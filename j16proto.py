#!/usr/bin/env python3
"""Wire protocol of the J16 tracker's USB config port.

Recovered by disassembling the frame builder at 0x4E88B8 in ENTools_V1065.exe
(the vendor tool) and confirmed against a live device on COM50.

A request is an ASCII line::

    "ATYS" + uppercase_hex(payload) + CRLF

where `payload` is binary::

    [0:2]    'YS'
    [2:11]   9 bytes, last one is a sequence number (the rest are zero)
    [11:13]  message type, big endian: 0x0201 write, 0x0202 read
    [13:15]  length of the command text, big endian
    [15:...] command text
    [...]    checksum: sum of every preceding payload byte, & 0xFF
    [...]    CR LF

Replies come back as the payload alone -- raw binary, no "ATYS", no hex --
with the type echoed as 0x8201 / 0x8202. Their command field is a 16-bit
length followed by the text and zero padding.

Command text is '#KEY' to read and '#KEY=value' to write; the type field
already says which, so the SZCS/CXCS prefixes the vendor tool displays never
reach the wire. Several settings fit in one message::

    #FREQ#APN#SERVPORT  ->  FREQ=15,APN=multigetrak.br,SERVPORT=5023
"""

HEADER = b"ATYS"
MARKER = b"YS"
MSG_WRITE, MSG_READ = 0x0201, 0x0202
ACK_WRITE, ACK_READ = 0x8201, 0x8202

# Live status, found by sweeping opcodes against the device: the firmware
# answers 0xF002 ("unsupported", echoing the opcode back) for everything it does
# not implement, which made the sweep safe to run.
MSG_MONI_SYS, MSG_MONI_GPS = 0x0100, 0x0101
ACK_MONI_SYS, ACK_MONI_GPS = 0x8100, 0x8101

# Reboot. Taken from the vendor tool's own EquManage handler, which does
# nothing but 'mov [obj+0x08], 0x0300' before calling its send routine; sending
# it with an empty payload dropped a live device's uptime from 107s to 1s.
# Its sibling buttons (PowerON/PowerOff) have no OnClick at all in the vendor
# DFM, so they are dead there too and are not worth wiring here.
MSG_RESET = 0x0300

# 0xF002 echoes back an opcode the firmware does not implement, which is what
# made a blind opcode sweep safe. 0xF000/0xF001 are acks for commands it does
# know -- RESET answers 0xF000 and reboots anyway.
ACK_UNSUPPORTED = 0xF002
ACK_OK0, ACK_OK1 = 0xF000, 0xF001

# 0x0301 is the vendor's "write server settings". Sent with an empty payload it
# blanks SERVIP and APN on the device -- never send it from here.
# 0x0340/0x0341 are the vendor's "cut fuel/power" and "restore" -- they drive
# the output relay, so they never go out from a config screen. 0x0370 (flight
# mode) and 0x0373 (external power off) take the tracker off the air.
MSG_PERIGOSO = {0x0301, 0x0340, 0x0341, 0x0370, 0x0373}

# --- movimento: colisao, gSensor, parada ------------------------------------
# Recovered from the vendor tool's ack dispatcher. Every reply opcode it knows
# sits in one of five jump tables (0x4E2FBC, 0x4E30BE, 0x4E30FB, 0x4E3222,
# 0x4E32A4 in ENTools_V1067.exe), each compiled as
#     add eax, -base ; cmp eax, n ; jmp [tabela + eax*4]
# so the entry index IS the opcode and the string its body prints names it.
# The request opcodes below were then confirmed at their send sites, where the
# tool writes 'mov [obj+8], opcode' exactly the way MSG_RESET does.
#
# There is no harsh-acceleration / harsh-braking / sharp-turn setting in this
# firmware: the accelerometer side is the collision alarm plus the raw gSensor
# registers, and "curva" is ANGLE_SEND/ANGLEVALUE on the config protocol.
MSG_COLISAO_SET, MSG_COLISAO_GET = 0x0385, 0x0386
ACK_COLISAO_SET, ACK_COLISAO_GET = 0x8385, 0x8386
MSG_GSENSOR_LER, ACK_GSENSOR_LER = 0x0317, 0x8317
MSG_GSENSOR_REGS, ACK_GSENSOR_REGS = 0x0512, 0x8512   # "gSensor record count"
MSG_VIB_CTRL, ACK_VIB_CTRL = 0x0380, 0x8380
MSG_PARADA, ACK_PARADA = 0x033C, 0x833C               # vendor: "stop report time"

# What the vendor tool prints for each reply it understands, so an answer to one
# of the opcodes above shows up in the log as words instead of loose bytes.
EVENTOS = {
    ACK_COLISAO_SET: "colisao: parametros gravados",
    ACK_COLISAO_GET: "colisao: parametros atuais",
    ACK_GSENSOR_LER: "gSensor: valor lido",
    ACK_GSENSOR_REGS: "gSensor: numero de registros",
    ACK_VIB_CTRL: "sensor de vibracao: controle",
    ACK_PARADA: "tempo de parada para reportar",
    0x8105: "flag de vibracao valida",
    0x8316: "gSensor: registrador gravado",
    0x8330: "estado da area sem sinal (blind)",
    0x8338: "consulta de estado do alarme apos reset",
    0x8115: "informacao de depuracao do sistema",
    0x8116: "informacao de depuracao (2)",
}

# Alarm codes the tracker puts in the GT06 packet it sends to the platform
# (VL100 protocol sheet, 5.3.1.17). This is the other side of the wire, not the
# USB port -- but it is where the harsh-driving events actually live, and the
# J16 speaks GT06 whenever PTL_SEL=0, so a platform log can be read with this.
ALARMES_GT06 = {
    0x00: "normal", 0x01: "SOS", 0x02: "falta de energia",
    0x03: "vibracao", 0x04: "entrou na cerca", 0x05: "saiu da cerca",
    0x06: "excesso de velocidade", 0x09: "movimento",
    0x0A: "entrou em sombra de GPS", 0x0B: "saiu de sombra de GPS",
    0x0E: "bateria externa baixa", 0x15: "desligou por bateria fraca",
    # 0x19 nao esta na tabela do GT06: foi deduzido dos quadros reais dos dois
    # aparelhos (bits 3-5 do Terminal Information = 3 "low battery", nivel de
    # bateria 2 e 3, e os dois dispararam dentro da janela em que a alimentacao
    # externa estava cortada). Sem ele a plataforma so mostra o codigo cru.
    0x19: "bateria interna fraca",
    0x29: "aceleracao brusca", 0x2C: "colisao", 0x2D: "capotamento",
    0x30: "desaceleracao brusca (freada)", 0x4C: "curva brusca",
    0xFE: "ignicao ligada", 0xFF: "ignicao desligada",
}

# 0 / 1 / 2 as the vendor's own combo box lists them.
COLISAO_MODOS = ["desligado", "vetor (soma dos 3 eixos)", "eixo unico"]

HEAD_LEN = 15          # marker + 9 id bytes + type + length
TAIL_LEN = 3           # checksum + CR + LF
_TYPES = {MSG_WRITE, MSG_READ, ACK_WRITE, ACK_READ,
          MSG_MONI_SYS, MSG_MONI_GPS, ACK_MONI_SYS, ACK_MONI_GPS,
          MSG_RESET, ACK_UNSUPPORTED, ACK_OK0, ACK_OK1} | set(EVENTOS)

# System Status codes, in the order the vendor tool lists them.
ESTADOS = [
    "Init", "Wait Reg Net", "Begin PPP", "Wait PPP", "Call Deal Begin",
    "Call Deal Wait", "DNS Begin", "DNS Wait", "Socket Begin", "Socket Wait",
    "Reg Server Begin", "Reg Server Wait", "Login Server Begin",
    "Login Server Wait", "Goto Idle", "Normal Connect", "Re Connect Begin",
    "Re Connect Wait", "Deep Sleep Begin", "Deep Sleep Wait", "Wait Active",
    "Reset Delay", "Reset Doing", "Goto Fly Mode", "Fly Mode", "Attach Begin",
    "Attach Wait",
]


def encode(text, mtype, seq=0):
    """Build the on-the-wire request line for one command."""
    data = text.encode() if isinstance(text, str) else text
    p = bytearray(MARKER)
    p += b"\x00" * 8 + bytes([seq & 0xFF])
    p += bytes([mtype >> 8, mtype & 0xFF, len(data) >> 8, len(data) & 0xFF])
    p += data
    p.append(sum(p) & 0xFF)
    p += b"\r\n"
    return HEADER + p.hex().upper().encode() + b"\r\n"


def read_frame(keys, seq=0):
    return encode("".join(f"#{k}" for k in keys), MSG_READ, seq)


def write_frame(pairs, seq=0):
    return encode("".join(f"#{k}={v}" for k, v in pairs), MSG_WRITE, seq)


