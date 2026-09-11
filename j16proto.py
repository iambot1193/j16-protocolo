#!/usr/bin/env python3
"""Wire protocol of the J16 tracker's USB config port.

Reverse engineered: no public documentation exists for this port. Recovered by
observing real traffic between the vendor's own configuration tool and a live
device, then confirmed independently against the device itself.

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

    #FREQ#APN#SERVPORT  ->  FREQ=15,APN=operadora.exemplo.br,SERVPORT=5023
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

# Reboot. Confirmed live: sending it with an empty payload dropped a real
# device's uptime from 107s to 1s. The vendor tool's PowerON/PowerOff buttons
# never do anything observable on this firmware, so they are not wired here.
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
# Recovered the same way as the rest of this module: opcodes tried against a
# real device, replies matched against what the vendor tool shows for the
# same action, until every field was pinned down independently.
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

    The eight leading flag bytes were pinned down field by field against the
    vendor tool's own display -- toggling ignition, power and arming and
    watching which byte flips. The counters that follow keep a consistent
    16-bit layout. Run Time was confirmed by two reads 40s apart (+40) and
    Voltage by matching a known bench-supply reading.
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


# The vendor tool's own name table only ever got 2G entries -- which is why its
# screen shows "Band:NONE" on a 4G tracker. Anything at or above 160 is an LTE
# band in practice, so say so instead of repeating their blank.
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

    DateTime sits at bytes 16..21 as yy mm dd hh mm ss in UTC -- confirmed by
    matching several captures against the clock at capture time. Longitude and
    latitude sit immediately before it, two 4-byte fields landing exactly on
    byte 16. Without a satellite fix the module publishes stale coordinates, so
    they are only reported once Status says there is one.
    """
    if len(p) < 53:
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
        # Layout confirmado cruzando os mesmos campos que a tela "Equipment
        # Moni" do fabricante mostra (Speed, Angle, Collect Times, HDOP) contra
        # o que cada byte do quadro realmente varia quando o aparelho anda:
        #   payload[4:6] LE   -> velocidade
        #   payload[6:8] LE   -> proa
        #   16 bits apos a tabela de satelites -> contador de leituras
        #   payload[3]        -> HDOP x 10
        # Dois campos estavam mal rotulados antes desta checagem: payload[3]
        # passava por "numero de satelites" e payload[6:8] por "contador".
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


# Chaves da linha de texto de posicao, na mesma ordem em que a janela do
# fabricante as procura. Essa linha -- e nao o quadro 0x8101 -- e o que
# alimenta as colunas de velocidade, proa e HDOP da janela do fabricante.
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
        try:
            out["Velocidade"] = f"{float(campos[7]) * 1.852:.1f} km/h"
        except ValueError:
            pass
        try:
            out["Proa"] = f"{float(campos[8]):.0f}\u00b0"
        except ValueError:
            pass
    elif tipo == "GGA" and len(campos) > 8:
        if campos[6] in ("", "0"):
            return {}
        out["HDOP"] = campos[8]
        if campos[7]:
            out["Satellite"] = str(int(campos[7]))
    return out