def decode(buf, descarte=None):
    """Pull complete reply frames out of a byte stream.

    Returns (frames, leftover) where each frame is (mtype, seq, text). Junk
    before a marker is skipped, so an unsolicited debug burst from the
    firmware cannot desynchronise the parser.

    Skipping is not the same as throwing away: pass a bytearray as `descarte`
    and every byte the scanner steps over lands there. The module interleaves
    plain text lines with binary frames, and with the monitor running about one
    frame per second there is always a frame right after the text -- so the
    text was being eaten here, before anyone could read it.
    """
    frames = []
    i = 0
    while True:
        start = buf.find(MARKER, i)
        if start < 0:
            tail = buf[i:]
            # 256, nao 64: o modulo tambem manda linhas de texto de posicao, e
            # cortar a cauda curta demais comia o comeco da linha antes de
            # alguem poder le-la.
            if descarte is not None and len(tail) > 256:
                descarte.extend(tail[:-256])
            return frames, tail[-256:] if len(tail) > 256 else tail
        if descarte is not None and start > i:
            descarte.extend(buf[i:start])
        if len(buf) < start + HEAD_LEN:
            return frames, buf[start:]
        mtype = (buf[start + 11] << 8) | buf[start + 12]
        if mtype not in _TYPES:
            # a stray 'YS' inside binary padding -- not a real frame, keep scanning
            if descarte is not None:
                descarte.extend(buf[start:start + len(MARKER)])
            i = start + len(MARKER)
            continue
        dlen = (buf[start + 13] << 8) | buf[start + 14]
        end = start + HEAD_LEN + dlen + TAIL_LEN
        if len(buf) < end:
            return frames, buf[start:]
        data = buf[start + HEAD_LEN:start + HEAD_LEN + dlen]
        # config replies wrap their text in a 16-bit length; status frames are
        # raw binary, so those are handed back as bytes for the caller to parse
        texto = unpack_text(data) if mtype in (ACK_READ, ACK_WRITE) else data
        frames.append((mtype, buf[start + 10], texto))
        i = end


def unpack_text(data):
    """Reply command field: 16-bit text length, the text, then zero padding."""
    if len(data) < 2:
        return ""
    n = (data[0] << 8) | data[1]
    return data[2:2 + n].decode("latin-1", "replace")


def parse_values(text):
    """'FREQ=15,APN=x.br' -> {'FREQ': '15', 'APN': 'x.br'}"""
    out = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        key = key.strip()
        if not (sep and key):
            continue
        value = value.strip()
        # a value carrying control/8-bit bytes is a mis-sliced frame, not real
        # data -- drop it so callers keep the last good value instead of garbage
        if value and any(not (32 <= ord(c) < 127) for c in value):
            continue
        out[key] = value
    return out


def _u(data, off, n):
    return int.from_bytes(data[off:off + n], "little") if len(data) >= off + n else 0


def _sn(v, sim="sim", nao="nao"):
    return sim if v else nao


def parse_moni_sys(p):
    """Decode the 96-byte 0x8100 status frame.

    The eight leading flag bytes come straight out of the vendor tool's own
    parser, which reads them as `cmp byte [esi+N], 1` right before picking
    "Power:1"/"Power:0" and friends -- so those offsets are its offsets, not a
    guess. The counters that follow keep the same field order the vendor struct
    uses, packed as 16-bit on the wire. Run Time was confirmed by two reads 40s
    apart (+40) and Voltage by matching 12.4V on the bench supply.
    """
    if len(p) < 96:
        return {}
    estado = p[0]
    seg = _u(p, 32, 4)
    bat = _u(p, 12, 2)
    return {
        "System Status": ESTADOS[estado] if estado < len(ESTADOS) else f"? ({estado})",
        "SIM": _sn(p[1], "presente", "ausente"),
        "REG": _sn(p[2], "registrado", "fora da rede"),
        "Defences": _sn(p[3], "armado", "desarmado"),
        "CSQ": f"{p[4]} ({_qualidade(p[4])})",
        "ACC": _sn(p[5], "ligada", "desligada"),
        "Power": _sn(p[6], "conectada", "cortada"),
        "Sleep": _sn(p[7], "dormindo", "acordado"),
        "AreaID": _u(p, 8, 2), "CellID": _u(p, 10, 2),
        "Battery": f"{bat / 1000:.2f} V" if 2000 < bat < 5000 else str(bat),
        "PPP Times": _u(p, 14, 2),
        "Sms Send": _u(p, 16, 2), "Sms Rec": _u(p, 18, 2),
        "Socket Send": _u(p, 20, 2), "Socket Receive": _u(p, 22, 2),
        "Call IN": _u(p, 24, 2), "Call Out": _u(p, 26, 2),
        "Mileage": f"{_u(p, 28, 4) / 1000:.1f} km",
        "Run Time": f"{seg // 3600}h {seg % 3600 // 60}m {seg % 60}s",
        "SIM IMSI": p[36:52].split(b"\x00")[0].decode("latin-1", "replace"),
        "NET": f"{_u(p, 54, 2)}-{_u(p, 52, 2):02d}",     # MCC-MNC
        "Band": _banda(p[58]),
        "Vibration": _sn(p[59], "detectada", "parado"),
        "Voltage": f"{p[94] / 10:.1f} V",
        "raw": p.hex(" "),
    }


# The vendor tool branches on this byte at 128 and again at 163, then indexes a
# name table that only ever got 2G entries -- which is why its own screen shows
# "Band:NONE" on a 4G tracker. Anything at or above 160 is an LTE band, so say
# so instead of repeating their blank.
_BANDAS_2G = ["NONE", "GSM900", "DCS1800", "PCS1900", "GSM450", "GSM480", "GSM850"]


def _banda(v):
    if v >= 160:
        return f"4G / LTE (codigo {v})"
    if 1 <= v < len(_BANDAS_2G):
        return f"2G / {_BANDAS_2G[v]}"
    return "sem leitura" if v == 0 else f"codigo {v}"


def _qualidade(csq):
    """CSQ is the standard 0-31 GSM scale; 99 means 'no reading'."""
    if csq >= 99:
        return "sem leitura"
    if csq >= 20:
        return "otimo"
    if csq >= 15:
        return "bom"
    if csq >= 10:
        return "fraco"
    return "muito fraco"


def parse_moni_gps(p):
    """Decode the 53-byte 0x8101 frame.

    DateTime sits at bytes 16..21 as yy mm dd hh mm ss in UTC -- three captures
    taken seconds apart matched the PC clock to the second. The vendor struct
    puts Longitude and Latitude immediately before its DateTime field, and two
    32-bit values land exactly on byte 16, which is where they are read from
    here. Without a satellite fix the module publishes stale coordinates, so
    they are only reported once Status says there is one.
    """
    if len(p) < 23:
        return {}
    # "Status: A/W/S" on the vendor screen is three separate dword tests in its
    # code -- valid, E/W, N/S -- and our frame's bytes 0,1,2 reproduce it exactly.
    tem_fix = p[0] == 1
    hemi_lon = "E" if p[1] == 1 else "W"
    hemi_lat = "N" if p[2] == 1 else "S"
    sats = _satelites(p)
    a, me, dia, h, mi, seg = p[16:22]
    data = (f"20{a:02d}-{me:02d}-{dia:02d} {h:02d}:{mi:02d}:{seg:02d} UTC"
            if 1 <= me <= 12 and 1 <= dia <= 31 else "--")
    out = {
        "Status": (f"fix valido ({hemi_lon}/{hemi_lat})" if tem_fix
                   else f"sem fix ({hemi_lon}/{hemi_lat})"),
        # Mapa confirmado no ENTools V1065, na rotina que desenha a janela
        # "Euqipment Moni": ela imprime rec+0x1C como Speed, rec+0x20 como
        # Angle, rec+0x24 como Collect Times e rec+0x28 como DHOP -- este
        # ultimo com 'fild' seguido de 'fdiv 10.0', ou seja, um byte que vale
        # um decimo. Cruzando com o que o V1067 escreve nesses campos:
        #   rec+0x1C <- payload[4:6] LE    -> velocidade
        #   rec+0x20 <- payload[6:8] LE    -> proa
        #   rec+0x24 <- 16 bits BE apos a tabela -> contador de leituras
        #   rec+0x28 <- payload[3]         -> HDOP x 10
        # Estavam todos aqui desde sempre: payload[3] vinha rotulado como
        # numero de satelites e payload[6:8] como contador.
        "Velocidade": f"{_u(p, 4, 2)} km/h",
        "Proa": f"{_u(p, 6, 2)}\u00b0",
        "HDOP": f"{p[3] / 10:.1f}",
        "Collect Times": _extra16(p),
        "DateTime": data,
        "sats": " ".join(f"{n}:{v}" for n, v in sats),
        # o proprio ComTools mostra como "Staellite" o tamanho da tabela
        "Satellite": len(sats),
        "com sinal": sum(1 for _, v in sats if v),
        "raw": p.hex(" "),
    }
    if tem_fix:
        out["Longitude"] = _coord(p, 8, hemi_lon)
        out["Latitude"] = _coord(p, 12, hemi_lat)
        # plain decimals too, for whoever wants to hand them to a map
        out["_lon"] = _decimal(p, 8, hemi_lon)
        out["_lat"] = _decimal(p, 12, hemi_lat)
    return out


# Chaves da linha de texto de posicao, na ordem em que o ENTools as procura
# (tabela de strings em 0x4BDEF8..0x4BDF7C, lidas pelo parser em 0x4BDC3C).
# Essa linha -- e nao o quadro 0x8101 -- e o que alimenta as colunas de
# velocidade, proa e HDOP da janela do fabricante.
TEXTO_GPS = {
    "E:": "Erro", "SC:": "SC", "DC:": "DC", "dis:": "Distancia",
    "SecDis:": "Distancia no intervalo", "logi:": "_lon", "lati:": "_lat",
    "spd:": "Velocidade", "course:": "Proa", "precision:": "HDOP",
}


def parse_texto_gps(linha):
    """Decode a position line like

        SecDis:4,logi:113.880413,lati:22.571707,course:73,spd:0,precision:12

    Returns {} for anything that is not one. Values stay as read except the two
    coordinates, which come back as floats so a map link can use them.
    """
    if "logi:" not in linha and "spd:" not in linha:
        return {}
    out = {}
    for parte in linha.replace(";", ",").split(","):
        chave, sep, valor = parte.strip().partition(":")
        if not sep:
            continue
        nome = TEXTO_GPS.get(chave.strip() + ":")
        if not nome:
            continue
        valor = valor.strip()
        if nome in ("_lon", "_lat"):
            try:
                out[nome] = float(valor)
            except ValueError:
                continue
        else:
            out[nome] = valor
    return out


# O G900L nao tem o quadro binario 0x0100, entao "Vibration" nunca chegaria
# pela tela. Mas ele cospe sozinho uma linha por tranco enquanto o sensor esta
# ligado -- medido em 14-09-2026 com VIBL=1, uma linha por segundo enquanto o
# aparelho era sacudido:
#
#     2026-09-14 19:51:53  [GSENSOR]>>>shake<<< [2,0,0]
#
# O primeiro numero entre colchetes e o nivel do tranco; os outros dois ficaram
# zerados em toda a medicao.
def parse_shake(linha):
    """Linha de tranco do gSensor -> {'Vibration': 'nivel 2 as 19:51'}.

    Devolve {} para qualquer outra linha. Mostra a HORA do ultimo tranco em vez
    de "detectada": sem quadro de status nao da para saber quando ele parou, e
    um "detectada" que nunca volta para "parado" mente depois do primeiro
    solavanco.
    """
    if ">>>shake<<<" not in linha:
        return {}
    nivel = linha.rpartition("[")[2].strip("] ").split(",")[0].strip()
    hora = linha.partition(" ")[2].strip().partition(" ")[0]
    if hora.count(":") != 2:
        hora = ""
    texto = f"nivel {nivel}"
    return {"Vibration": f"{texto} as {hora[:5]}" if hora else texto}


def _num_rmc(campo, fator, sufixo, casas=1):
    """Numero de uma sentenca RMC, ou "--" quando o campo vem vazio/ilegivel."""
    try:
        return f"{float(campo) * fator:.{casas}f}{sufixo}"
    except ValueError:
        return "--"


def parse_nmea(linha):
    """Decode the two NMEA sentences that carry what 0x8101 does not.

    RMC gives speed (knots) and course; GGA gives HDOP, satellites used and
    the fix flag. The SimCom module publishes both on its NMEA port, which is
    a sibling of the AT port this tool normally talks to -- same physical
    device, different COM. Returns {} for any other sentence.
    """
    if not linha.startswith("$") or "," not in linha:
        return {}
    campos = linha.split("*")[0].split(",")
    tipo = campos[0][3:]          # $GPRMC / $GNRMC -> RMC
    out = {}
    if tipo == "RMC" and len(campos) > 8:
        if campos[2] != "A":      # 'V' = sem fix: os numeros nao valem nada
            return {}
        # Parado, o receptor manda o campo de rumo VAZIO -- nao ha direcao a
        # informar quando nao se anda. Omitir a chave aqui parecia inofensivo e
        # nao era: a tela guarda o ultimo valor, entao o rumo da primeira
        # sentenca com movimento ficava fixo na tela para sempre, como se fosse
        # a leitura de agora. Devolver "--" diz a verdade: indefinido neste
        # instante.
        out["Velocidade"] = _num_rmc(campos[7], 1.852, " km/h")
        out["Proa"] = _num_rmc(campos[8], 1.0, "\u00b0", casas=0)
    elif tipo == "GGA" and len(campos) > 8:
        if campos[6] in ("", "0"):
            return {}
        out["HDOP"] = campos[8]
        if campos[7]:
            out["Satellite"] = str(int(campos[7]))
    return out


def parse_colisao(p):
    """Reply to MSG_COLISAO_GET: three bytes, the way the vendor tool reads them
    (mode at payload[0], then threshold and detection count -- its handler is a
    switch on byte 0 followed by two IntToStr of bytes 1 and 2).
    """
    if len(p) < 3:
        return {}
    modo = p[0] if p[0] < len(COLISAO_MODOS) else None
    return {
        "Colisao": COLISAO_MODOS[modo] if modo is not None else f"codigo {p[0]}",
        "Limiar": p[1],
        "Deteccoes": p[2],
    }


def encode_colisao(modo, limiar, vezes, seq=0):
    """Frame for MSG_COLISAO_SET. The vendor builds a 4-byte payload: combo
    index, threshold, count, and a zero byte it never fills.
    """
    if not 0 <= modo < len(COLISAO_MODOS):
        raise ValueError(f"modo de colisao invalido: {modo}")
    corpo = bytes([modo, limiar & 0xFF, vezes & 0xFF, 0])
    return encode(corpo, MSG_COLISAO_SET, seq)


def _frac(p, off):
    """Fraction of a minute, packed as two decimal bytes: hundredths of a
    minute then ten-thousandths. Not a binary 16-bit value -- every one of
    these bytes across the captures lands in 0..99 (78,69 / 57,30 / 77,96 /
    56,83), which no binary scale would respect, and reading them as
    decimal is what puts the two frames of a parked tracker 9 m apart and
    on the same spot the vendor screen showed (5434.7685 / 2027.5804).
    """
    return (p[off + 2] * 100 + p[off + 3]) / 10000.0


def _decimal(p, off, hemi):
    dec = p[off] + (p[off + 1] + _frac(p, off)) / 60.0
    return -dec if hemi in ("W", "S") else dec


def _coord(p, off, hemi):
    """Position is split the way NMEA writes it: a degrees byte, a minutes byte,
    then the fraction of a minute. Degrees and minutes were confirmed against the
    vendor screen -- 0x36,0x22 for its "5434.7685" and 0x14,0x1b for "2027.5804".
    """
    graus, minutos = p[off], p[off + 1]
    frac = _frac(p, off)
    return (f"{graus}°{minutos + frac:07.4f}' {hemi}  "
            f"({_decimal(p, off, hemi):+.5f})")


def _s32(data, off):
    return int.from_bytes(data[off:off + 4], "little", signed=True)


def _satelites(p):
    """Trailing (PRN, SNR) table.

    Not a guess any more: the vendor's own 0x8101 handler reads the pair count
    from byte 22 and then walks that many pairs starting at byte 23, clamping at
    24 pairs. Both captured frames end exactly on 23 + 2*count + 2, which is what
    confirms it -- the 53-byte frame carries 14 pairs, the 57-byte one carries 16.
    """
    n = min(p[22], 24) if len(p) > 22 else 0
    if 23 + 2 * n > len(p):
        return []
    return [(p[23 + 2 * k], p[24 + 2 * k]) for k in range(n)]


def _extra16(p):
    """The 16-bit big-endian field the vendor reads right after the satellite
    table.

    Parsed, never displayed: a scan of all 65 references to the vendor's GPS
    record (0x4FE5DC) shows it writes this field and then never reads it back,
    same as the 16 bits at payload[4:5]. ComTools itself does not show them, so
    there is no label to copy and no way to name it from the binary. Kept here
    because it is part of the frame layout, with the value from both captures
    pinned in the selftest (26 and 0x2D27) for whoever identifies it later.
    """
    fim = 23 + 2 * min(p[22], 24) if len(p) > 22 else 0
    if fim + 2 > len(p):
        return None
    return (p[fim] << 8) | p[fim + 1]


# ---------------------------------------------------------------- Cantrack
# O G900L nao fala ATYS: recusa todo quadro binario com "CFG CMD UNKNOWN!!!".
# Ele usa comandos de texto terminados em "#" e responde
# ">>cmdAckStr:<conteudo>, len:N". Detalhes em
# docs/engenharia-reversa/ENGENHARIA_REVERSA_G900L.md.

# Consulta que serve de aperto de mao: so este firmware responde "VER:".
CANTRACK_VERSAO = "VERSION#"

# Leitura completa na conexao. Ordem importa: identidade primeiro, para o painel
# preencher o nome do aparelho antes do resto.
CANTRACK_LEITURA = [
    "VERSION#", "PARAM#", "STATUS#", "WHERE#", "CELL#",
    "SERVER#", "APN#",
    "TIMER#", "HBT#", "GMT#", "SPEED#",
    "SENALM#", "POWERALM#", "BATALM#", "MOVING#",
    "ACCALM#", "ACCOFFALM#", "SOSALM#", "STOCKADEALM#", "CENTER#",
    "RFID,ENABLE#",
    "CXCS#PULSE", "CXCS#SLPDISCONNECT", "CXCS#GT06GPRSGMT", "CXCS#GT06SEL",
    "CXCS#GT06ICCID", "CXCS#GT06IEXVOL", "CXCS#GT06METER",
    # achadas na varredura de 14-09-2026: o firmware le mais seis chaves do
    # dicionario do J16 do que a primeira medicao tinha encontrado
    "CXCS#ANGLEVALUE", "CXCS#GPS_DISSLP", "CXCS#GPS_FINTER_EN", "CXCS#SLEEPT",
    "CXCS#VIBL", "CXCS#SOURCE_OFF_TYPE",
    "MILEAGE#",
]