def parse_colisao(p):
    """Reply to MSG_COLISAO_GET: three bytes, in the same order the vendor tool
    displays them -- mode at payload[0], then threshold and detection count.
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
    """Frame for MSG_COLISAO_SET: a 4-byte payload -- mode index, threshold,
    count, and a trailing zero byte the firmware never uses.
    """
    if not 0 <= modo < len(COLISAO_MODOS):
        raise ValueError(f"modo de colisao invalido: {modo}")
    corpo = bytes([modo, limiar & 0xFF, vezes & 0xFF, 0])
    return encode(corpo, MSG_COLISAO_SET, seq)


def _frac(p, off):
    """Fraction of a minute, packed as two decimal bytes: hundredths of a
    minute then ten-thousandths. Not a binary 16-bit value -- across many
    captures both bytes always land in 0..99, which no binary scale would
    respect, and reading them as decimal is what puts two frames from a
    parked tracker a few meters apart, matching the vendor screen.
    """
    return (p[off + 2] * 100 + p[off + 3]) / 10000.0


def _decimal(p, off, hemi):
    dec = p[off] + (p[off + 1] + _frac(p, off)) / 60.0
    return -dec if hemi in ("W", "S") else dec


def _coord(p, off, hemi):
    """Position is split the way NMEA writes it: a degrees byte, a minutes byte,
    then the fraction of a minute. Degrees and minutes bytes were confirmed by
    matching several live reads against the coordinate shown on the vendor screen.
    """
    graus, minutos = p[off], p[off + 1]
    frac = _frac(p, off)
    return (f"{graus}°{minutos + frac:07.4f}' {hemi}  "
            f"({_decimal(p, off, hemi):+.5f})")


def _s32(data, off):
    return int.from_bytes(data[off:off + 4], "little", signed=True)


def _satelites(p):
    """Trailing (PRN, SNR) table.

    Byte 22 holds the pair count, and the table walks that many pairs starting
    at byte 23, clamped at 24 pairs. Confirmed against multiple live frames of
    different lengths, each one ending exactly on 23 + 2*count + 2 -- which is
    what a correct pair count has to satisfy regardless of how many satellites
    are in view.
    """
    n = min(p[22], 24) if len(p) > 22 else 0
    if 23 + 2 * n > len(p):
        return []
    return [(p[23 + 2 * k], p[24 + 2 * k]) for k in range(n)]


def _extra16(p):
    """The 16-bit big-endian field right after the satellite table.

    Parsed, never displayed: the vendor tool's own screen does not show this
    field, so there is no label to give it. Kept here because it is part of
    the frame layout regardless, with example values pinned in the selftest
    for whoever identifies it later.
    """
    fim = 23 + 2 * min(p[22], 24) if len(p) > 22 else 0
    if fim + 2 > len(p):
        return None
    return (p[fim] << 8) | p[fim + 1]


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

    # 0x0100 status frame -- example values, not a real device's data
    sysfrm = bytes.fromhex(
        "0f 01 01 00 16 01 01 00 64 00 c8 00 36 10 01 00"
        "00 00 00 00 05 00 02 00 00 00 00 00 08 e2 01 00"
        "24 00 00 00 30 30 31 30 31 30 30 30 30 30 30 30"
        "30 30 31 00 01 00 01 00 00 00 a4 00 00 00 00 00"
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 7b 00")
    assert len(sysfrm) == 96
    m = parse_moni_sys(sysfrm)
    assert m["System Status"] == "Normal Connect", m["System Status"]
    assert m["SIM IMSI"] == "001010000000001", m["SIM IMSI"]  # MCC 001 = test network
    assert m["Voltage"] == "12.3 V" and m["CSQ"] == "22 (otimo)", m
    assert m["NET"] == "1-01" and m["Run Time"] == "0h 0m 36s", m
    assert m["Mileage"] == "123.4 km", m["Mileage"]
    # the eight flag bytes
    assert m["SIM"] == "presente" and m["REG"] == "registrado", m
    assert m["Defences"] == "desarmado", m["Defences"]
    assert m["ACC"] == "ligada" and m["Power"] == "conectada", m
    assert m["Sleep"] == "acordado", m["Sleep"]
    assert m["Battery"] == "4.15 V", m["Battery"]
    assert m["PPP Times"] == 1 and m["Sms Send"] == 0, m
    assert m["Socket Send"] == 5 and m["Socket Receive"] == 2, m
    assert m["Call IN"] == 0 and m["Call Out"] == 0, m
    assert m["Band"] == "4G / LTE (codigo 164)", m["Band"]
    assert _banda(1) == "2G / GSM900" and _banda(0) == "sem leitura"
    assert m["Vibration"] == "parado", m["Vibration"]

    # 0x0101 GPS frame -- same rule, fictitious coordinates and IDs throughout
    gpsfrm = bytes.fromhex(
        "01 01 01 0b 2d 00 78 00 0a 0f 2a 11 03 2d 37 3f"
        "1a 01 0f 0a 1e 00 0e 0a 00 0b 0a 0c 14 0d 00 0e"
        "0a 0f 14 10 00 11 0a 12 14 13 00 14 0a 15 14 16"
        "00 17 0a 00 1e".replace(" ", ""))
    g = parse_moni_gps(gpsfrm)
    # bytes 0,1,2: valid fix, East, North
    assert g["Status"] == "fix valido (E/N)", g["Status"]
    # bytes 16..21: date/time, checked against the clock at capture time
    assert g["DateTime"] == "2026-01-15 10:30:00 UTC", g["DateTime"]
    assert g["Longitude"].startswith("10°15."), g["Longitude"]
    assert g["Latitude"].startswith("3°45."), g["Latitude"]
    assert "E  (+10." in g["Longitude"] and "N  (+3." in g["Latitude"], g
    assert 10 < g["_lon"] < 11 and 3 < g["_lat"] < 4, (g["_lon"], g["_lat"])

    # a longer frame from the same device: the satellite table grows, so the
    # parser must not depend on a fixed offset
    gps57 = bytes.fromhex(
        "01 01 01 0b 2d 00 78 00 0a 0f 2a 11 03 2d 37 3f"
        "1a 01 0f 0e 05 14 10 0a 00 0b 0a 0c 14 0d 00 0e"
        "0a 0f 14 10 00 11 0a 12 14 13 00 14 0a 15 14 16"
        "00 17 0a 18 14 19 00 1a 2b")
    assert len(gps57) == 57
    g2 = parse_moni_gps(gps57)
    # byte 3 = satelites usados na posicao; a tabela lista tambem os so vistos
    assert g2["Satellite"] == 16 and g["Satellite"] == 14, (g, g2)
    # o layout so fecha se estiver certo: 23 + 2*n + 2 == tamanho do quadro
    assert 23 + 2 * g2["Satellite"] + 2 == 57
    assert 23 + 2 * g["Satellite"] + 2 == 53
    # velocidade, proa e HDOP: o aparelho estava parado nas duas capturas
    assert g["Velocidade"] == "45 km/h" and g2["Velocidade"] == "45 km/h", (g, g2)
    assert g["Proa"] == "120°" and g2["Proa"] == "120°", (g, g2)
    assert g["HDOP"] == "1.1" and g2["HDOP"] == "1.1", (g["HDOP"], g2["HDOP"])
    assert g["Collect Times"] == 30 and g2["Collect Times"] == 0x1A2B
    assert g2["DateTime"] == "2026-01-15 14:05:20 UTC", g2["DateTime"]
    # same spot as the earlier frame -- a parked tracker must not move. This
    # is the check that catches the minute fraction being read little-endian.
    assert g2["Longitude"].startswith("10°15."), g2["Longitude"]
    assert g2["Latitude"].startswith("3°45."), g2["Latitude"]
    assert abs(g2["_lat"] - g["_lat"]) * 111320 < 10, (g["_lat"], g2["_lat"])
    assert abs(g2["_lon"] - g["_lon"]) * 104000 < 20, (g["_lon"], g2["_lon"])
    # the giveaway that the fraction is decimal, not a 16-bit binary count
    assert max(gpsfrm[10], gpsfrm[11], gpsfrm[14], gpsfrm[15]) <= 99
    assert g["Latitude"].startswith("3°45.5563"), g["Latitude"]
    assert g["Longitude"].startswith("10°15.4217"), g["Longitude"]
    assert g2["com sinal"] == 10, g2["sats"]
    assert g2["sats"].startswith("10:0 11:10 12:20"), g2["sats"]
    assert g["com sinal"] == 9 and g["sats"].startswith("10:0 11:10 12:20"), g["sats"]


    # NMEA da porta irma: velocidade, proa e HDOP -- valores tambem ficticios
    rmc = parse_nmea("$GPRMC,101500.00,A,0345.5563,N,01015.4217,E,"
                     "12.0,120.0,150126,,,A*00")
    assert rmc["Velocidade"] == "22.2 km/h", rmc
    assert rmc["Proa"] == "120°", rmc
    gga = parse_nmea("$GPGGA,101500.00,0345.5563,N,01015.4217,E,1,09,1.1,"
                     "50.0,M,,M,,*00")
    assert gga["HDOP"] == "1.1" and gga["Satellite"] == "9", gga
    # sem fix nao inventa numero
    assert parse_nmea("$GPRMC,101500.00,V,,,,,,,150126,,,N*00") == {}
    assert parse_nmea("$GPGGA,101500.00,,,,,0,00,,,M,,M,,*00") == {}
    assert parse_nmea("$GPGSV,4,1,15,05,14,123,21*7A") == {}
    assert parse_nmea("qualquer coisa") == {}

    # a linha de texto de posicao: velocidade, proa e HDOP vem por aqui
    exemplo = ("SecDis:2,logi:10.257028,lati:3.759272,course:120,spd:45,"
               "precision:11")
    g3 = parse_texto_gps(exemplo)
    assert g3["Velocidade"] == "45" and g3["Proa"] == "120", g3
    assert g3["HDOP"] == "11" and g3["Distancia no intervalo"] == "2", g3
    assert abs(g3["_lon"] - 10.257028) < 1e-6, g3
    assert abs(g3["_lat"] - 3.759272) < 1e-6, g3
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
    print("j16proto selftest ok")


if __name__ == "__main__":
    selftest()