# Consultas que devolvem chaves da tabela de parametros sem passar por CXCS#.
# Medido no aparelho em 14-09-2026: CXCS# nessas chaves nao responde nada, mas o
# comando de consulta do dialeto SMS responde. Sem este mapa a tela ficava vazia
# nos cinco campos de servidor e APN.
CANTRACK_CONSULTA_PARAM = {
    "SERVER#": ("SERVIP", "SERVPORT"),
    "APN#": ("APN", "USERPPP", "PWPPP"),
    "TIMER#": ("FREQ", "TIMER"),
    # "HBT" NAO entra aqui: o PARAM# devolve so o primeiro intervalo ("HBT:180"),
    # o HBT# devolve os dois ("HBT ACC ON:180s,ACC OFF:300s"). Com a chave
    # listada, a releitura escolhia o PARAM# e acusava "gravei 180,300, o
    # aparelho tem 180" numa gravacao que tinha dado certo.
    "PARAM#": ("IMEI", "TIMER", "AGNS", "TZ", "DRV", "GM", "IC",
               "1A", "2A", "3A", "D", "ES", "SW", "L"),
    "VERSION#": ("SOFTVERSION",),
    "HBT#": ("HBT",),
    "GMT#": ("GMT",),
    "SPEED#": ("SPEED",),
    "SENALM#": ("SENALM",),
    "POWERALM#": ("POWERALM",),
    "BATALM#": ("BATALM",),
    "MOVING#": ("MOVING",),
    "ACCALM#": ("ACCALM",),
    "ACCOFFALM#": ("ACCOFFALM",),
    "SOSALM#": ("SOSALM",),
    "STOCKADEALM#": ("STOCKADEALM",),
    "CENTER#": ("CENTER",),
    "RFID,ENABLE#": ("RFID_ENABLE",),
}

# Nome que vem na resposta -> nome da linha da tabela. Tudo que esta aqui deixa
# de cair no log como "_minusculo" e passa a ocupar uma linha. O mesmo valor
# chega por dois caminhos (PARAM# manda "TIMER:20,3600", TIMER# manda
# "TIMER ACC ON:20s,ACC OFF:3600s"); vale o ultimo lido, que e o mais legivel.
_CANTRACK_CFG = {
    "TIMER": "TIMER", "TIMER ACC ON": "TIMER",
    "HBT ACC ON": "HBT",          # o "HBT:180" do PARAM# e parcial: vai para o log
    "GMT": "GMT", "SPEED": "SPEED",
    "SENALM": "SENALM", "POWERALM": "POWERALM", "BATALM": "BATALM",
    "MOVING": "MOVING", "ACCALM": "ACCALM", "ACCOFFALM": "ACCOFFALM",
    "SOSALM": "SOSALM", "STOCKADEALM": "STOCKADEALM",
    "CENTER,A": "CENTER", "RFID,ENABLE": "RFID_ENABLE",
    "AGNS": "AGNS", "TZ": "TZ", "DRV": "DRV", "GM": "GM", "IC": "IC",
    "1A": "1A", "2A": "2A", "3A": "3A", "D": "D", "ES": "ES", "SW": "SW",
    "L": "L",
}
# NAO SABEMOS PARA QUE SERVEM (so aparecem no PARAM#, sem comando proprio de
# leitura/escrita conhecido). Deixados passar como estao, sem interpretar.
# Decidido em 16/09/2026 ignorar ate ter necessidade real. Valores tipicos:
#   1A: 30       -- talvez limiar de algum alarme
#   2A: 0,0,0    -- ?
#   D:  0        -- ?
#   ES: 0        -- ?
#   SW: c (hex)  -- parece mascara de bits
#   L:  0        -- ?
#   GM: 2        -- ?
#   IC: 0,0      -- confirmado que NAO e ICCID
# (3A = alarme de deslocamento, mexido por move654321; DRV = perfil de conducao;
#  AGNS ~ AGPS; TZ = fuso -- estes a gente entende.)

# Das 90 linhas da tabela do J16, o G900L so trata estas. As sete primeiras
# ele le e grava; as seis ultimas ele SO grava -- CXCS nelas nao responde nada.
# Esconder o resto e a diferenca entre uma tela vazia e uma tela honesta.
CANTRACK_PARAMS = {
    "PULSE", "SLPDISCONNECT", "GT06GPRSGMT", "GT06SEL", "GT06ICCID",
    "GT06IEXVOL", "GT06METER",
    "SERVIP", "SERVPORT", "APN", "USERPPP", "PWPPP", "FREQ",
    # ICCID, IMSI e GPS_VER so aparecem no modo de teste (AT+ZDR=debug) ou no
    # log de diagnostico (<ZDRCMD*LOG:1>) -- medido em 15-09-2026. Ficam na
    # tabela porque agora tem de onde vir.
    "IMEI", "SOFTVERSION", "ICCID", "IMSI", "GPS_VER",
    # MIL (odometro) so sai no log de diagnostico (<ZDRCMD*LOG:1>), como ICCID
    "MIL",
    "ANGLEVALUE", "GPS_DISSLP", "GPS_FINTER_EN", "SLEEPT", "VIBL",
    "SOURCE_OFF_TYPE",
} | set(_CANTRACK_CFG.values())

# Estas chaves NAO se gravam por "SZCS#CHAVE=valor": medido no aparelho em
# 14-09-2026, o quadro sai, o firmware nao responde nada e o valor antigo fica.
# A forma que ele aceita e a do conjunto de SMS da familia GT06 -- "CHAVE,valor#"
# -- e a resposta ja vem com o estado novo ("SENALM,OFF#" -> "SENALM:OFF").
# O HBT quer os dois intervalos: "HBT,180,300#"; com um so nao responde.
CANTRACK_ESCRITA_SMS = {
    "SENALM", "MOVING", "ACCALM", "ACCOFFALM", "SOSALM", "STOCKADEALM",
    "POWERALM", "BATALM", "SPEED", "TIMER", "HBT", "GMT", "RFID_ENABLE",
    "APN",
}

_APN_TRIO = ("APN", "USERPPP", "PWPPP")


def juntar_apn(pairs, lidos=None):
    """Junta APN, usuario e senha num par so: ('APN', 'nome,user,senha').

    No G900L os tres sao UM comando -- "APN,nome,user,senha#", igual a resposta
    de APN# ("APN:em,,"). Mandados separados por "SZCS#APN=..." o aparelho
    responde CFGSZCS, reinicia e volta com o APN velho: medido em 15-09-2026,
    gravou avatek.br e leu de volta "em". As partes que o tecnico nao mexeu
    entram com o valor lido do aparelho -- comando incompleto apaga o resto.
    """
    lidos = lidos or {}
    trio = {k: v for k, v in pairs if k in _APN_TRIO}
    if not trio:
        return list(pairs)
    campos = [trio.get(k, lidos.get(k, "")) or "" for k in _APN_TRIO]
    fora = [(k, v) for k, v in pairs if k not in _APN_TRIO]
    return fora + [("APN", ",".join(campos))]


def cantrack_escrita(chave, valor):
    """Comando de gravacao no dialeto do G900L.

    'SENALM','OFF' -> 'SENALM,OFF#'      (conjunto de SMS)
    'PULSE','20'   -> 'SZCS#PULSE=20'    (dicionario do J16)
    """
    if chave == "RFID_ENABLE":
        return f"RFID,ENABLE,{valor}#"
    if chave in CANTRACK_ESCRITA_SMS:
        return f"{chave},{valor}#"
    return f"SZCS#{chave}={valor}"


# Campos do painel que o G900L alimenta. O que nao esta aqui ele nunca
# reporta -- nao adianta deixar a linha na tela mostrando "--" para sempre.
CANTRACK_CAMPOS_TELA = {
    "_modelo", "ACC", "Battery", "Sleep", "Proa", "DateTime", "Latitude",
    "Vibration",
    "Longitude", "Velocidade", "CSQ", "Voltage", "Power", "System Status",
    "REG", "Status", "AreaID", "CellID", "NET", "Mileage",
}

# O monitor alterna estas duas: uma da o estado eletrico e de rede, a outra a
# posicao. Nao existe quadro de status binario neste firmware.
CANTRACK_MONITOR = ["STATUS#", "WHERE#"]

# Nome do campo do aparelho -> nome do campo do painel. O que nao esta aqui vai
# para o log com o nome original, que e melhor que sumir.
_CANTRACK_CAMPOS = {
    "ACC": "ACC",
    "Battery": "Battery",
    "Course": "Proa",
    "Cur Mileage Value": "Mileage",      # resposta do MILEAGE#
    "DateTime": "DateTime",
}


def _cantrack_grau(campo):
    """'S20.460865' -> -20.460865. None quando o campo nao e coordenada."""
    if not campo or campo[0] not in "NSEW":
        return None
    try:
        valor = float(campo[1:])
    except ValueError:
        return None
    return -valor if campo[0] in "SW" else valor


def _cantrack_pos(resto):
    """'Lati:N0.00,E0.00,Course:0,Speed:0.00,DateTime:...' -> campos do painel.

    A longitude vem sem nome nenhum, colada na latitude -- e o unico campo do
    protocolo que depende da posicao na linha em vez da etiqueta.
    """
    out = {}
    partes = resto.split(",")
    if partes and partes[0].strip():
        out["Latitude"] = partes[0].strip()
    if len(partes) > 1 and partes[1].strip() and ":" not in partes[1]:
        out["Longitude"] = partes[1].strip()
    # o botao do mapa precisa de numero, nao do texto "S20.460865"
    lat, lon = _cantrack_grau(out.get("Latitude")), _cantrack_grau(out.get("Longitude"))
    if lat is not None and lon is not None and (lat or lon):
        out["_lat"], out["_lon"] = lat, lon
    elif "Latitude" in out:
        # Sem fix o G900L responde "N0.000000,E0.000000". Mostrar isso e pior que
        # mostrar nada: zero e uma coordenada valida no golfo da Guine, e o
        # tecnico fica esperando o mapa abrir num lugar que o aparelho nunca viu.
        out.pop("Latitude", None)
        out.pop("Longitude", None)
    for parte in partes[2:]:
        chave, sep, valor = parte.partition(":")
        if not sep:
            continue
        chave, valor = chave.strip(), valor.strip()
        if chave == "Speed":
            out["Velocidade"] = f"{valor} km/h"
        elif chave in _CANTRACK_CAMPOS:
            out[_CANTRACK_CAMPOS[chave]] = valor
    # Parado nao ha rumo, e o G900L manda "Course:0" do mesmo jeito -- o zero e
    # ausencia de dado, nao norte. Mostrar 0 grau com o carro na garagem e dizer
    # que ele aponta para o norte. "--" e o mesmo que o RMC ja faz aqui.
    if "Proa" in out:
        vel = out.get("Velocidade", "").split()[0]
        parado = vel in ("", "0", "0.0", "0.00")
        out["Proa"] = "--" if parado else out["Proa"] + "°"
    return out


def _tempos(valor):
    """'20s,ACC OFF:3600s' -> '20,3600'.  '20,3600' -> '20,3600'.

    TIMER# e HBT# devolvem o rotulo do segundo intervalo grudado no valor. A
    linha da tela e o que volta para o aparelho na gravacao ("TIMER,20,3600#"),
    entao ela tem de conter os numeros e nada mais.
    """
    nums, atual = [], ""
    for c in valor:
        if c.isdigit():
            atual += c
        elif atual:
            nums.append(atual)
            atual = ""
    if atual:
        nums.append(atual)
    return ",".join(nums)


def _mv(v):
    """'12123mV' -> '12.12 V'."""
    n = "".join(c for c in v if c.isdigit())
    return f"{int(n) / 1000:.2f} V" if n else v


# Linha do log de diagnostico ("PBLOG"), ligado por <ZDRCMD*LOG:1>. Vem em
# bloco, uma linha por assunto comecando com "-->", a cada 6 s. E mais rico que
# o bloco do AT+ZDR=debug: traz IMSI, CSQ, intervalos e o servidor em uso.
def _depois(corpo, chave, ate=";,"):
    """Valor de 'CHAVE:valor' dentro da linha, ate o primeiro separador."""
    alvo = chave + ":"
    i = corpo.find(alvo)
    if i < 0:
        return None
    j = i + len(alvo)
    for k in range(j, len(corpo)):
        if corpo[k] in ate:
            return corpo[j:k].strip()
    return corpo[j:].strip()


def _pblog(txt):
    """Uma linha "-->..." do log de diagnostico -> (moni, cfg), ou None."""
    if not txt.startswith("-->"):
        return None
    corpo, moni, cfg = txt[3:], {}, {}
    for chave in ("ICCID", "IMEI", "IMSI"):
        v = _depois(corpo, chave)
        if v and v.isdigit() and len(v) >= 10:
            cfg[chave] = v
    vkk, bat = _depois(corpo, "VKK"), _depois(corpo, "BAT")
    if vkk and vkk.isdigit():
        moni["Voltage"] = _mv(vkk)
        moni["Power"] = "ausente" if moni["Voltage"].startswith("0.0") else "presente"
    if bat and bat.isdigit():
        moni["Battery"] = _mv(bat)
    csq = _depois(corpo, "CSQ")
    if csq and csq.isdigit():
        moni["CSQ"] = f"{csq} ({_qualidade(int(csq))})"
    dns = _depois(corpo, "DNS", ate=";")       # "200.152.062.020:13346"
    if dns and ":" in dns:
        ip, _, porta = dns.rpartition(":")
        if porta.isdigit():
            cfg["SERVIP"], cfg["SERVPORT"] = ip.strip(), porta
    if corpo.startswith("APN:"):
        cfg["APN"] = _depois(corpo, "APN") or ""
        cfg["USERPPP"] = _depois(corpo, "U") or ""
        cfg["PWPPP"] = _depois(corpo, "P") or ""
    itv, sri = _depois(corpo, "ITV"), _depois(corpo, "SRI")
    if itv and itv.isdigit():
        cfg["FREQ"] = itv
        if sri and sri.isdigit():
            cfg["TIMER"] = f"{itv},{sri}"
    ht = _depois(corpo, "HT", ate=";")         # "180,300"
    if ht and ht.replace(",", "").isdigit():
        cfg["HBT"] = ht
    gv = _depois(corpo, "GPSVER", ate=";")     # "SW=URANUS5,V5.3.2.0, MODTYP:2,1"
    if gv:
        cfg["GPS_VER"] = gv.split(",")[0] + ("," + gv.split(",")[1]
                                             if "," in gv else "")
    net = _depois(corpo, "CURNET", ate=";")    # "LTE,Online"
    if net and "," in net:
        tec, _, estado = net.partition(",")
        moni["NET"] = tec
        moni["System Status"] = estado
        moni["REG"] = "sim" if estado.lower() == "online" else "nao"
    dif = _depois(corpo, "DIF", ate=";")       # "16,14" -- leitura crua do impacto
    if dif and dif.replace(",", "").isdigit():
        moni["Impacto"] = dif
    mil = _depois(corpo, "MIL", ate=";")       # "0,202" -- odometro
    if mil and mil.replace(",", "").isdigit():
        cfg["MIL"] = mil
    return (moni, cfg) if (moni or cfg) else None


# checklist do autoteste (AT+ZDR=debug): cada item e OK (passou) ou NG (falhou).
# LOGIN:NG foi o sintoma que denunciou a perda do servidor -- por isso entra.
_TESTE_CHECKLIST = {
    "CEXTV": "_teste_alim", "GPS": "_teste_gps", "CSQ": "_teste_csq",
    "G_SENSOR": "_teste_gsensor", "PDP": "_teste_pdp", "LOGIN": "_teste_login",
    "SOS": "_teste_sos", "ACC": "_teste_acc", "IBT": "_teste_ibt",
    "FSPARML": "_teste_fsparml",
}


def _teste(txt):
    """Uma linha do bloco de AT+ZDR=debug -> (moni, cfg), ou None se nao for.

    O bloco vem solto, uma linha por vez, sem ';' e sem 'cmdAckStr' -- por isso
    nao passa pelo laco geral. Os OK/NG sao um checklist de fabrica: cada um diz
    se aquela parte do aparelho respondeu na hora do teste.
    """
    chave, sep, valor = txt.partition(":")
    if not sep:
        return None
    chave, valor = chave.strip().upper(), valor.strip().rstrip(",")
    if chave == "ICCID" and valor.isdigit():
        return {}, {"ICCID": valor}
    if chave == "GPS_VER":
        return {}, {"GPS_VER": valor}
    if chave == "IMEI" and valor.isdigit():
        return {}, {"IMEI": valor}
    if chave == "SATVAL" and valor.isdigit():
        return {"Satellite": valor}, {}
    if chave == "EVKK":
        volts = _mv(valor)
        return {"Voltage": volts,
                "Power": "ausente" if volts.startswith("0.0") else "presente"}, {}
    if chave == "VBAT":
        return {"Battery": _mv(valor)}, {}
    if chave == "SIM" and valor in ("OK", "NG"):
        return {"SIM": "presente" if valor == "OK" else "ausente"}, {}
    if chave == "REG" and valor in ("OK", "NG"):
        return {"REG": "sim" if valor == "OK" else "nao"}, {}
    if chave == "IP1":
        ip, _, porta = valor.rpartition(":")     # "200.152.062.020:13346"
        if ip and porta.isdigit():
            return {}, {"SERVIP": ip, "SERVPORT": porta}
    # o checklist de autoteste (CEXTV/GPS/CSQ/ACC/...) e OK/NG: e STATUS, nao
    # dado. Sem tratar aqui, "GPS: NG"/"CSQ: OK" caiam no laco geral e viravam
    # posicao/sinal falsos, sobrescrevendo valor bom.
    if valor in ("OK", "NG") and chave in _TESTE_CHECKLIST:
        return {_TESTE_CHECKLIST[chave]: valor}, {}
    return None


def parse_cantrack(resposta):
    """Resposta de um comando Cantrack -> (campos do monitor, chaves de config).

    Devolve dois dicionarios porque as duas metades da tela sao alimentadas por
    lugares diferentes: o painel de telemetria e a tabela de parametros.
    """
    moni, cfg = {}, {}
    txt = resposta.strip()

    # "READOK: CHAVE=valor" e a forma normal, mas SOURCE_OFF_TYPE responde so
    # "CHAVE=valor", sem o prefixo -- sem este segundo caso ele some.
    if txt.upper().startswith("READOK") or ("=" in txt and ":" not in txt):
        corpo = txt.partition(":")[2] if txt.upper().startswith("READOK") else txt
        chave, sep, valor = corpo.partition("=")
        if sep:
            # GPS_DISSLP e GPS_FINTER_EN devolvem "0,CXCS": o eco do proprio
            # comando grudado no valor, nao um segundo campo
            valor = valor.strip()
            if valor.upper().endswith(",CXCS"):
                valor = valor[:-5]
            cfg[chave.strip().upper()] = valor.strip()
        return moni, cfg

    if txt.startswith("VER:"):
        for parte in txt[4:].rstrip(";").split(","):
            chave, sep, valor = parte.partition(":")
            if sep:
                moni["_" + chave.strip().lower()] = valor.strip().rstrip(";")
        # o APP e a versao de firmware que a linha SOFTVERSION da tela descreve;
        # sem isto ela so aparecia como linha solta do log
        if moni.get("_app"):
            cfg["SOFTVERSION"] = moni["_app"]
        return moni, cfg

    if "LastPosition" in txt:
        _, _, resto = txt.partition("Lati:")
        return _cantrack_pos(resto), cfg

    if txt.startswith("CELL,"):
        _, _, resto = txt.partition("CellInfo:")
        celula = dict(p.split("=", 1) for p in resto.split(",") if "=" in p)
        if celula.get("lac"):
            moni["AreaID"] = celula["lac"]
        if celula.get("cid"):
            moni["CellID"] = celula["cid"]
        if celula.get("mcc") not in (None, "0"):
            moni["NET"] = f"mcc {celula['mcc']} / mnc {celula.get('mnc', '?')}"
        elif celula.get("mcc") == "0":
            moni["NET"] = "nao registrado"
        return moni, cfg

    if txt.upper().startswith("SERVER:"):
        # "SERVER:1,dominio,7018,0;SERVER:0,0.0.0.0,0,1;" -- os dois registros
        # vem sempre, um por dominio e um por IP, e o que nao esta em uso volta
        # zerado. Nao ha campo dizendo qual vale, entao vale o que tem endereco.
        for reg in txt.rstrip(";").split(";"):
            _, _, corpo = reg.partition(":")
            campos = [c.strip() for c in corpo.split(",")]
            if len(campos) < 3 or campos[1] in ("", "0.0.0.0") or campos[2] == "0":
                continue
            cfg["SERVIP"], cfg["SERVPORT"] = campos[1], campos[2]
        return moni, cfg

    # --- bloco do modo de teste (AT+ZDR=debug) --------------------------------
    # Medido em 15-09-2026: o firmware passa a cuspir, a cada 3 s, um bloco de
    # autoteste linha a linha. E a UNICA fonte de ICCID que este aparelho tem --
    # nem ICCID#, nem CXCS#ICCID, nem o PARAM# devolvem o numero do chip.
    tst = _teste(txt) or _pblog(txt)
    if tst is not None:
        return tst

    if txt.upper().startswith("APN:"):
        # "APN:em,," -- nome, usuario, senha; os dois ultimos quase sempre vazios
        campos = [c.strip() for c in txt.partition(":")[2].split(",")]
        campos += [""] * (3 - len(campos))
        cfg["APN"], cfg["USERPPP"], cfg["PWPPP"] = campos[:3]
        return moni, cfg

    # formato geral: "Chave:valor;Chave:valor;" -- STATUS# e PARAM#
    for parte in txt.rstrip(";").split(";"):
        chave, sep, valor = parte.partition(":")
        if not sep:
            continue
        chave, valor = chave.strip(), valor.strip()
        if chave == "CSQ":
            csq = int(valor) if valor.isdigit() else 99
            moni["CSQ"] = f"{valor} ({_qualidade(csq)})"
        elif chave == "Exvkk":
            # "0.00,0": tensao e um sinalizador. Zero aqui e alimentacao externa
            # ausente, que e a explicacao de metade dos "nao transmite".
            tensao = valor.split(",")[0]
            moni["Voltage"] = f"{tensao} V"
            moni["Power"] = "ausente" if tensao.startswith("0.0") else "presente"
        elif chave == "GPRS":
            moni["System Status"] = valor
            moni["REG"] = "sim" if valor.lower() == "online" else "nao"
        elif chave == "GPS":
            # "GPS:ON" no STATUS# e o modulo LIGADO, nao posicao valida. Chamar
            # isso de "Fix" fazia o painel dizer fix com a coordenada zerada.
            moni["Status"] = ("ligado" if valor.upper() == "ON"
                              else "desligado" if valor.upper() == "OFF"
                              else valor)
        elif chave == "Slp":
            # "Slp" e o parametro de sleep, nao o estado: veio 1 com o aparelho
            # acordado respondendo tudo. Rotular como evento seria mentira.
            moni["Sleep"] = _sn(valor not in ("0", ""), "habilitado", "desabilitado")
        elif chave == "Relay":
            moni["_rele"] = ("cortado -- bloqueio ATIVO" if valor not in ("0", "")
                             else "solto")
        elif chave == "IMEI":
            # vai para a TABELA, nao para o painel: a linha IMEI ja existe la e
            # e o unico lugar onde o tecnico procura a identidade do aparelho
            cfg["IMEI"] = valor
        elif chave in _CANTRACK_CAMPOS:
            moni[_CANTRACK_CAMPOS[chave]] = valor
        elif chave in _CANTRACK_CFG:
            # "#" no fim e terminador de comando que o firmware devolve junto
            nome = _CANTRACK_CFG[chave]
            cfg[nome] = (_tempos(valor) if nome in ("TIMER", "HBT")
                         else valor.rstrip("#"))
        else:
            moni["_" + chave.lower()] = valor
    return moni, cfg


def selftest():
    f = encode("#FREQ", MSG_READ)
    assert f.startswith(HEADER) and f.endswith(b"\r\n")
    body = bytes.fromhex(f[len(HEADER):-2].decode())
    assert body[:2] == MARKER
    assert (body[11] << 8) | body[12] == MSG_READ
    assert (body[13] << 8) | body[14] == 5
    assert body[15:20] == b"#FREQ"
    assert body[20] == sum(body[:20]) & 0xFF, "checksum"
    assert body[21:] == b"\r\n"

    assert read_frame(["FREQ", "APN"]) == encode("#FREQ#APN", MSG_READ)
    assert write_frame([("FREQ", "60")]) == encode("#FREQ=60", MSG_WRITE)

    # exactly what the device sent back for #FREQ
    reply = bytes.fromhex("5953000000000000000012820200" "0B") + \
        b"\x00\x07FREQ=15\x00\x00" + b"\x39\r\n"
    frames, rest = decode(reply)
    assert frames == [(ACK_READ, 0x12, "FREQ=15")], frames
    assert rest == b""

    # split across two reads, with leading junk
    frames, rest = decode(b"lixo" + reply[:9])
    assert frames == [] and rest.startswith(MARKER)
    frames, rest = decode(rest + reply[9:])
    assert frames == [(ACK_READ, 0x12, "FREQ=15")]

    assert parse_values("FREQ=15,APN=x.br") == {"FREQ": "15", "APN": "x.br"}
    assert parse_values("") == {}
    # a mis-sliced binary value must be dropped, the clean one kept
    assert parse_values("IMSI=A\xf9\x00Y,FREQ=15") == {"FREQ": "15"}

    # a stray 'YS' in leading junk must not be locked onto as a frame start
    frames, rest = decode(b"\x01YS\x99\x88\x77" + reply)
    assert frames == [(ACK_READ, 0x12, "FREQ=15")], frames

    # exactly what the device answered for 0x0100, byte for byte
    sysfrm = bytes.fromhex(
        "0f 01 01 00 17 01 01 00 3f 9f 1c 55 6c 10 01 00"
        "00 00 00 00 07 00 03 00 00 00 00 00 bd 45 0d 00"
        "24 00 00 00 37 32 34 39 39 30 30 30 30 30 30 30"
        "30 30 30 00 05 00 d4 02 00 00 a4 00 00 00 00 00"
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 7b 00")
    assert len(sysfrm) == 96
    m = parse_moni_sys(sysfrm)
    assert m["System Status"] == "Normal Connect", m["System Status"]
    assert m["SIM IMSI"] == "724990000000000", m["SIM IMSI"]
    assert m["Voltage"] == "12.3 V" and m["CSQ"] == "23 (otimo)", m
    assert m["NET"] == "724-05" and m["Run Time"] == "0h 0m 36s", m
    assert m["Mileage"] == "869.8 km", m["Mileage"]
    # the eight flag bytes, read the way the vendor tool reads them
    assert m["SIM"] == "presente" and m["REG"] == "registrado", m
    assert m["Defences"] == "desarmado", m["Defences"]
    assert m["ACC"] == "ligada" and m["Power"] == "conectada", m
    assert m["Sleep"] == "acordado", m["Sleep"]
    assert m["Battery"] == "4.20 V", m["Battery"]        # 0x106c mV
    assert m["PPP Times"] == 1 and m["Sms Send"] == 0, m
    assert m["Socket Send"] == 7 and m["Socket Receive"] == 3, m
    assert m["Call IN"] == 0 and m["Call Out"] == 0, m
    assert m["Band"] == "4G / LTE (codigo 164)", m["Band"]
    assert _banda(1) == "2G / GSM900" and _banda(0) == "sem leitura"
    assert m["Vibration"] == "parado", m["Vibration"]

    tranco = parse_shake("2026-09-14 19:51:53  [GSENSOR]>>>shake<<< [2,0,0]")
    assert tranco == {"Vibration": "nivel 2 as 19:51"}, tranco
    assert parse_shake("2026-09-14 19:51:53  [DEF]Update_File_type:2") == {}

    assert cantrack_escrita("SENALM", "OFF") == "SENALM,OFF#"
    assert cantrack_escrita("HBT", "180,300") == "HBT,180,300#"
    assert cantrack_escrita("RFID_ENABLE", "0") == "RFID,ENABLE,0#"
    assert cantrack_escrita("PULSE", "20") == "SZCS#PULSE=20"
    assert cantrack_escrita("APN", "x.br,u,p") == "APN,x.br,u,p#"
    assert juntar_apn([("FREQ", "20")]) == [("FREQ", "20")]
    assert juntar_apn([("APN", "x.br"), ("PWPPP", "s")],
                      {"USERPPP": "u"}) == [("APN", "x.br,u,s")]

    _m, c = parse_cantrack("TIMER ACC ON:20s,ACC OFF:3600s")
    assert c["TIMER"] == "20,3600", c
    _m, c = parse_cantrack("HBT ACC ON:180s,ACC OFF:300s")
    assert c["HBT"] == "180,300", c
    _m, c = parse_cantrack("IMEI:860000000000001;TIMER:20,3600;HBT:180;")
    # o HBT do PARAM# e parcial (so o intervalo com ignicao ligada): nao vira
    # linha da tela, senao sobrescreve o valor inteiro que o HBT# trouxe
    assert c["TIMER"] == "20,3600" and "HBT" not in c, c

    # and for 0x0101, likewise
    gpsfrm = bytes.fromhex(
        "01 00 00 0b 00 00 00 00 36 22 4e 45 14 1b 39 1e"
        "1a 09 0a 0f 09 3a 0e 05 0e 0c 15 12 1b 19 19 1c"
        "18 0b 00 0d 00 15 00 18 00 1d 00 2e 00 33 00 21"
        "00 26 00 00 1a".replace(" ", ""))
    g = parse_moni_gps(gpsfrm)
    # bytes 0,1,2 reproduce the vendor's "A/W/S" -- valid, West, South
    assert g["Status"] == "fix valido (W/S)", g["Status"]
    # bytes 16..21 matched the PC clock across three captures
    assert g["DateTime"] == "2026-09-10 15:09:58 UTC", g["DateTime"]
    # degrees and minutes as shown by the vendor: 5434.xxxx / 2027.xxxx
    assert g["Longitude"].startswith("54°34."), g["Longitude"]
    assert g["Latitude"].startswith("20°27."), g["Latitude"]
    assert "W  (-54." in g["Longitude"] and "S  (-20." in g["Latitude"], g
    # decimals for the map link: Campo Grande, MS
    assert -55 < g["_lon"] < -54 and -21 < g["_lat"] < -20, (g["_lon"], g["_lat"])

    # the same device later answered 57 bytes: the satellite table grows, so the
    # parser must not depend on a fixed offset
    gps57 = bytes.fromhex(
        "01 00 00 0e 00 00 36 01 36 22 4d 60 14 1b 38 53"
        "1a 09 0a 12 2f 2f 10 0a 0f 10 12 17 1e 19 12 1a"
        "1b 1b 15 1f 0b 0f 00 12 00 1c 00 1d 00 20 00 2e"
        "00 33 00 21 00 26 00 2d 27")
    assert len(gps57) == 57
    g2 = parse_moni_gps(gps57)
    # byte 3 = satelites usados na posicao; a tabela lista tambem os so vistos
    assert g2["Satellite"] == 16 and g["Satellite"] == 14, (g, g2)
    # o layout so fecha se estiver certo: 23 + 2*n + 2 == tamanho do quadro
    assert 23 + 2 * g2["Satellite"] + 2 == 57
    assert 23 + 2 * g["Satellite"] + 2 == 53
    # velocidade, proa e HDOP: o aparelho estava parado nas duas capturas
    assert g["Velocidade"] == "0 km/h" and g2["Velocidade"] == "0 km/h", (g, g2)
    assert g["Proa"] == "0\u00b0" and g2["Proa"] == "310\u00b0", (g, g2)
    assert g["HDOP"] == "1.1" and g2["HDOP"] == "1.4", (g["HDOP"], g2["HDOP"])
    assert g["Collect Times"] == 26 and g2["Collect Times"] == 0x2D27
    assert g2["DateTime"] == "2026-09-10 18:47:47 UTC", g2["DateTime"]
    assert g2["Collect Times"] == 0x2D27, g2["Collect Times"]
    # same spot as the earlier frame -- a parked tracker must not move. This
    # is the check that catches the minute fraction being read little-endian:
    # that way round these two frames sit ~200 m apart.
    assert g2["Longitude"].startswith("54°34."), g2["Longitude"]
    assert g2["Latitude"].startswith("20°27."), g2["Latitude"]
    assert abs(g2["_lat"] - g["_lat"]) * 111320 < 10, (g["_lat"], g2["_lat"])
    assert abs(g2["_lon"] - g["_lon"]) * 104000 < 20, (g["_lon"], g2["_lon"])
    # the giveaway that the fraction is decimal, not a 16-bit binary count
    assert max(gpsfrm[10], gpsfrm[11], gpsfrm[14], gpsfrm[15]) <= 99
    assert g["Latitude"].startswith("20°27.5730"), g["Latitude"]
    assert g["Longitude"].startswith("54°34.7869"), g["Longitude"]
    assert g2["com sinal"] == 7, g2["sats"]
    assert g2["sats"].startswith("10:15 16:18 23:30"), g2["sats"]
    assert g["com sinal"] == 5 and g["sats"].startswith("5:14 12:21"), g["sats"]


    # J16 Plus responde 49 bytes: mesmo layout, so com menos satelites. O
    # parser exigia 53 e descartava; agora aceita a partir de 23.
    gps49 = bytes.fromhex(
        "01 00 00 08 00 00 00 00 36 22 4e 05 14 1b 38 57"
        "1a 09 0b 15 0a 04 0c 02 1f 03 00 08 1e 0a 00 10"
        "1b 12 0c 17 00 1a 0a 1b 16 1c 10 1f 0d 20 1f 08"
        "1f")
    assert len(gps49) == 49
    gp = parse_moni_gps(gps49)
    assert gp["Satellite"] == 12, gp
    assert 23 + 2 * gp["Satellite"] + 2 == 49
    assert gp["HDOP"] == "0.8", gp["HDOP"]
    assert gp["Velocidade"] == "0 km/h" and gp["Proa"] == "0°", gp
    assert gp["Longitude"].startswith("54°34.780"), gp["Longitude"]
    assert gp["Latitude"].startswith("20°27.568"), gp["Latitude"]

    # NMEA da porta irma: velocidade, proa e HDOP
    rmc = parse_nmea("$GPRMC,152526.00,A,2027.5702,S,05434.7797,W,"
                     "22.4,73.2,110926,,,A*6A")
    assert rmc["Velocidade"] == "41.5 km/h", rmc
    assert rmc["Proa"] == "73\u00b0", rmc
    # parado o receptor manda rumo vazio: tem de virar "--", nunca sumir -- se
    # a chave some, a tela segue exibindo o rumo antigo como se fosse de agora
    parado = parse_nmea("$GPRMC,123519,A,4807.038,N,01131.000,E,0.0,,230394,,,A")
    assert parado["Proa"] == "--" and parado["Velocidade"] == "0.0 km/h", parado
    gga = parse_nmea("$GPGGA,152526.00,2027.5702,S,05434.7797,W,1,15,0.9,"
                     "530.4,M,,M,,*5A")
    assert gga["HDOP"] == "0.9" and gga["Satellite"] == "15", gga
    # sem fix nao inventa numero
    assert parse_nmea("$GPRMC,152526.00,V,,,,,,,110926,,,N*53") == {}
    assert parse_nmea("$GPGGA,152526.00,,,,,0,00,,,M,,M,,*66") == {}
    assert parse_nmea("$GPGSV,4,1,15,05,14,123,21*7A") == {}
    assert parse_nmea("qualquer coisa") == {}

    # a linha de texto de posicao: velocidade, proa e HDOP vem por aqui
    exemplo = ("SecDis:4,logi:113.880413,lati:22.571707,course:73,spd:0,"
               "precision:12")
    g3 = parse_texto_gps(exemplo)
    assert g3["Velocidade"] == "0" and g3["Proa"] == "73", g3
    assert g3["HDOP"] == "12" and g3["Distancia no intervalo"] == "4", g3
    assert abs(g3["_lon"] - 113.880413) < 1e-6, g3
    assert abs(g3["_lat"] - 22.571707) < 1e-6, g3
    assert parse_texto_gps("ATYS5953") == {}
    assert parse_texto_gps("") == {}

    # collision alarm: the only accelerometer event this firmware exposes
    assert parse_colisao(bytes([1, 30, 3])) == {
        "Colisao": "vetor (soma dos 3 eixos)", "Limiar": 30, "Deteccoes": 3}
    assert parse_colisao(bytes([0, 0, 0]))["Colisao"] == "desligado"
    assert parse_colisao(bytes([9])) == {}
    quadro = encode_colisao(2, 30, 3, seq=7)
    corpo = bytes.fromhex(quadro[4:-2].decode())
    assert list(corpo[11:15]) == [0x03, 0x85, 0x00, 0x04], corpo.hex()
    assert list(corpo[15:19]) == [2, 30, 3, 0], corpo.hex()
    assert MSG_COLISAO_GET not in MSG_PERIGOSO and 0x0340 in MSG_PERIGOSO
    # os eventos bruscos existem, mas do lado da plataforma
    assert ALARMES_GT06[0x29] == "aceleracao brusca"
    assert ALARMES_GT06[0x30].startswith("desaceleracao") and ALARMES_GT06[0x4C]
    # 0x19 e o unico alarme da tabela que nao veio do protocolo publicado, e sim
    # da captura: se sumir num merge, volta a aparecer como codigo cru na tela
    assert ALARMES_GT06[0x19] == "bateria interna fraca"

    # o que o decode pula tem de sair pelo descarte, senao texto intercalado
    # com quadro binario some sem ninguem ver
    quadro = encode("#FREQ", MSG_READ, 1)
    fatia = bytes.fromhex(quadro[4:-2].decode())
    lixo = bytearray()
    frames, resto = decode(b"spd:41,course:73\r\n" + fatia, lixo)
    assert len(frames) == 1 and frames[0][2] == b"#FREQ", frames
    assert b"spd:41,course:73" in bytes(lixo), bytes(lixo)
    # sem o parametro, o comportamento antigo continua igual
    frames2, _ = decode(b"spd:41\r\n" + fatia)
    assert len(frames2) == 1 and frames2[0][2] == b"#FREQ"

    # an unsupported opcode must survive the decoder, not desync it
    frames, _ = decode(bytes.fromhex("59530000000000000000f8f00200020203") +
                       b"\x9d\r\n")
    assert frames and frames[0][0] == ACK_UNSUPPORTED, frames

    # exactly the ack the device sent right before it rebooted
    frames, _ = decode(bytes.fromhex("595300000000000000000bf00000020300") +
                       b"\xac\r\n")
    assert frames and frames[0][0] == ACK_OK0, frames
    assert encode(b"", MSG_RESET, 0x0b).startswith(HEADER)
    assert 0x0301 in MSG_PERIGOSO and MSG_RESET not in MSG_PERIGOSO
    # Cantrack G900L: respostas reais capturadas do aparelho em 14-09-2026.
    moni, cfg = parse_cantrack(
        "Battery:3.93V;Exvkk:0.00,0;GPRS:Offline;CSQ:99;ACC:OFF;GPS:ON;"
        "Gid:11;Relay:0;Slp:1;")
    assert moni["Battery"] == "3.93V" and moni["ACC"] == "OFF"
    assert moni["CSQ"] == "99 (sem leitura)"
    assert moni["Voltage"] == "0.00 V" and moni["Power"] == "ausente"
    assert moni["System Status"] == "Offline" and moni["REG"] == "nao"
    assert moni["_rele"] == "solto" and moni["Sleep"] == "habilitado"
    # bloco do modo de teste
    _, c = parse_cantrack("ICCID:89550000000000000000")
    assert c == {"ICCID": "89550000000000000000"}, c
    m, _ = parse_cantrack("EVKK:    12123mV")
    assert m == {"Voltage": "12.12 V", "Power": "presente"}, m
    m, _ = parse_cantrack("VBAT:    4254mV")
    assert m == {"Battery": "4.25 V"}, m
    m, _ = parse_cantrack("SATVAL:    19")
    assert m == {"Satellite": "19"}, m
    _, c = parse_cantrack("IP1:200.152.062.020:13346")
    assert c == {"SERVIP": "200.152.062.020", "SERVPORT": "13346"}, c
    m, _ = parse_cantrack("REG:    NG")
    assert m == {"REG": "nao"}, m
    # checklist do autoteste vira status, nao dado -- nao sobrescreve campo bom
    assert parse_cantrack("GPS:    NG") == ({"_teste_gps": "NG"}, {}), \
        parse_cantrack("GPS:    NG")
    assert parse_cantrack("LOGIN:    NG") == ({"_teste_login": "NG"}, {})
    # DIF (impacto cru) e MIL (odometro) saem do log de diagnostico
    _mo, _cf = parse_cantrack("-->GSENSOR:1,0,STA:1;THR:55,45,QS:300;DIF:16,14;MOV:2")
    assert _mo.get("Impacto") == "16,14", _mo
    _mo, _cf = parse_cantrack("-->PARSE:OT:28; MIL:0,202; ST:9,6153")
    assert _cf.get("MIL") == "0,202", _cf
    assert m == {"REG": "nao"}, m
    # log de diagnostico (<ZDRCMD*LOG:1>)
    _, c = parse_cantrack("-->ICCID:89550000000000000000; IMEI:860000000000002;"
                          "IMSI:724990000000001; SIM:OK,0; SN:860000000000002")
    assert c["IMSI"] == "724990000000001" and c["ICCID"].startswith("8955"), c
    m, _ = parse_cantrack("-->LOWP:1; VKK:12123,BAT:4276,100%; ES:0,0,0,0")
    assert m["Voltage"] == "12.12 V" and m["Battery"] == "4.28 V", m
    _, c = parse_cantrack("-->[0]DNS:200.152.062.020:13346; HS:52,HM:0;CM:0;"
                          " HT:180,300; RE:8000,0;")
    assert c["SERVPORT"] == "13346" and c["HBT"] == "180,300", c
    m, _ = parse_cantrack("-->CURNET:LTE,Online;NWM:0")
    assert m["REG"] == "sim" and m["NET"] == "LTE", m
    assert cfg == {}
    _, cfg = parse_cantrack("READOK: SLPDISCONNECT=0")
    assert cfg == {"SLPDISCONNECT": "0"}
    moni, _ = parse_cantrack(
        "VER:SDK:A7670M6_SDK_1.011.131,APP:BXBZ16S131V1.01.05_260505_14:36:41;")
    assert moni["_sdk"] == "A7670M6_SDK_1.011.131"
    assert moni["_app"].startswith("BXBZ16S131V1.01.05")
    moni, _ = parse_cantrack(
        "LastPosition! Lati:N0.000000,E0.000000,Course:0,Speed:0.00,"
        "DateTime:2026-09-14 14:43:01")
    assert "Latitude" not in moni and "Longitude" not in moni,         "0,0 nao e posicao -- a linha fica em '--' em vez de mentir"
    assert "_lat" not in moni, "0,0 nao e fix -- nao pode acender o botao do mapa"
    fixo, _ = parse_cantrack(
        "LastPosition! Lati:S20.460865,W54.577084,Course:0,Speed:0.00,"
        "DateTime:2026-09-14 15:07:49")
    assert round(fixo["_lat"], 6) == -20.460865
    assert round(fixo["_lon"], 6) == -54.577084
    # parado o rumo e indefinido, nao norte -- vale para o G900L como para o RMC
    assert moni["Velocidade"] == "0.00 km/h" and moni["Proa"] == "--"
    andando, _ = parse_cantrack(
        "LastPosition! Lati:S20.460865,W54.577084,Course:73,Speed:41.20,"
        "DateTime:2026-09-14 15:07:49")
    assert andando["Proa"] == "73°", andando
    moni, _ = parse_cantrack("CELL,CellInfo:mcc=0,mnc=0,lac=0,cid=0")
    assert moni["NET"] == "nao registrado"
    moni, _cfg2 = parse_cantrack("IMEI:860000000000001;TIMER:20,3600;HBT:180;")
    _cfg = _cfg2
    assert _cfg["IMEI"] == "860000000000001", _cfg
    _, _cfg = parse_cantrack(
        "VER:SDK:A7670M6_SDK_1.011.131,APP:BXBZ16S131V1.01.05_260505_14:36:41;")
    assert _cfg["SOFTVERSION"].startswith("BXBZ16S131"), _cfg
    # as respostas de texto do dialeto SMS tambem viram linha da tabela
    _, _cfg = parse_cantrack("TIMER ACC ON:20s,ACC OFF:3600s")
    assert _cfg["TIMER"] == "20,3600", _cfg        # so os numeros: a linha volta
    _, _cfg = parse_cantrack("RFID,ENABLE:0#")
    assert _cfg["RFID_ENABLE"] == "0", _cfg
    _, _cfg = parse_cantrack("READOK: GPS_DISSLP=0,CXCS")
    assert _cfg["GPS_DISSLP"] == "0", _cfg          # eco grudado no valor
    _, _cfg = parse_cantrack("SOURCE_OFF_TYPE=0")
    assert _cfg["SOURCE_OFF_TYPE"] == "0", _cfg     # resposta sem READOK
    _moni, _ = parse_cantrack("Cur Mileage Value: 0KM")
    assert _moni["Mileage"] == "0KM", _moni
    _, _cfg = parse_cantrack("POWERALM:ON,0,5,5")
    assert _cfg["POWERALM"] == "ON,0,5,5", _cfg
    assert _cfg2["TIMER"] == "20,3600"

    print("j16proto selftest ok")


if __name__ == "__main__":
    selftest()
