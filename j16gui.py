#!/usr/bin/env python3
"""J16 tracker configurator: parameter table, import/export, free-command console.

Alternative to the vendor's own configuration tool, for a USB config protocol
that has no public documentation. Command names come from the vendor tool;
the wire format lives in j16proto and was reverse engineered from real device
traffic, then verified independently against a real device.

    python j16gui.py
    python j16gui.py --selftest
"""
import argparse, configparser, datetime, os, queue, sys, threading, time
import webbrowser
from types import SimpleNamespace

import ajuda
import j16proto as proto
import tema

VERSAO = "1.3"
AUTOR = "Felipe Gonçalves Lopes"
FEITO_EM = "setembro de 2026"
ASSINATURA = f"{AUTOR}  \u00b7  {FEITO_EM}"

# Command names come from the vendor's own configuration tool; the descriptions
# come from field notes gathered configuring real devices. Grouped for the UI
# only -- the firmware does not care about the grouping.
#
# Every name here was read back from a real device, except the RFID group --
# that comes from the vendor's own command sheet for the Plus variant, and the
# plain J16 on hand has no reader, so it answers nothing for them.
# DNS_ENABLE and TIMING_RESET answered nothing on read but field notes set them
# explicitly, so they are kept as write-only (greyed, see NAO_CONFIRMADOS).
COMMANDS = {
    "Servidor e APN": [
        ("SERVIP", "endereco IP do servidor"),
        ("SERVPORT", "porta do servidor"),
        ("DNS_ENABLE", "habilita DNS: 0 nao, 1 sim"),
        ("SERV2_ADDR", "endereço DNS (servidor 2) -- não usar"),
        ("SERV2_PORT", "porta DNS (servidor 2) -- não usar"),
        ("APN", "APN do chip"),
        ("USERPPP", "usuario do APN"),
        ("PWPPP", "senha do APN"),
        ("NETSELECT", "rede: 0 automatico, 1 so 4G, 2 so 2G"),
    ],
    "Rastreamento": [
        ("FREQ", "intervalo com ignicao ligada (s)"),
        ("ACC_OFF_FREQ", "intervalo com ignicao desligada (s)"),
        ("PULSE", "heartbeat (s)"),
        ("ANGLE_SEND", "enviar por curva: 0 nao, 1 sim"),
        ("ANGLEVALUE", "curva: intervalo-angulo, ex 02-015"),
        ("SPEED", "limite de velocidade (km/h)"),
        ("GPS_FINTER_EN", "filtro / otimização de deriva do GPS"),
        ("BLIND_EN", "guardar log sem sinal: 0 nao, 1 sim"),
        ("GMT_SET", "fuso horário: sinal + HH + MM, ex E0000"),
        ("TIMING_RESET", "reset automatico as 00h: 0 nao, 1 sim"),
        ("POS_STYLE", "formato da posicao"),
        ("RADIUS", "raio"),
        ("DIS_COEFFI", "coeficiente de distancia"),
        ("TRACE", "rastreio continuo"),
    ],
    "Ignicao e bloqueio": [
        ("ACCLINE", "ignição: 0 virtual, 1 física (fio laranja), 17 acelerômetro"),
        ("ACCLOCK", "trava por ignicao: 0 nao, 1 sim"),
        ("ACCLT", "tempo da trava por ignicao (s)"),
        ("SOURCE_OFF_TYPE", "bloqueio: 0 condicionado, 1 imediato"),
        ("OUT", "saida"),
        ("OUTS", "saida"),
        ("POF", "alerta de ignicao por SMS"),
        ("POFS", "alerta de ignicao por SMS"),
        ("POFT", "tempo do alerta de ignicao"),
        ("LED_CTRL", "controle do LED"),
        ("LED_ENABLE", "habilita LED"),
    ],
    "Economia (sleep)": [
        ("SLEEPT", "tempo para dormir (min)"),
        ("SLPDISCONNECT", "sleep: 0 nunca, 1 só portal, 2 portal e SMS"),
        ("MTK_DISSLP", "rastreador desligado EM sleep: 0 não"),
        ("GPS_DISSLP", "GPS desligado EM sleep: 0 não"),
        ("SLEEP", "modo de sono"),
        ("WAKEUP", "acordar"),
        ("WAKEUPT", "tempo para acordar"),
        ("BATT_TYPE", "tipo de bateria"),
        ("LBV", "tensao de bateria baixa"),
        ("STOPT", "tempo de parada"),
    ],
    "Vibracao": [
        ("VIBL", "sensibilidade do sensor"),
        ("VIBCHK", "tempo x movimento para checagem, ex 10:3"),
        ("VIB", "alerta de vibracao por SMS: 0 nao"),
        ("VIBCALL", "alerta de vibracao por ligacao: 0 nao"),
        ("VIBS", "vibracao"),
        ("VIBT", "tempo de vibracao"),
        ("VIBGPS", "vibracao aciona GPS"),
        ("VIB_BASE", "base do sensor"),
        ("VIBSMS_EN", "habilita SMS de vibracao"),
    ],
    "Alarmes SMS": [
        ("SOS_SMS_EN", "alertas por SMS: 0 nao"),
        ("SOS_CALL_EN", "alertas por ligacao: 0 nao"),
        ("ACC_SMS_EN", "SMS ao ligar/desligar ignicao: 0 nao"),
        ("ACC_CALL_EN", "ligacao ao ligar/desligar ignicao: 0 nao"),
        ("SPDSMSEN", "SMS de excesso de velocidade: 0 nao"),
        ("POFSMS_EN", "SMS de energia cortada"),
        ("OUTSMS_EN", "SMS de saida"),
        ("SOS_CODE2", "numero SOS 2"),
        ("SOS_CODE3", "numero SOS 3"),
        ("WARN_TIMES", "repeticoes do alerta"),
    ],
    "Protocolo": [
        ("PTL_SEL", "protocolo: 0 TQ, 1 JT808, 2 GT06"),
        ("808SEL", "variante JT808: 0 = 2011, 1 = 2013"),
        ("SKY_LINE_FLAG", "track padrao: 0"),
        ("GT06ICCID", "envia ICCID: 1 sim"),
        ("GT06METER", "habilita odometro: 1 sim"),
        ("GT06IEXVOL", "envia tensao/odometro: 1 sim"),
    ],
    "RFID / iButton (so J16 Plus)": [
        ("RFIDENABLE", "habilita leitura de tag: 1 sim"),
        ("RFIDRECEN", "envia leitura da tag pra plataforma (0x17): 1 sim"),
        ("RFIDNOACCT", "segundos apos ACC off para encerrar a conducao"),
        ("RFIDSFDELAY", "segundos ate armar o modo de defesa"),
    ],
    # Found by comparing the vendor tool's own command list against this
    # table, then reading each one back from the device -- these four answered.
    "Audio / escuta": [
        ("VOICE_CTRL_EN", "escuta por voz: 0 desligado, 1 ligado"),
        ("VOICE_DB_VALUE", "limiar de ruido em dB, ex 80"),
        ("VOICE_DB_TIME", "segundos acima do limiar para disparar"),
        ("VOICE_REDO_DELAY", "espera antes de disparar de novo (s)"),
    ],
    # Hardware/SIM telemetry -- not configuration. Read-only, no checkbox, and
    # every file operation (importar/exportar/copiar/enviar) skips these.
    "Informacoes do dispositivo": [
        ("IMEI", "IMEI do aparelho"),
        ("ICCID", "ICCID do chip"),
        ("IMSI", "IMSI do chip"),
        ("TERIID", "ID do terminal"),
        ("SOFTVERSION", "versao do firmware"),
        ("EQUTYPE", "tipo de equipamento"),
    ],
    "Acesso e diversos": [
        ("USER", "usuario"),
        ("PSW", "senha"),
        ("PHONE", "telefone"),
        ("NET_MODE", "modo de rede"),
        ("WORK_MODE", "modo de trabalho"),
        ("LOG_EN", "habilita log"),
        ("SYNC_DT", "sincroniza data/hora"),
    ],
}
ALL_COMMANDS = [c for group in COMMANDS.values() for c, _ in group]
GRUPO_DE = {c: g for g, cmds in COMMANDS.items() for c, _ in cmds}
GRUPO_INFO = "Informacoes do dispositivo"     # identity rows: never written

# One plain line per group, so the tech knows what the block is for before
# reading 12 field names.
GRUPO_AJUDA = {
    "Servidor e APN": "para onde o rastreador manda os dados e por qual chip",
    "Rastreamento": "de quanto em quanto tempo posiciona, e o que dispara um envio",
    "Ignicao e bloqueio": "fio laranja, saida de bloqueio e avisos de ignicao",
    "Economia (sleep)": "quando dorme e o que continua ligado dormindo",
    "Vibracao": "sensor de movimento: sensibilidade e o que ele dispara",
    "Alarmes SMS": "quais eventos viram SMS ou ligacao",
    "Protocolo": "formato dos pacotes enviados pra plataforma",
    "RFID / iButton (so J16 Plus)": "leitor de tag -- o J16 simples nao responde",
    "Audio / escuta": "microfone: limiar de ruido e disparo",
    "Informacoes do dispositivo": "identificacao -- so leitura, nunca e gravado",
    "Acesso e diversos": "senha, telefone e ajustes soltos",
}

# How each parameter should be shown. A tech should not have to remember that
# BLIND_EN=1 means "on" -- the wire value stays 0/1, only the widget changes.
LIGA_DESLIGA = {
    "DNS_ENABLE", "ANGLE_SEND", "GPS_FINTER_EN", "BLIND_EN", "TIMING_RESET",
    "ACCLOCK", "LED_ENABLE", "LED_CTRL", "MTK_DISSLP", "GPS_DISSLP", "TRACE",
    "VIB", "VIBCALL", "VIBS", "VIBSMS_EN", "VIBGPS", "POF", "POFS",
    "POFSMS_EN", "OUTSMS_EN", "SOS_SMS_EN", "SOS_CALL_EN", "ACC_SMS_EN",
    "ACC_CALL_EN", "SPDSMSEN", "GT06ICCID", "GT06METER", "GT06IEXVOL",
    "RFIDENABLE", "RFIDRECEN", "VOICE_CTRL_EN", "LOG_EN", "SYNC_DT",
    "SKY_LINE_FLAG", "OUT", "OUTS",
}

# Parameters that take one of a few known values: show the meaning, send the code.
ESCOLHAS = {
    "NETSELECT": [("0", "automatico (2G + 4G)"), ("1", "so 4G"), ("2", "so 2G")],
    "SLPDISCONNECT": [("0", "nunca desconecta"),
                      ("1", "desconecta so do portal"),
                      ("2", "desconecta do portal e do SMS")],
    "ACCLINE": [("1", "ignicao fisica (fio laranja)"), ("0", "ignicao virtual"),
                ("17", "virtual por acelerometro")],
    # Ordem confirmada na propria tela do fabricante: "Ptl Select:TQ", "Ptl
    # Select:808", "Ptl Select:GT06" -- nessa sequencia, entao 0/1/2.
    "PTL_SEL": [("0", "TQ / Tianqin / H02"), ("1", "JT808"), ("2", "GT06")],
    "808SEL": [("0", "JT808 de 2011"), ("1", "JT808 de 2013")],
    "SOURCE_OFF_TYPE": [("0", "condicionado (so em condicao segura)"),
                        ("1", "imediato")],
    # Mesma ideia dos tres campos da ferramenta do fabricante (sinal, hora,
    # minuto), so que ja resolvidos nos fusos que se usa de verdade.
    "GMT_SET": [("E0000", "UTC / GMT 0 -- padrao do portal"),
                ("W0300", "GMT-3 Brasilia"),
                ("W0400", "GMT-4 Mato Grosso do Sul, Amazonas"),
                ("W0500", "GMT-5 Acre")],
    "WORK_MODE": [("0", "normal")],
}

# Everything the tracker answers that is NOT "set a field" -- found by sweeping
# opcodes against the device (0xF002 = unsupported, so the sweep was safe) and by
# reading the vendor tool's own button handlers. Ready to fire, no typing.
ACOES = [
    ("Versão e identificação", "#SOFTVERSION#IMEI#ICCID",
     "firmware, IMEI e chip"),
    ("Servidor e APN", "#SERVIP#SERVPORT#APN#USERPPP#PWPPP",
     "para onde ele manda os dados"),
    ("Rastreamento", "#FREQ#ACC_OFF_FREQ#PULSE#ANGLE_SEND#ANGLEVALUE#SPEED",
     "intervalos, curva e limite de velocidade"),
    ("Curva e parada", "#ANGLE_SEND#ANGLEVALUE#STOPT#SPEED",
     "o que dispara envio fora do intervalo"),
    ("Ignição e bloqueio", "#ACCLINE#ACCLOCK#ACCLT#SOURCE_OFF_TYPE",
     "fio laranja, trava e modo de corte"),
    ("Sensor de movimento", "#VIBL#VIBCHK#VIB#VIBCALL",
     "sensibilidade e alertas de vibração"),
    ("Economia de energia", "#SLEEPT#SLPDISCONNECT#MTK_DISSLP#GPS_DISSLP",
     "quando e como ele dorme"),
    ("Protocolo e portal", "#PTL_SEL#808SEL#GT06ICCID#GT06METER#GT06IEXVOL",
     "formato dos pacotes, odômetro e tensão"),
    ("Fuso e filtro", "#GMT_SET#GPS_FINTER_EN#BLIND_EN#TIMING_RESET",
     "fuso, deriva do GPS e log sem sinal"),
    ("Alarmes por SMS", "#SOS_SMS_EN#SOS_CALL_EN#ACC_SMS_EN#SPDSMSEN",
     "quais eventos viram SMS ou ligação"),
    ("Áudio e escuta", "#VOICE_CTRL_EN#VOICE_DB_VALUE#VOICE_DB_TIME",
     "microfone: limiar de ruído e disparo"),
    ("Status do sistema", f"moni:{proto.MSG_MONI_SYS:04X}",
     "um quadro: sinal, ignição, energia, tempo ligado"),
    ("Posição do GPS", f"moni:{proto.MSG_MONI_GPS:04X}",
     "um quadro: fix, satélites, coordenada"),
    ("Alarme de colisão", f"moni:{proto.MSG_COLISAO_GET:04X}",
     "modo, limiar e nº de detecções do acelerômetro"),
    ("Registros do gSensor", f"moni:{proto.MSG_GSENSOR_REGS:04X}",
     "quantos eventos de aceleração ele guardou"),
    ("Valor bruto do gSensor", f"moni:{proto.MSG_GSENSOR_LER:04X}",
     "lê os registradores do acelerômetro"),
    ("Tempo de parada", f"moni:{proto.MSG_PARADA:04X}",
     "de quanto em quanto tempo reporta parado"),
    ("Reiniciar rastreador", f"moni:{proto.MSG_RESET:04X}",
     "reinicia o aparelho -- a porta cai por ~10 s"),
]

# Live status, shown the same way the vendor tool's own monitoring window
# shows it. Field names and wording match theirs one to one once the stream
# is decoded.
# Blocos do painel de telemetria. As chaves continuam as mesmas do parser --
# muda so como sao agrupadas e desenhadas.
MONI_BLOCOS = [
    ("Rede", [("SIM", "Chip"), ("REG", "Registrado"), ("NET", "Rede"),
              ("Band", "Banda"), ("AreaID", "Área (LAC)"),
              ("CellID", "Célula"), ("PPP Times", "Conexões PPP"),
              ("Socket Send", "Enviados ao portal"),
              ("Socket Receive", "Recebidos do portal")]),
    ("Veículo e elétrica", [("ACC", "Ignição"), ("Power", "Energia externa"),
                            ("Battery", "Bateria interna"),
                            ("Mileage", "Odômetro"),
                            ("Vibration", "Movimento"),
                            ("Defences", "Modo defesa"), ("Sleep", "Dormindo")]),
    ("Sistema", [("System Status", "Estado"), ("Run Time", "Tempo ligado"),
                 ("SIM IMSI", "IMSI do chip"), ("Sms Send", "SMS enviados"),
                 ("Sms Rec", "SMS recebidos"),
                 ("Call IN", "Ligações recebidas"),
                 ("Call Out", "Ligações feitas")]),
]
# valor em destaque grande no topo de cada bloco
MONI_DESTAQUE = {"Rede": ("CSQ", "Sinal GSM"),
                 "Veículo e elétrica": ("Voltage", "Tensão de entrada")}

MONI_SISTEMA = [
    [("SIM", "Chip"), ("REG", "Registrado na rede"),
     ("NET", "Rede"), ("AreaID", "Área (LAC)"), ("CellID", "Célula")],
    [("CSQ", "Sinal GSM"), ("Band", "Rede 2G/4G"), ("Mileage", "Odômetro"),
     ("Defences", "Modo defesa"), ("Power", "Energia externa")],
    [("ACC", "Ignição"), ("Battery", "Bateria interna"),
     ("Vibration", "Movimento"), ("Sleep", "Dormindo"),
     ("Voltage", "Tensão de entrada")],
    [("PPP Times", "Conexões PPP"), ("Call IN", "Ligações recebidas"),
     ("Call Out", "Ligações feitas")],
    [("Sms Send", "SMS enviados"), ("Sms Rec", "SMS recebidos"),
     ("SIM IMSI", "IMSI do chip")],
    [("Socket Send", "Enviados ao portal"),
     ("Socket Receive", "Recebidos do portal")],
    [("System Status", "Estado do sistema"), ("Run Time", "Tempo ligado")],
]

MONI_GPS = [
    ("Status", "Fix"), ("Satellite", "Satélites"), ("com sinal", "Com sinal"),
    ("HDOP", "HDOP"), ("Velocidade", "Velocidade"), ("Proa", "Proa"),
    ("Longitude", "Longitude"), ("Latitude", "Latitude"),
    ("DateTime", "Data e hora (UTC)"), ("Collect Times", "Leituras"),
    ("sats", "PRN:sinal"),
]

# System Status codes the firmware reports, in the order the vendor tool lists
# them -- the stream carries the index, not the text.
MONI_ESTADOS = [
    "Init", "Wait Reg Net", "Begig PPP", "Wait PPP", "Call Deal Begin",
    "Call Deal Wait", "DNS Begin", "DNS Wait", "Socket Begin", "Socket Wait",
    "Reg Server Begin", "Reg Server Wait", "Login Server Begin",
    "Login Server Wait", "Goto Idle", "Normal Connect", "Re Connect Begin",
    "Re Connect Wait", "Deep Sleep Begin", "Deep Sleep Wait", "Wait Active",
    "Reset Delay", "Reste Doing", "Goto Fly Mode", "Fly Mode", "Attach Begin",
    "Attach Wait",
]

# Read back from the device: these stayed silent, so they are either unknown to
# this firmware or write-only. Kept in the table (another J16 build may answer)
# but greyed out, so nobody wastes time filling in a field that goes nowhere.
NAO_CONFIRMADOS = {
    "POS_STYLE", "RADIUS", "DIS_COEFFI", "TRACE", "OUT", "OUTS", "POFT",
    "LED_CTRL", "SLEEP", "WAKEUP", "WAKEUPT", "BATT_TYPE", "LBV", "STOPT",
    "VIBT", "VIBGPS", "VIB_BASE", "VIBSMS_EN", "POFSMS_EN", "OUTSMS_EN",
    "WARN_TIMES", "EQUTYPE", "PHONE", "NET_MODE", "LOG_EN", "SYNC_DT",
    "RFIDENABLE", "RFIDRECEN", "RFIDNOACCT", "RFIDSFDELAY",
    "DNS_ENABLE", "TIMING_RESET",
}

# Hardware/SIM identity and the password: read-only. Shown so the tech can see
# them, but never selected, never written, never exported, never touched by an
# import -- a garbled read here once wrote NUL bytes into an exported .ini.
SOMENTE_LEITURA = {
    "IMEI", "ICCID", "IMSI", "TERIID", "SOFTVERSION", "PSW", "WORK_MODE",
}

# ponytail: the device answered a 3-key read happily; 6 keeps the line short
# enough to stay clear of any firmware buffer limit. Raise it if reads feel slow.
BATCH = 6


# Prefixos que a ferramenta do fabricante mostra na tela e as anotacoes de
# campo usam. Eles nunca chegam ao fio: o tipo do quadro ATYS (0x0201 gravar /
# 0x0202 ler) ja diz o que e. Aceitar a sintaxe evita o tecnico ter que
# traduzir na cabeca o que esta escrito no papel.
PREFIXOS = {"SZCS": "gravar", "CXCS": "ler", "SCXSZ": "ler", "SXCS": "ler"}

# Comandos que existem de verdade, mas no canal de SMS e da plataforma. Dizer
# isso e diferente de dizer "nao entendi": o primeiro caso e "existe, canal
# errado", o segundo e "isso nao e comando nenhum".
CMD_SMS = {
    "PARAM", "STATUS", "VERSION", "SCXSZ", "GPRSSET", "WHERE", "URL",
    "POSITION", "RESET", "CLEAR", "FACTORY", "RELAY", "DWXX", "SETLOCX",
    "ADDRESS", "TIMER", "HBT", "GMT", "GPRSON", "SIGNAL", "ACCALM",
    "POWERALM", "BATALM", "SENALM", "JAMMER", "MILEAGE", "MOVING", "SERVER",
    "APN", "RFID", "SOS", "CENTER", "MONITOR", "TRACKER",
}


# 0x0201/0x0202 nao sao opcodes: sao o campo "tipo" do quadro ATYS, que vai
# sempre acompanhado do nome do parametro no corpo. Sugerir moni:0202 para eles
# era mandar o tecnico construir um quadro de leitura vazio, que nao pede nada
# e por isso nao responde nada.
TIPOS_QUADRO = {
    "0201": "o tipo do quadro de GRAVACAO de parametro",
    "0202": "o tipo do quadro de LEITURA de parametro",
    "8201": "a resposta de uma gravacao",
    "8202": "a resposta de uma leitura",
}


def dica_hex(cru):
    """Sugestao para quem digitou 4 digitos hex soltos."""
    if cru in TIPOS_QUADRO:
        return (f" 0x{cru} nao e um comando: e {TIPOS_QUADRO[cru]}, e ele "
                "precisa do nome do parametro junto. Para ler use #CHAVE, "
                "para gravar #CHAVE=valor.")
    return f" Para opcode use moni:{cru}."


def classificar_recusa(texto):
    """Por que este texto nao pode ser enviado: 'sms' ou 'formato'."""
    base = texto.strip().upper().split(",")[0].split("#")[0].split("=")[0]
    return "sms" if base.strip() in CMD_SMS else "formato"


def normalizar_comando(texto):
    """'SZCS#APN=x.br' -> '#APN=x.br'.  'APN' -> '#APN'.  '#FREQ' inalterado.

    Devolve (texto_atys, forcar) onde forcar e 'ler', 'gravar' ou None. Um
    texto que nao e comando de configuracao volta como (None, None), para o
    chamador tratar como texto solto.
    """
    t = texto.strip()
    if not t:
        return None, None
    cabeca, sep, resto = t.partition("#")
    forcar = PREFIXOS.get(cabeca.strip().upper())
    if sep and forcar:
        t = "#" + resto.strip()
    elif not t.startswith("#"):
        # chave pelada: 'APN' ou 'APN=x.br', desde que seja chave conhecida
        chave = t.split("=", 1)[0].strip().upper()
        if chave in ALL_COMMANDS:
            t = "#" + t.strip()
        else:
            return None, None
    if not t.startswith("#") or len(t) < 2:
        return None, None
    return t, forcar


def pasta_backup():
    """Onde os backups moram: ao lado do programa, ou no HOME se a pasta do
    programa nao aceitar escrita (Arquivos de Programas, pendrive travado)."""
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    for tentativa in (os.path.join(base, "backups"),
                      os.path.join(os.path.expanduser("~"), "J16 backups")):
        try:
            os.makedirs(tentativa, exist_ok=True)
            return tentativa
        except OSError:
            continue
    return None


def limpo_ascii(s):
    """So ASCII imprimivel -- uma leitura embaralhada ja gravou NUL num .ini."""
    return "".join(c for c in s if 32 <= ord(c) < 127)


def escrever_ini(caminho, valores):
    cp = configparser.ConfigParser()
    cp["J16"] = valores
    with open(caminho, "w", encoding="utf-8") as f:
        cp.write(f)


def nome_backup(quando=None):
    """'configuracao backup 2026-09-11 11-46-00.ini'.

    Sem ':' no nome: o Windows nao aceita dois-pontos em nome de arquivo, e o
    arquivo nao seria criado bem na hora em que ele mais importa.
    """
    quando = quando or datetime.datetime.now()
    return f"configuracao backup {quando:%Y-%m-%d %H-%M-%S}.ini"


def _topico(barra, texto):
    """Rotulo curto que nomeia o grupo de botoes seguinte."""
    from tkinter import ttk as _ttk
    _ttk.Label(barra, text=texto, style="Topico.TLabel"
               ).pack(side="left", padx=(0, 6))


def _divisor(barra):
    """Linha vertical entre dois grupos de botoes."""
    import tkinter as _tk
    _tk.Frame(barra, bg=tema.BORDA, width=1).pack(side="left", fill="y",
                                                  padx=12, pady=2)


def valor_suspeito(v):
    """True for a value that must not be written to the tracker unchecked:
    empty, longer than any field this firmware takes, or carrying 8-bit /
    control bytes -- which is what a garbled read looks like once it has been
    round-tripped through an .ini.
    """
    return (not v or len(v) > 60
            or any(not (32 <= ord(c) < 127) for c in v))


def hexdump(b):
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in b)
    return f"{b.hex(' ')}  |{asc}|"


class Link:
    """Serial transport. Opened the way ComTools opens it: 8N1, DTR/RTS low."""

    def __init__(self):
        self.s = None
        self.seq = 0

    @property
    def open(self):
        return self.s is not None and self.s.is_open

    def connect(self, port, baud):
        import serial
        s = serial.Serial()
        s.port, s.baudrate = port, int(baud)
        s.bytesize, s.parity, s.stopbits = 8, serial.PARITY_NONE, 1
        s.timeout = 0.1
        s.write_timeout = 2          # fail fast if the device stops reading
        s.dtr = s.rts = False
        s.open()
        try:
            s.set_buffer_size(rx_size=4096, tx_size=4096)
        except Exception:
            pass          # not supported off Windows; harmless
        self.s = s

    def close(self):
        if self.s:
            self.s.close()
        self.s = None

    def next_seq(self):
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    def send(self, payload):
        self.s.write(payload)
        self.s.flush()

    def read_any(self):
        return self.s.read(4096) if self.open else b""


def ports():
    try:
        from serial.tools import list_ports
        return [f"{p.device}  {p.description}" for p in list_ports.comports()]
    except Exception:
        return []


# The J16's config port is a SimCom/Qualcomm USB modem. Match on the USB vendor
# id or on the words that show up in the port description.
_TRACKER_VIDS = {0x1E0E, 0x05C6, 0x2C7C}
_TRACKER_HINTS = ("simtech", "simcom", "hs-usb", "qualcomm", "at port",
                  "usb serial", "usb-serial", "modem")


def detect_devices():
    """One entry per physical tracker, as '<dev>  <desc>' like ports().

    A SimCom module exposes four COM ports (modem/diag/NMEA/AT) that share a USB
    serial number, so grouping on that -- not on the port name -- is what keeps
    two trackers apart. From each group take the AT port, which is the config one.
    """
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    grupos = {}
    for p in list_ports.comports():
        blob = f"{p.description or ''} {p.hwid or ''}".lower()
        if not (p.vid in _TRACKER_VIDS or any(h in blob for h in _TRACKER_HINTS)):
            continue
        # Serial number first. Falling back to the USB location means cutting the
        # ':x.N' interface suffix off -- '1-3:x.5' and '1-3:x.2' are two ports of
        # the same device on hub path 1-3, and must land in one group.
        chave = p.serial_number or (p.location or "").split(":")[0] \
            or f"{p.vid}:{p.pid}"
        grupos.setdefault(chave, []).append(p)
    saida = []
    for chave, portas in grupos.items():
        at = [p for p in portas if "at port" in (p.description or "").lower()]
        escolhida = (at or sorted(portas, key=lambda p: p.device))[0]
        saida.append(f"{escolhida.device}  {escolhida.description}")
    return saida


# kept so older callers/scripts do not break
detect_trackers = detect_devices


def portas_irmas(device):
    """As outras portas COM do MESMO modulo fisico.

    O SimCom expoe quatro (AT, modem, diag, NMEA) com o mesmo numero de serie
    USB. O configurador conversa pela AT, mas velocidade, proa e HDOP saem em
    NMEA na porta vizinha -- so escutando da para preencher esses campos.
    """
    try:
        from serial.tools import list_ports
        portas = list(list_ports.comports())
    except Exception:
        return []
    eu = next((p for p in portas if p.device == device), None)
    if eu is None:
        return []
    chave = eu.serial_number or (eu.location or "").split(":")[0]
    if not chave:
        return []
    irmas = []
    for p in portas:
        if p.device == device:
            continue
        outra = p.serial_number or (p.location or "").split(":")[0]
        if outra and outra == chave:
            irmas.append(p.device)
    return sorted(irmas)


def parse_kv(raw):
    """Key=value out of either an .ini body or the colleague's .txt notes.

    Splits '#'-joined pairs (SZCS#FREQ=15#PULSE=15), drops '//' and ';'
    comments and '[section]' headers. Returns (pairs dict, discarded count).
    """
    pairs, descartadas = {}, 0
    for line in raw.splitlines():
        line = line.split("//", 1)[0].strip()
        if not line or line.startswith((";", "[")) or "=" not in line:
            continue
        for seg in line.split("#"):
            if "=" not in seg:
                continue
            key, _, value = seg.partition("=")
            key = key.strip().strip(",").upper()
            value = value.strip()
            if key and all(c.isalnum() or c == "_" for c in key):
                pairs[key] = value
            else:
                descartadas += 1
    return pairs, descartadas


# Conteudo do "Detalhes tecnicos" do Sobre. Fica aqui como dado, e nao num
# arquivo ao lado, porque o programa e um exe unico: um .md solto nao viaja
# junto e a explicacao sumiria justamente na maquina de quem precisa dela.
SOBRE_TECNICO = [
    ("Duas portas, dois protocolos",
     "O J16 fala de dois jeitos, e confundir os dois e o erro mais comum.\n\n"
     "Por esta porta USB ele so entende ATYS, um protocolo binario que nao\n"
     "esta documentado em lugar nenhum. Pela rede (GPRS) ele fala GT06 com a\n"
     "plataforma -- outro protocolo, outro formato, outros comandos.\n\n"
     "Por isso PARAM#, STATUS#, RELAY,1# e parecidos nao respondem aqui: sao\n"
     "comandos de SMS e de plataforma. Testado com CR, LF e CRLF: silencio\n"
     "nos tres."),
    ("Como uma leitura vira bytes",
     "Quando voce pede #FREQ, o que sai no fio e isto:\n\n"
     "  ATYS 5953 000000000000000001 0202 0005 2346524551 07 0D0A\n"
     "       |    |                  |    |    |          |  |\n"
     "       |    |                  |    |    |          |  fim de linha\n"
     "       |    |                  |    |    |          soma de verificacao\n"
     "       |    |                  |    |    o texto \"#FREQ\"\n"
     "       |    |                  |    tamanho do texto\n"
     "       |    |                  tipo: 0202 le, 0201 grava\n"
     "       |    numero de sequencia\n"
     "       marcador YS\n\n"
     "Por isso 0x0202 sozinho nao faz nada: e uma etiqueta dentro do quadro,\n"
     "nao um comando. Sem o nome do parametro junto, nao ha o que pedir."),
    ("Como os comandos foram descobertos",
     "Nada aqui veio de manual: a porta USB nao tem documentacao publica em\n"
     "lugar nenhum. O caminho foi observar o trafego real entre a ferramenta\n"
     "do fabricante e um aparelho de verdade, e testar contra o aparelho ate\n"
     "cada campo bater com o que a tela do fabricante mostra.\n\n"
     "Os opcodes de evento -- colisao, gSensor, tempo de parada -- vieram do\n"
     "mesmo processo: disparo, observacao da resposta, comparacao com a tela.\n\n"
     "Os nomes de parametro vem da propria ferramenta do fabricante; o\n"
     "significado de cada um foi conferido lendo do aparelho de verdade."),
    ("O quadro de GPS, campo a campo",
     "Este e o mapa do quadro 0x8101, o que alimenta a aba Monitoramento:\n\n"
     "  byte 0       fix valido\n"
     "  bytes 1-2    hemisferios (E/W, N/S)\n"
     "  byte 3       HDOP x 10\n"
     "  bytes 4-5    velocidade em km/h\n"
     "  bytes 6-7    proa em graus\n"
     "  bytes 8-11   longitude: grau, minuto, centesimo, dez-milesimo\n"
     "  bytes 12-15  latitude, mesmo formato\n"
     "  bytes 16-21  data e hora em UTC\n"
     "  byte 22      quantos satelites vem na lista\n"
     "  byte 23...   pares (satelite, sinal)\n"
     "  ultimos 2    contador de leituras\n\n"
     "A prova de que esta certo: o quadro fecha exatamente em 23 + 2*n + 2\n"
     "bytes. Os dois capturados batem, um com 14 satelites e outro com 16.\n\n"
     "A coordenada engana: a fracao do minuto e decimal, nao binaria. Lida\n"
     "como binaria, o ponto caia 1 km fora do lugar."),
    ("O que responde e o que nao",
     "Dos 90 parametros da tabela, 58 respondem neste firmware (V5.56).\n\n"
     "Os outros 32 ficam cinzas e escondidos pelo filtro. Nao respondem: ou\n"
     "o firmware nao conhece o nome, ou o parametro e so de escrita. Nos dois\n"
     "casos nao da para confiar no que aparece.\n\n"
     "Nomes vem da ferramenta do fabricante. Descricoes, onde nao havia nota\n"
     "de campo, sao interpretacao -- e estao marcadas como tal."),
    ("O console e livre",
     "Na aba Comandos livres voce digita qualquer comando, tenha ele botao ou\n"
     "nao. Nao ter atalho na tela nao significa estar bloqueado: PARAM#,\n"
     "STATUS#, RELAY,1# e outros comandos de SMS e de plataforma sao enviados\n"
     "normalmente -- esta porta USB e que costuma nao responder a eles, e o\n"
     "historico anota isso.\n\n"
     "A unica excecao e FACTORY#, que apaga tudo: ele pede confirmacao antes."),
    ("O que so vai com confirmacao",
     "Alguns comandos apagam configuracao ou tiram o aparelho do ar. Os botoes\n"
     "da tela nunca os disparam sozinhos:\n\n"
     "  0x0301   grava servidor; com corpo vazio apaga SERVIP e APN\n"
     "  0x0340   corta combustivel e energia\n"
     "  0x0341   religa\n"
     "  0x0370   modo aviao\n"
     "  0x0373   desliga o aparelho\n"
     "  FACTORY# reset de fabrica, apaga tudo\n\n"
     "Gravacao vai uma chave por quadro. Em lotes, o firmware para de ler no\n"
     "meio da linha e a porta morre -- isso ja travou um aparelho aqui.\n\n"
     "E antes de cada gravacao o programa salva sozinho um backup com data e\n"
     "hora, na pasta backups, para existir caminho de volta."),
]


def cor_marca(fundo):
    """Assinatura a 45% sobre o fundo: legivel de perto, invisivel de longe."""
    return tema.mistura(tema.TXT3, fundo, 0.45)


def abrir_sobre(pai):
    """Janela Sobre, pintada com o tema em uso -- um messagebox do sistema
    ficaria branco no meio de tudo escuro."""
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(pai)
    win.title("Sobre o Configurador J16")
    win.configure(bg=tema.BG)
    win.resizable(False, False)
    win.transient(pai)

    caixa = tk.Frame(win, bg=tema.CARD, padx=24, pady=20,
                     highlightbackground=tema.BORDA, highlightthickness=1)
    caixa.pack(padx=14, pady=14)

    tk.Label(caixa, text="Configurador J16", bg=tema.CARD, fg=tema.ACENTO,
             font=(tema.FONTE, 16, "bold")).pack(anchor="w")
    tk.Label(caixa, text=f"versão {VERSAO}", bg=tema.CARD, fg=tema.TXT2,
             font=tema.F_TXT).pack(anchor="w", pady=(0, 14))

    tk.Label(caixa, text=AUTOR, bg=tema.CARD, fg=tema.TXT,
             font=tema.F_BOLD).pack(anchor="w")
    tk.Label(caixa, text=f"autoria e engenharia reversa  \u00b7  {FEITO_EM}",
             bg=tema.CARD, fg=tema.TXT2,
             font=tema.F_TXT).pack(anchor="w", pady=(0, 14))

    tk.Frame(caixa, bg=tema.BORDA, height=1).pack(fill="x", pady=(0, 14))

    texto = ("Configuração e diagnóstico do rastreador J16 pela porta USB.\n\n"
             "O protocolo desta porta não é documentado em lugar nenhum: foi\n"
             "reconstruído por engenharia reversa a partir do tráfego real do\n"
             "aparelho, conferido contra um aparelho real, quadro por quadro.\n\n"
             "90 parâmetros mapeados, 58 confirmados no firmware V5.56.")
    tk.Label(caixa, text=texto, bg=tema.CARD, fg=tema.TXT2, font=tema.F_TXT,
             justify="left", anchor="w").pack(anchor="w")

    # O detalhe fica dobrado: quem so quer saber a versao nao precisa ver
    # seis paginas de protocolo, e quem quer aprender tem tudo aqui dentro.
    painel = tk.Frame(caixa, bg=tema.CARD)
    corpo = tk.Text(painel, width=74, height=17, wrap="none", relief="flat",
                    bg=tema.TERM, fg=tema.LOG_NEUTRO, font=tema.F_MONO,
                    padx=12, pady=10, insertwidth=0, cursor="arrow",
                    highlightthickness=1, highlightbackground=tema.BORDA)
    rolagem = ttk.Scrollbar(painel, orient="vertical", command=corpo.yview)
    corpo.configure(yscrollcommand=rolagem.set)
    corpo.pack(side="left", fill="both", expand=True)
    rolagem.pack(side="right", fill="y")
    corpo.tag_configure("titulo", foreground=tema.ACENTO,
                        font=(tema.MONO, 10, "bold"), spacing1=10, spacing3=6)
    corpo.tag_configure("corpo", foreground=tema.LOG_VAL)
    for n, (titulo, conteudo) in enumerate(SOBRE_TECNICO):
        corpo.insert("end", f"{n + 1}. {titulo}\n", "titulo")
        corpo.insert("end", conteudo + "\n\n", "corpo")
    corpo.configure(state="disabled")

    rodape = tk.Frame(caixa, bg=tema.CARD)
    rodape.pack(fill="x", pady=(18, 0))

    def alterna_detalhes():
        if painel.winfo_manager():
            painel.pack_forget()
            det_btn.config(text="Como isto funciona  \u25be")
        else:
            painel.pack(fill="both", expand=True, pady=(14, 0), before=rodape)
            det_btn.config(text="Como isto funciona  \u25b4")
        win.update_idletasks()

    det_btn = ttk.Button(rodape, text="Como isto funciona  \u25be",
                         style="Outline.TButton", command=alterna_detalhes)
    det_btn.pack(side="left")
    ttk.Button(rodape, text="Fechar", style="Primary.TButton",
               command=win.destroy).pack(side="right")

    win.update_idletasks()
    x = pai.winfo_rootx() + (pai.winfo_width() - win.winfo_width()) // 2
    y = pai.winfo_rooty() + (pai.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    win.bind("<Escape>", lambda _e: win.destroy())
    win.grab_set()
    return win


def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"Configurador J16  {VERSAO}")
    root.geometry("1280x720")

    style = tema.aplicar(root, tema.modo_salvo())
    root.minsize(1100, 640)

    # One tracker per panel, side by side. Each owns its port, its reader
    # thread and its own copy of the table -- nothing is shared, so two
    # trackers can be read and written at the same time.
    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.pack(fill="both", expand=True)
    paineis = []

    def montar_painel(pai, indice):
        link = Link()
        rx_q = queue.Queue()
        # --- connection bar -----------------------------------------------------
        top = tk.Frame(pai, bg=tema.CARD, padx=10, pady=8)
        top.pack(fill="x")
        tk.Frame(pai, bg=tema.BORDA, height=1).pack(fill="x")
        # Holder do rodape ancorado no fundo AGORA, antes do notebook: pack
        # aloca por ordem, entao o que vem antes reserva espaco. Assim os
        # botoes de baixo nunca ficam sem altura quando a janela encolhe.
        rodape_painel = tk.Frame(pai, bg=tema.BG)
        rodape_painel.pack(side="bottom", fill="x")
        tk.Label(top, text="PORTA", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left")
        port_var = tk.StringVar()
        port_cb = ttk.Combobox(top, textvariable=port_var, width=32)
        port_cb.pack(side="left", padx=(8, 4))
        ttk.Button(top, text="atualizar", width=9, style="Ghost.TButton",
                   command=lambda: refresh_ports()).pack(side="left")
        tk.Label(top, text="BAUD", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left", padx=(14, 0))
        baud_var = tk.StringVar(value="115200")
        ttk.Combobox(top, textvariable=baud_var, width=8,
                     values=["115200", "9600", "19200", "38400", "57600", "921600"]
                     ).pack(side="left", padx=8)
        conn_btn = ttk.Button(top, text="Conectar", style="Outline.TButton")
        conn_btn.pack(side="left", padx=(6, 12))
        # pill de status: ponto + texto, do jeito que um painel moderno mostra
        status = tema.Badge(top, "DESCONECTADO", tema.ERRO, fundo=tema.CARD)
        status.pack(side="left")

        def rotulo_tema():
            """Diz o que o clique FAZ, nao o tema atual -- e o que confunde
            menos em botao que alterna."""
            return ("\u263c  Tema claro" if tema.MODO == "escuro"
                    else "\u263e  Tema escuro")

        def alterna_tema():
            novo = "claro" if tema.MODO == "escuro" else "escuro"
            tema.trocar(root, novo)
            tema_btn.config(text=rotulo_tema())
            for lbl in marcas:
                lbl.config(bg=tema.CARD if lbl is marca_topo else tema.BG,
                           fg=cor_marca(tema.CARD if lbl is marca_topo
                                        else tema.BG))
            # o Text do log guarda as cores nas tags, que nao entram no repinte
            log.configure(bg=tema.TERM, fg=tema.LOG_NEUTRO,
                          highlightbackground=tema.BORDA)
            for nome, cor in (("tx", tema.LOG_TX), ("rx", tema.LOG_RX),
                              ("err", tema.LOG_ERR), ("val", tema.LOG_VAL),
                              ("hora", tema.LOG_HORA)):
                log.tag_configure(nome, foreground=cor)
            revisar_sujos()          # as marcas de ambar precisam da cor nova
            notify(f"TEMA: {novo}", tema.ACENTO)

        tema_btn = ttk.Button(top, width=14, style="Outline.TButton",
                              command=alterna_tema, text=rotulo_tema())
        tema_btn.pack(side="right")
        ttk.Button(top, text="Sobre", width=8, style="Ghost.TButton",
                   command=lambda: abrir_sobre(root)).pack(side="right", padx=6)
        # Marca d'agua: mistura com o fundo em vez de cinza chapado, para
        # assinar sem disputar atencao com o dado na tela.
        marca_topo = tk.Label(top, text=ASSINATURA, bg=tema.CARD,
                              fg=cor_marca(tema.CARD), font=(tema.FONTE, 8))
        marca_topo.pack(side="right", padx=10)
        marcas = [marca_topo]

        def _ajusta_marcas(_e=None):
            """Assinatura e decoracao: some quando a janela aperta, para os
            botoes -- que sao funcao -- nunca ficarem sem espaco.

            Blindado: um erro aqui roda dentro do <Configure> e, se escapar,
            interrompe o layout no meio -- foi o que deixava a barra de baixo
            com 1px e os botoes sumindo."""
            try:
                largo = root.winfo_width() >= 1150
                for lbl in marcas:
                    if not lbl.winfo_exists():
                        continue
                    if largo and not lbl.winfo_manager():
                        lbl.pack(side="right", padx=10)
                    elif not largo and lbl.winfo_manager():
                        lbl.pack_forget()
            except tk.TclError:
                pass
        root.bind("<Configure>", _ajusta_marcas, add="+")
        # --- notebook -----------------------------------------------------------
        # clam is the only stock theme that honours tab background/padding, which is
        # what makes the active tab actually stand out from the window.
        nb = ttk.Notebook(pai, padding=6)
        nb.pack(fill="both", expand=True)
        par_tab = ttk.Frame(nb)
        nb.add(par_tab, text="Parametros")

        # Search + "hide the dead ones" -- 90 rows is a wall of text otherwise.
        # Duas linhas: senao os botoes nao cabem numa janela estreita e o
        # ultimo grupo some. Cada linha e curta o bastante para caber sempre.
        filtro = ttk.Frame(par_tab, padding=(4, 6))
        filtro.pack(fill="x")
        _topico(filtro, "BUSCA")
        busca_var = tk.StringVar()
        ttk.Entry(filtro, textvariable=busca_var, width=20).pack(side="left")
        ttk.Button(filtro, text="limpar", width=8, style="Ghost.TButton",
                   command=lambda: busca_var.set("")).pack(side="left", padx=4)
        _divisor(filtro)
        _topico(filtro, "EXIBIR")
        so_vivos = tk.BooleanVar(value=True)
        ttk.Checkbutton(filtro, text="esconder os que não respondem",
                        variable=so_vivos,
                        command=lambda: aplicar_filtro()).pack(side="left")
        filtro_lbl = ttk.Label(filtro, foreground=tema.TXT2, text="")
        filtro_lbl.pack(side="right", padx=6)
        filtro2 = ttk.Frame(par_tab, padding=(4, 0))
        filtro2.pack(fill="x")

        ttk.Label(par_tab, foreground=tema.ALERTA, padding=(4, 0),
                  text="\u2022 antes do nome = valor na tela ainda não gravado "
                       "no rastreador"
                  ).pack(anchor="w")
        corpo = ttk.Frame(par_tab)
        corpo.pack(fill="both", expand=True)
        canvas = tk.Canvas(corpo, highlightthickness=0, bg=tema.BG)
        scroll = ttk.Scrollbar(corpo, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, style="TFrame")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        janela = canvas.create_window((0, 0), window=inner, anchor="nw")
        # sem isto os cards param na largura natural e sobra um vazio a direita
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(janela, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        # Wheel scrolls the form from anywhere inside the tab, but only when there is
        # something to scroll -- otherwise the view jitters against its own edge.
        def _wheel(e):
            top_frac, bot_frac = canvas.yview()
            if top_frac <= 0.0 and bot_frac >= 1.0:
                return
            canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        rows = {}          # cmd -> (checked BooleanVar, value StringVar)
        nomes = {}         # cmd -> (label do nome, e duvidoso?)
        edicao = {}        # cmd -> widget de edicao, para tingir de ambar
        linhas = []        # (cmd, description, [widgets]) so rows can be hidden
        cabecalhos = []    # (group label widget, [cmds under it])

        fechados = set()   # groups folded away by a click on their heading

        for group, cmds in COMMANDS.items():
            # Um card por grupo: moldura de 1px, faixa de acento e cabecalho
            # clicavel. Dobrar agora esconde o corpo inteiro de uma vez, em vez
            # de tirar linha por linha do grid.
            moldura = tk.Frame(inner, bg=tema.BORDA, padx=1, pady=1)
            moldura.pack(fill="x", padx=6, pady=(0, 8))
            dentro = tk.Frame(moldura, bg=tema.CARD)
            dentro.pack(fill="both", expand=True)
            faixa = tk.Frame(dentro, bg=tema.CARD_ALT, cursor="hand2")
            faixa.pack(fill="x")
            tk.Frame(faixa, bg=tema.ACENTO, width=3).pack(side="left", fill="y")
            cab = tk.Label(faixa, bg=tema.CARD_ALT, fg=tema.ACENTO,
                           font=tema.F_TIT, anchor="w", padx=8, pady=6,
                           cursor="hand2")
            cab.pack(side="left")
            dica_grp = tk.Label(faixa, text=GRUPO_AJUDA.get(group, ""),
                                bg=tema.CARD_ALT, fg=tema.TXT2, font=tema.F_TXT,
                                anchor="w", cursor="hand2")
            dica_grp.pack(side="left", padx=10)
            tema.icone_info(
                faixa, fundo=tema.CARD_ALT,
                on_click=lambda e, g=group: tema.popover(
                    root, g, [ajuda.GRUPO.get(g, GRUPO_AJUDA.get(g, ""))],
                    e.x_root + 12, e.y_root + 8)
            ).pack(side="left")
            caixa = tk.Frame(dentro, bg=tema.CARD, padx=8, pady=6)
            caixa.pack(fill="x")
            for w in (faixa, cab, dica_grp):
                w.bind("<Button-1>", lambda _e, g=group: dobrar(g))
            cabecalhos.append((cab, moldura, caixa, group, [c for c, _ in cmds]))
            inner_grid = caixa
            for cmd, description in cmds:
                r = inner_grid.grid_size()[1]
                chk = tk.BooleanVar()
                val = tk.StringVar()
                so_leitura = cmd in SOMENTE_LEITURA
                duvidoso = cmd in NAO_CONFIRMADOS
                ws = []

                # every row can be ticked, but for identity rows the tick only means
                # "include me in the next Ler" -- writing/exporting still skips them
                w = ttk.Checkbutton(inner_grid, variable=chk, style="Card.TCheckbutton")
                w.grid(row=r, column=0, sticky="w"); ws.append(w)
                w = ttk.Label(inner_grid, text=cmd, width=18,
                              foreground=tema.TXT3 if duvidoso else tema.TXT,
                              style="Card.TLabel")
                w.grid(row=r, column=1, sticky="w"); ws.append(w)
                # guarda o PAPEL, nao a cor: guardando a cor, uma troca de tema
                # deixava o nome pintado com a cor do tema anterior -- texto
                # escuro em fundo escuro, ilegivel
                nomes[cmd] = (w, duvidoso)

                editavel = not so_leitura
                if cmd in LIGA_DESLIGA and editavel:
                    # two explicit buttons beat a box where 1 means yes
                    linha_lig = ttk.Frame(inner_grid, style="Card.TFrame")
                    ttk.Radiobutton(linha_lig, text="Ligado", value="1",
                                    variable=val, style="Card.TRadiobutton"
                                    ).pack(side="left")
                    ttk.Radiobutton(linha_lig, text="Desligado", value="0",
                                    variable=val, style="Card.TRadiobutton"
                                    ).pack(side="left", padx=(8, 0))
                    linha_lig.grid(row=r, column=2, sticky="w", padx=4)
                    campo = linha_lig
                elif cmd in ESCOLHAS and editavel:
                    opcoes = ESCOLHAS[cmd]
                    rotulos = [f"{v} - {t}" for v, t in opcoes]
                    cb = ttk.Combobox(inner_grid, values=rotulos, width=28,
                                      state="readonly")
                    cb.grid(row=r, column=2, sticky="w", padx=4)

                    def espelha(_=None, cb=cb, val=val, opcoes=opcoes):
                        i = cb.current()
                        if i >= 0:
                            val.set(opcoes[i][0])

                    def recebe(*_, cb=cb, val=val, opcoes=opcoes):
                        v = val.get().strip()
                        for i, (codigo, _t) in enumerate(opcoes):
                            if codigo == v:
                                cb.current(i)
                                return
                        cb.set(v)

                    cb.bind("<<ComboboxSelected>>", espelha)
                    val.trace_add("write", recebe)
                    campo = cb
                else:
                    campo = ttk.Entry(inner_grid, textvariable=val, width=30,
                                      state="readonly" if so_leitura else "normal")
                    campo.grid(row=r, column=2, sticky="w", padx=4)
                ws.append(campo)

                opcoes_campo = ESCOLHAS.get(cmd)
                info = tema.icone_info(
                    inner_grid,
                    on_click=lambda e, c=cmd, d=description, oc=opcoes_campo,
                    rp=(cmd not in NAO_CONFIRMADOS),
                    ro=(cmd in SOMENTE_LEITURA): tema.popover(
                        root, *ajuda.do_campo(
                            c, d,
                            ajuda.tipo_do_campo(c, LIGA_DESLIGA, ESCOLHAS, ro),
                            opcoes=oc, respondeu=rp, so_leitura=ro)[::1],
                        e.x_root + 12, e.y_root + 8))
                info.grid(row=r, column=4, sticky="w", padx=(2, 8))
                ws.append(info)

                if editavel:
                    edicao[cmd] = campo
                    # rede de seguranca: o trace do StringVar ja cobre, mas uma
                    # tecla solta garante a marca mesmo se algo comer o trace
                    campo.bind("<KeyRelease>",
                               lambda _e, c=cmd: marca_sujo(c), add="+")

                if duvidoso:
                    description += "   (nao respondeu no V5.56)"
                elif so_leitura:
                    description += "   (somente leitura)"
                w = ttk.Label(inner_grid, text=description,
                              style="CardDica.TLabel",
                              foreground=tema.TXT3 if duvidoso else tema.TXT2)
                w.grid(row=r, column=3, sticky="w", padx=6); ws.append(w)

                rows[cmd] = (chk, val)
                if editavel:
                    val.trace_add("write", lambda *_a, c=cmd: marca_sujo(c))
                linhas.append((cmd, description.lower(), ws))

        def marca_sujo(cmd):
            """Um valor na tela que nao confere com o ultimo que o rastreador
            devolveu ainda nao esta gravado nele. Marca com bolinha laranja --
            some sozinho quando a gravacao volta confirmada."""
            alvo = nomes.get(cmd)
            if not alvo:
                return
            lbl, duvidoso = alvo
            cor = tema.TXT3 if duvidoso else tema.TXT
            atual = rows[cmd][1].get().strip()
            lido = last_values.get(cmd)
            sujo = bool(atual) and atual != (lido or "")
            lbl.config(text=("\u2022 " + cmd) if sujo else cmd,
                       foreground=tema.ALERTA if sujo else cor)
            campo = edicao.get(cmd)
            if campo is None:
                return
            base = campo.winfo_class()          # TEntry / TCombobox / TFrame
            if base == "TEntry":
                campo.config(style="Sujo.TEntry" if sujo else "TEntry")
            elif base == "TCombobox":
                campo.config(style="Sujo.TCombobox" if sujo else "TCombobox")

        def revisar_sujos():
            for c in rows:
                marca_sujo(c)

        def aplicar_filtro(*_):
            """Show only rows matching the search box, and optionally drop the
            ones this firmware never answers -- 32 dead rows out of 90 is most of
            what makes the table hard to read. A folded group hides its rows too,
            except while something is typed in the search box: a search that
            silently skipped folded groups would look like "not found"."""
            termo = busca_var.get().strip().lower()
            esconde = so_vivos.get()
            elegiveis, visiveis = set(), set()
            for cmd, desc, ws in linhas:
                ok = (not termo or termo in cmd.lower() or termo in desc)
                if esconde and cmd in NAO_CONFIRMADOS:
                    ok = False
                if ok:
                    elegiveis.add(cmd)
                    if not termo and GRUPO_DE[cmd] in fechados:
                        ok = False
                for w in ws:
                    w.grid() if ok else w.grid_remove()
                if ok:
                    visiveis.add(cmd)
            for cab, moldura, caixa, grupo, sob in cabecalhos:
                n = len(elegiveis & set(sob))
                aberto = grupo not in fechados or bool(termo)
                seta = "▾" if aberto else "▸"
                cab.config(text=f"{seta}  {grupo}   ({n})")
                if not n:            # card sem nada dentro sai da tela
                    moldura.pack_forget()
                    continue
                if not moldura.winfo_manager():
                    moldura.pack(fill="x", padx=6, pady=(0, 8))
                caixa.pack(fill="x") if aberto else caixa.pack_forget()
            canvas.configure(scrollregion=canvas.bbox("all"))
            filtro_lbl.config(text=f"{len(visiveis)} de {len(linhas)} parametros")

        def dobrar(grupo):
            fechados.symmetric_difference_update({grupo})
            aplicar_filtro()

        def todos_grupos(fechar):
            fechados.clear()
            if fechar:
                fechados.update(COMMANDS)
            aplicar_filtro()

        def marcar(ligar):
            """Tick/untick in one go. Marking hits only what is on screen and
            leaves the identity rows out -- IMEI, chip and firmware are never
            written, so ticking them just pads the next read. Unmarking clears
            everything, hidden rows included: a tick nobody can see is exactly
            how a value gets sent by accident."""
            n = 0
            for cmd, _desc, ws in linhas:
                if ligar:
                    if not ws[0].winfo_manager():
                        continue                     # escondido pelo filtro
                    if cmd in SOMENTE_LEITURA or GRUPO_DE[cmd] == GRUPO_INFO:
                        continue
                rows[cmd][0].set(ligar)
                n += 1
            notify(f"{'MARCAR' if ligar else 'DESMARCAR'}: {n} parametros",
                   tema.OK if ligar else tema.ACENTO)

        _topico(filtro2, "GRUPOS")
        ttk.Button(filtro2, text="fechar", width=9, style="Ghost.TButton",
                   command=lambda: todos_grupos(True)).pack(side="left", padx=2)
        ttk.Button(filtro2, text="abrir", width=9, style="Ghost.TButton",
                   command=lambda: todos_grupos(False)).pack(side="left", padx=2)
        def zerar_tudo():
            """Limpa a tela inteira. Nao toca no rastreador -- so apaga o que
            esta escrito aqui, para comecar uma configuracao do zero."""
            if not messagebox.askyesno(
                    "J16 -- Zerar", "Apaga o valor de todos os parametros na "
                    "tela.\n\nO rastreador nao e alterado: nada e enviado.\n\n"
                    "Confirma?", default="no"):
                return
            n = 0
            for cmd, (chk, val) in rows.items():
                if cmd in SOMENTE_LEITURA:
                    continue
                if val.get():
                    n += 1
                val.set("")
                chk.set(False)
            revisar_sujos()
            notify(f"ZERAR: {n} campos limpos na tela -- o rastreador nao mudou",
                   tema.ALERTA)

        _divisor(filtro2)
        _topico(filtro2, "SELEÇÃO")
        ttk.Button(filtro2, text="marcar", width=9, style="Ghost.TButton",
                   command=lambda: marcar(True)).pack(side="left", padx=2)
        ttk.Button(filtro2, text="desmarcar", width=11, style="Ghost.TButton",
                   command=lambda: marcar(False)).pack(side="left", padx=2)
        ttk.Button(filtro2, text="zerar", width=8, style="Ghost.TButton",
                   command=zerar_tudo).pack(side="left", padx=2)
        busca_var.trace_add("write", aplicar_filtro)
        aplicar_filtro()
        # --- monitoring tab -----------------------------------------------------
        mon_tab = ttk.Frame(nb, padding=8)
        nb.add(mon_tab, text="Monitoramento")
        moni = {}          # field name -> StringVar holding the live value

        def moni_campo(parent, nome, dica, r, c=0, largura=16):
            """Uma linha rotulo/valor dentro de um card. Sem dado mostra '--'
            apagado, em vez de texto cru."""
            lbl = tk.Label(parent, text=dica, bg=tema.CARD, fg=tema.TXT2,
                           font=tema.F_TXT, anchor="w")
            lbl.grid(row=r, column=c * 2, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value="--")
            val = tk.Label(parent, textvariable=var, bg=tema.CARD, fg=tema.TXT,
                           font=tema.F_BOLD, anchor="w", width=largura)
            val.grid(row=r, column=c * 2 + 1, sticky="w", pady=2)

            def pintar(*_):
                v = var.get().strip()
                val.configure(fg=tema.TXT3 if v in ("", "--") else tema.TXT)
            var.trace_add("write", pintar)
            moni[nome] = var
            return val

        grade = tk.Frame(mon_tab, bg=tema.BG)
        grade.pack(fill="x")
        for i, (titulo, campos) in enumerate(MONI_BLOCOS):
            moldura, caixa = tema.card(grade, titulo)
            moldura.grid(row=0, column=i, sticky="nsew", padx=(0, 8))
            grade.columnconfigure(i, weight=1, uniform="mon")
            destaque = MONI_DESTAQUE.get(titulo)
            linha0 = 0
            if destaque:
                nome, rotulo = destaque
                topo = tk.Frame(caixa, bg=tema.CARD)
                topo.grid(row=0, column=0, columnspan=2, sticky="w",
                          pady=(0, 6))
                var = tk.StringVar(value="--")
                tk.Label(topo, textvariable=var, bg=tema.CARD, fg=tema.ACENTO,
                         font=tema.F_GRANDE).pack(side="left")
                tk.Label(topo, text=rotulo, bg=tema.CARD, fg=tema.TXT2,
                         font=tema.F_TXT).pack(side="left", padx=(8, 0), pady=(8, 0))
                moni[nome] = var
                linha0 = 1
            for r, (nome, rotulo) in enumerate(campos):
                moni_campo(caixa, nome, rotulo, r + linha0)

        gps_mold, gps = tema.card(mon_tab, "GPS")
        gps_mold.pack(fill="x", pady=(8, 0))
        for i, (nome, dica) in enumerate(MONI_GPS):
            if nome == "sats":
                continue
            moni_campo(gps, nome, dica, i // 3, i % 3, 18)
        tk.Label(gps, text="PRN:sinal", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_TXT).grid(row=90, column=0, sticky="w", pady=(6, 0))
        var_sats = tk.StringVar(value="--")
        tk.Label(gps, textvariable=var_sats, bg=tema.CARD, fg=tema.LOG_RX,
                 font=tema.F_MONO, anchor="w").grid(
                     row=90, column=1, columnspan=5, sticky="w", pady=(6, 0))
        moni["sats"] = var_sats

        # Sits right under the coordinates, where the eye already is. Stays
        # disabled until there is a fix, so it can never open a stale spot.
        ultima_pos = [None]
        mapa_linha = tk.Frame(gps, bg=tema.CARD)
        mapa_linha.grid(row=98, column=0, columnspan=6, sticky="w", pady=(8, 0))

        def abrir_mapa():
            if ultima_pos[0] is None:
                return
            lat, lon = ultima_pos[0]
            webbrowser.open(f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}")
            notify(f"MAPA: abrindo {lat:.5f}, {lon:.5f} no navegador", tema.OK)

        def copiar_pos():
            if ultima_pos[0] is None:
                return
            lat, lon = ultima_pos[0]
            root.clipboard_clear()
            root.clipboard_append(f"{lat:.6f}, {lon:.6f}")
            notify(f"MAPA: {lat:.6f}, {lon:.6f} copiado", tema.OK)

        mapa_btn = ttk.Button(mapa_linha, text="Ver no mapa", state="disabled",
                              style="Outline.TButton", command=abrir_mapa)
        mapa_btn.pack(side="left")
        copia_btn = ttk.Button(mapa_linha, text="Copiar coordenada",
                               state="disabled", style="Ghost.TButton",
                               command=copiar_pos)
        copia_btn.pack(side="left", padx=6)
        mapa_lbl = tk.Label(mapa_linha, bg=tema.CARD, fg=tema.ALERTA,
                            font=tema.F_BOLD, text="aguardando fix do GPS")
        mapa_lbl.pack(side="left", padx=8)

        def set_pos(lat, lon):
            """Called from drain() on every GPS frame."""
            if lat is None:
                ultima_pos[0] = None
                mapa_btn.config(state="disabled")
                copia_btn.config(state="disabled")
                mapa_lbl.config(text="aguardando fix do GPS", fg=tema.ALERTA)
                return
            ultima_pos[0] = (lat, lon)
            mapa_btn.config(state="normal", cursor="hand2")
            copia_btn.config(state="normal", cursor="hand2")
            mapa_lbl.config(text=f"{lat:.5f}, {lon:.5f}", fg=tema.OK)

        tk.Label(gps, bg=tema.CARD, fg=tema.TXT2, font=tema.F_TXT,
                 justify="left", anchor="w",
                 text="Longitude e latitude só aparecem com fix -- sem sinal o "
                       "módulo repete a última posição, então mostrar seria mentira."
                 ).grid(row=99, column=0, columnspan=6, sticky="w", pady=(6, 0))
        # --- escuta passiva das portas irmas -----------------------------
        escuta = {"parar": None, "onde": ""}

        def escuta_ciclo(porta, ser, buf):
            if escuta["parar"] is not ser:
                return
            try:
                dados = ser.read(4096)
            except Exception as e:
                notify(f"ESCUTA: {porta} caiu -- {e}", tema.ALERTA)
                escuta_parar()
                return
            if dados:
                buf.extend(dados)
                if b"\n" in bytes(buf):
                    feitas, _, sobra = bytes(buf).rpartition(b"\n")
                    buf[:] = bytearray(sobra)
                    for crua in feitas.split(b"\n"):
                        txt = crua.decode("latin-1", "replace").strip()
                        if not txt:
                            continue
                        campos = (proto.parse_nmea(txt)
                                  or proto.parse_texto_gps(txt))
                        if not campos:
                            continue
                        if not escuta["onde"]:
                            escuta["onde"] = porta
                            notify(f"ESCUTA: {porta} está falando -- "
                                   "velocidade, proa e HDOP vêm daqui",
                                   tema.OK)
                        for nome, valor in campos.items():
                            if nome in moni:
                                moni[nome].set(valor)
                        if "_lat" in campos and "_lon" in campos:
                            set_pos(campos["_lat"], campos["_lon"])
            root.after(200, escuta_ciclo, porta, ser, buf)

        def escuta_parar(msg=None):
            ser = escuta["parar"]
            escuta["parar"] = None
            escuta["onde"] = ""
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
            escuta_btn.config(text="Escutar porta de telemetria")
            if msg:
                notify(msg, tema.ALERTA)

        def escuta_iniciar():
            if escuta["parar"] is not None:
                escuta_parar("ESCUTA: parada")
                return
            alvo = port_var.get().split()[0] if port_var.get() else ""
            irmas = portas_irmas(alvo)
            if not irmas:
                notify("ESCUTA: não achei outra porta COM deste mesmo módulo. "
                       "Só existe uma, então não há o que escutar.", tema.ALERTA)
                return
            import serial
            for porta in irmas:
                try:
                    ser = serial.Serial(porta, int(baud_var.get()), timeout=0.1)
                except Exception:
                    continue
                escuta["parar"] = ser
                escuta_btn.config(text="Parar escuta")
                notify(f"ESCUTA: ouvindo {porta} (irmãs: {', '.join(irmas)})",
                       tema.ACENTO)
                root.after(200, escuta_ciclo, porta, ser, bytearray())
                return
            notify(f"ESCUTA: nenhuma das irmãs abriu ({', '.join(irmas)}) -- "
                   "outro programa pode estar usando", tema.ERRO)

        mon_bar = ttk.Frame(mon_tab, padding=(0, 10, 0, 0))
        mon_bar.pack(fill="x")
        moni_on = [None]        # after() id of the running poll, None when stopped
        moni_mudo = [0]         # polls sent since the last status frame came back
        def moni_parar(msg="MONITOR: parado", cor=tema.ERRO):
            if moni_on[0] is not None:
                root.after_cancel(moni_on[0])
                moni_on[0] = None
                notify(msg, cor)
        def moni_ciclo(vez=0):
            """Alternate the two requests 400ms apart, so the system panel and the
            GPS panel each refresh a bit faster than once a second. The firmware
            answers requests and never streams, so asking is what keeps it live."""
            if not link.open:
                moni_parar("MONITOR: porta fechou", tema.ERRO)
                return
            op = proto.MSG_MONI_SYS if vez % 2 == 0 else proto.MSG_MONI_GPS
            if send_command(f"moni:{op:04X}") is False:
                moni_parar("MONITOR: falha ao enviar", tema.ERRO)
                return
            # The tracker sleeps after SLEEPT minutes and then answers nothing.
            # Say so, otherwise the panel just shows stale numbers forever.
            moni_mudo[0] += 1
            if moni_mudo[0] == 8:
                notify("MONITOR: rastreador nao responde -- provavelmente em "
                       "sleep. Mexa nele ou ligue a ignicao para acordar.", tema.ALERTA)
            moni_on[0] = root.after(400, moni_ciclo, vez + 1)

        def moni_iniciar():
            if not require_link() or moni_on[0] is not None:
                return
            moni_mudo[0] = 0
            notify("MONITOR: sistema e GPS atualizando -- Parar para encerrar", tema.OK)
            moni_ciclo()

        _topico(mon_bar, "MONITOR")
        ttk.Button(mon_bar, text="Iniciar", style="Outline.TButton",
                   command=moni_iniciar).pack(side="left", padx=2)
        ttk.Button(mon_bar, text="Parar", style="Ghost.TButton",
                   command=moni_parar).pack(side="left", padx=2)
        _divisor(mon_bar)
        _topico(mon_bar, "TELEMETRIA")
        escuta_btn = ttk.Button(mon_bar, text="Escutar porta de telemetria",
                                style="Ghost.TButton", command=escuta_iniciar)
        escuta_btn.pack(side="left", padx=2)
        ttk.Label(mon_bar, foreground=tema.TXT2,
                  text="sistema e GPS alternados, cada um ~1x por segundo"
                  ).pack(side="left", padx=10)
        con_tab = ttk.Frame(nb)
        nb.add(con_tab, text="Comandos livres")
        # Barra de ajuda: um botao que abre um guia do simples ao detalhado,
        # para quem chega sem saber o que digitar aqui.
        con_topo = tk.Frame(con_tab, bg=tema.BG)
        con_topo.pack(fill="x", padx=6, pady=(6, 0))
        tk.Label(con_topo, text="Console -- fale direto com o rastreador",
                 bg=tema.BG, fg=tema.TXT2, font=tema.F_BOLD).pack(side="left")

        def ajuda_console():
            win = tk.Toplevel(root)
            win.title("Como usar o console")
            win.configure(bg=tema.BG)
            cx = tk.Frame(win, bg=tema.CARD, padx=4, pady=4,
                          highlightbackground=tema.BORDA, highlightthickness=1)
            cx.pack(padx=12, pady=12, fill="both", expand=True)
            corpo = tk.Text(cx, width=72, height=22, wrap="word", relief="flat",
                            bg=tema.TERM, fg=tema.LOG_NEUTRO, font=tema.F_MONO,
                            padx=12, pady=10, insertwidth=0, cursor="arrow",
                            highlightthickness=0)
            rol = ttk.Scrollbar(cx, orient="vertical", command=corpo.yview)
            corpo.configure(yscrollcommand=rol.set)
            corpo.pack(side="left", fill="both", expand=True)
            rol.pack(side="right", fill="y")
            corpo.tag_configure("t", foreground=tema.ACENTO,
                                font=(tema.MONO, 10, "bold"), spacing1=12,
                                spacing3=6)
            corpo.tag_configure("c", foreground=tema.LOG_VAL)
            for n, (titulo, txt) in enumerate(ajuda.CONSOLE):
                corpo.insert("end", f"{n + 1}. {titulo}\n", "t")
                corpo.insert("end", txt + "\n\n", "c")
            corpo.configure(state="disabled")
            ttk.Button(cx, text="Fechar", style="Primary.TButton",
                       command=win.destroy).pack(side="bottom", anchor="e",
                                                 pady=(8, 0))
            win.bind("<Escape>", lambda _e: win.destroy())
            win.transient(root)
            win.grab_set()

        ttk.Button(con_topo, text="ⓘ  Como funciona", style="Outline.TButton",
                   command=ajuda_console).pack(side="right")
        log = tk.Text(con_tab, height=20, wrap="none", font=tema.F_MONO,
                      state="disabled", insertwidth=0, cursor="arrow",
                      bg=tema.TERM, fg=tema.LOG_NEUTRO, relief="flat",
                      padx=10, pady=8, selectbackground=tema.BORDA,
                      highlightthickness=1, highlightbackground=tema.BORDA)
        log.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        for nome, cor in (("tx", tema.LOG_TX), ("rx", tema.LOG_RX),
                          ("err", tema.LOG_ERR), ("val", tema.LOG_VAL),
                          ("hora", tema.LOG_HORA)):
            log.tag_configure(nome, foreground=cor)
        # Mirrors the vendor tool's equipment-control panel. Only Reset is
        # wired: PowerON and PowerOff do nothing observable there either, so
        # there is no working behavior to copy for them.
        equ_row = ttk.LabelFrame(con_tab, text="Controle do equipamento", padding=6)
        equ_row.pack(fill="x", pady=(6, 0))

        def do_reset():
            if not require_link():
                return
            if not messagebox.askyesno(
                    "J16 -- Reiniciar", "Reinicia o rastreador agora.\n\n"
                    "A configuração não se perde. O aparelho some da porta por "
                    "uns 10 segundos e volta sozinho.\n\nConfirma?",
                    icon="warning", default="no"):
                notify("RESET: cancelado", tema.ERRO)
                return
            moni_parar("")
            send_command(f"moni:{proto.MSG_RESET:04X}")
            notify("RESET: enviado -- o rastreador reinicia em ~10 s. Reconecte "
                   "depois se a porta cair.", tema.ALERTA)

        ttk.Button(equ_row, text="Reiniciar rastreador", style="Perigo.TButton",
                   command=do_reset).pack(side="left", padx=4)

        # Everything the tracker answers that is not "set a field", pinned as a
        # panel instead of a popup: the tech reads the whole list at once and the
        # buttons stay put between clicks.
        acoes_pane = ttk.LabelFrame(
            con_tab, padding=6,
            text="Comandos prontos -- consultas e controles, nenhum altera campo")

        def disparar(texto, rotulo):
            cmd_var.set(texto)
            on_send()
            notify(f"COMANDO PRONTO: {rotulo}", tema.OK)

        # Two columns: in one column the list runs past the bottom of the tab
        # and the last commands cannot be reached -- the panel does not scroll.
        metade = (len(ACOES) + 1) // 2
        for n, (rotulo, texto, dica) in enumerate(ACOES):
            alvo = (do_reset if texto == f"moni:{proto.MSG_RESET:04X}"
                    else lambda t=texto, r=rotulo: disparar(t, r))
            lin, col = n % metade, (n // metade) * 2
            ttk.Button(acoes_pane, text=rotulo, width=26, command=alvo,
                       style="Cmd.TButton"
                       ).grid(row=lin, column=col, sticky="ew", pady=2, padx=(0, 4))
            ttk.Label(acoes_pane, text=dica, style="CardDica.TLabel",
                      wraplength=250
                      ).grid(row=lin, column=col + 1, sticky="w", padx=(8, 16))

        def alterna_acoes():
            # winfo_manager, not winfo_ismapped: an unselected notebook tab maps
            # nothing, so ismapped would report "hidden" for a panel that is up
            if acoes_pane.winfo_manager():
                acoes_pane.pack_forget()
                log.configure(height=20)
                acoes_btn.config(text="Comandos prontos ▾")
            else:
                # the log expands and would squeeze the panel off the bottom
                log.configure(height=6)
                acoes_pane.pack(fill="x", padx=4, pady=(4, 0), after=equ_row)
                acoes_btn.config(text="Comandos prontos ▴")

        acoes_btn = ttk.Button(equ_row, text="Comandos prontos ▾",
                               style="Outline.TButton", command=alterna_acoes)
        acoes_btn.pack(side="left", padx=4)
        ttk.Label(equ_row, style="CardDica.TLabel", wraplength=430,
                  justify="left",
                  text="PowerON e PowerOff não existem: no próprio ComTools esses "
                       "dois botões estão sem função ligada."
                  ).pack(side="left", padx=10)
        entry_row = ttk.Frame(con_tab)
        entry_row.pack(fill="x", pady=4)
        cmd_var = tk.StringVar()
        cmd_entry = ttk.Entry(entry_row, textvariable=cmd_var)
        cmd_entry.pack(side="left", fill="x", expand=True)
        # A porta USB so fala ATYS. Isso fica escrito na tela porque a duvida
        # ja apareceu: "mandei PARAM# e nao voltou nada".
        ttk.Label(con_tab, foreground=tema.TXT2, justify="left",
                  text="Formatos:  #FREQ (ler)   #FREQ=60 (gravar)   "
                       "SZCS#APN=x.br / CXCS#APN (fabricante)   moni:0100 "
                       "(opcode)   hex:59 53 ...   —   dúvida? use o "
                       "botão ⓘ Como funciona."
                  ).pack(anchor="w", padx=4, pady=(2, 0))
        ttk.Label(con_tab, foreground=tema.TXT3, justify="left", wraplength=820,
                  text="Nada é bloqueado aqui: PARAM#, STATUS#, RELAY,1# e "
                       "outros comandos de SMS/plataforma podem ser digitados "
                       "e são enviados -- só que esta porta USB "
                       "geralmente não responde a eles (fica anotado no "
                       "histórico). FACTORY# pede confirmação "
                       "por apagar tudo."
                  ).pack(anchor="w", padx=4)
        show_raw = tk.BooleanVar(value=False)
        ttk.Checkbutton(entry_row, text="mostrar frame cru", variable=show_raw
                        ).pack(side="right", padx=6)
        # Last value seen for each key, so a write can be logged as old -> new.
        last_values = {}
        def cor_da_linha(txt):
            """Cor pelo tipo da linha, como um terminal de verdade: azul o que
            sai, verde o que volta, vermelho o que falhou."""
            t = txt.lstrip()
            if t.startswith("TX"):
                return "tx"
            if t.startswith("RX"):
                return "rx"
            if t.startswith(("ERRO", "nao enviado", "FALHA", "BLOQUEADO")):
                return "err"
            return "val" if txt.startswith(" ") else ""

        def write_log(line, tag=None):
            log.config(state="normal")          # log is read-only for the user;
            log.insert("end", f"{datetime.datetime.now():%H:%M:%S}  ", "hora")
            log.insert("end", f"{line}\n", tag or cor_da_linha(line))
            log.see("end")
            log.config(state="disabled")        # flip back so no caret, no typing
        def notify(text, color=None):
            """Every button says out loud that it fired and how it ended -- on the
            bar (visible from the Parametros tab) and in the console log.

            Vira um banner: faixa colorida a esquerda, icone e fundo tingido,
            no lugar do paragrafo vermelho solto que era antes."""
            cor = color or tema.ACENTO
            icone = {tema.ERRO: "\u2716", tema.ALERTA: "\u26a0",
                     tema.OK: "\u2714"}.get(cor, "\u2139")
            fundo = _tingir(cor)
            banner.configure(bg=fundo)
            faixa_banner.configure(bg=cor)
            icone_lbl.configure(text=icone, fg=cor, bg=fundo)
            action_lbl.configure(text=text, fg=cor, bg=fundo)
            write_log(text, {tema.ERRO: "err", tema.OK: "rx",
                             tema.ALERTA: "err"}.get(cor))
        def require_link():
            """One warning, not one per command -- callers loop over many commands."""
            if link.open:
                return True
            notify("porta desconectada -- conecte primeiro", tema.ERRO)
            messagebox.showwarning("J16", "Conecte a porta primeiro.")
            return False
        def send_command(text):
            """A '=' anywhere in the text makes it a write; otherwise it is a read.
            Returns False if the write to the port failed, so a batch can stop
            instead of throwing a Tk callback exception on every remaining item.
            """
            if not link.open:
                return False
            if text.lower().startswith("moni:"):
                # bare opcode, no payload: status requests and the reset
                op = int(text[5:], 16)
                if op in proto.MSG_PERIGOSO:
                    notify(f"BLOQUEADO: opcode 0x{op:04X} apaga a configuracao "
                           "do servidor", tema.ERRO)
                    return False
                payload = proto.encode(b"", op, link.next_seq())
                if op == proto.MSG_RESET:
                    write_log("TX  [reset] opcode 0x0300")
            elif text.lower().startswith("hex:"):
                payload = bytes.fromhex(text[4:].replace(",", " "))
                write_log(f"TX  (bytes crus)  {hexdump(payload)}")
            elif normalizar_comando(text)[0]:
                # '#KEY' / '#KEY=v' -> the ATYS binary config protocol. Tambem
                # entra aqui 'SZCS#KEY=v', 'CXCS#KEY' e a chave pelada.
                original, text = text, normalizar_comando(text)[0]
                forcar = normalizar_comando(original)[1]
                if original.strip() != text:
                    write_log(f"    {original.strip()}  ->  {text}")
                write = "=" in text if forcar is None else forcar == "gravar"
                mtype = proto.MSG_WRITE if write else proto.MSG_READ
                payload = proto.encode(text, mtype, link.next_seq())
                kind = "gravar" if write else "ler"
                write_log(f"TX  [{kind}] {text}")
                if write:
                    # so the reply can be read as a change, not just a value
                    for key, new in proto.parse_values(text.lstrip("#")).items():
                        old = last_values.get(key)
                        write_log(f"      {key}: {old if old else '?'} -> {new} (pedido)")
                if show_raw.get():
                    write_log(f"      frame  {payload.decode('latin-1').strip()}")
            else:
                # Console livre: NADA e bloqueado por nao ter botao. O usuario
                # pode digitar qualquer comando; so FACTORY, que apaga tudo,
                # ainda pede confirmacao por ser irreversivel.
                cmd = "".join(c for c in text if 32 <= ord(c) < 127).strip()
                base = cmd.upper().rstrip("#").split(",")[0]
                if base == "FACTORY":
                    if not messagebox.askyesno(
                            "J16 -- FACTORY", "FACTORY apaga TODA a configuração "
                            "do rastreador e nao tem volta.\n\nEnviar mesmo "
                            "assim?", icon="warning", default="no"):
                        notify("FACTORY: cancelado", tema.ALERTA)
                        return False
                cru = cmd.upper().replace("0X", "").replace(" ", "")
                if len(cru) == 4 and all(c in "0123456789ABCDEF" for c in cru):
                    # parece opcode digitado solto -- avisa o jeito certo, mas
                    # manda assim mesmo como texto, ja que o console e livre
                    notify(f"{cmd}: enviando como texto.{dica_hex(cru)}",
                           tema.ALERTA)
                payload = (cmd + "\r\n").encode("latin-1", "replace")
                write_log(f"TX  (texto) {cmd}")
                if classificar_recusa(cmd) == "sms":
                    write_log("      obs: comando de SMS/plataforma -- esta porta "
                              "USB costuma nao responder (testado CR/LF/CRLF)")
            try:
                link.send(payload)
            except Exception as e:
                # Leaving a timed-out port open is what turns one write timeout
                # into "Acesso negado" on the next Conectar: Windows still holds
                # the old handle. Drop it here and say the port is down.
                moni_parar("")
                try:
                    link.close()
                except Exception:
                    pass
                conn_btn.config(text="Conectar", style="Outline.TButton")
                status.set("DESCONECTADO", tema.ERRO)
                notify(f"falha ao enviar pra porta -- {e}. A porta foi fechada; "
                       "espere uns 2s e clique Conectar.", tema.ERRO)
                return False
            return True
        def on_send(_=None):
            text = cmd_var.get().strip()
            if not (text and require_link()):
                return
            if send_command(text) is not False:
                notify(f"COMANDO: {text} enviado -- resposta no historico acima")
            cmd_var.set("")
        cmd_entry.bind("<Return>", on_send)
        ttk.Button(entry_row, text="Enviar", command=on_send).pack(side="left", padx=4)
        def route_key(e):
            """Type anywhere and the free-command box grabs it -- unless a real
            editable field already has focus. Ctrl/Alt combos and navigation keys
            (Tab, Esc, arrows, F-keys) keep their native behaviour."""
            w = root.focus_get()
            if w is cmd_entry or w is None:
                return
            if e.state & 0x0004 or e.state & 0x20000:      # Ctrl / Alt held
                return
            apagar = e.keysym in ("BackSpace", "Delete")
            if not apagar and (not e.char or len(e.char) != 1
                               or not e.char.isprintable()):
                return
            try:
                if isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry, tk.Spinbox)) \
                   and str(w.cget("state")) in ("normal", "active", ""):
                    return                                 # let the field type
            except tk.TclError:
                pass
            cmd_entry.focus_set()
            i = cmd_entry.index("insert")
            if not apagar:
                cmd_entry.insert(i, e.char)
            elif e.keysym == "BackSpace":
                if i > 0:
                    cmd_entry.delete(i - 1)
            elif i < len(cmd_var.get()):
                cmd_entry.delete(i)
            return "break"
        pai.bind_all("<Key>", route_key, add="+")
        # --- actions ------------------------------------------------------------
        def selected():
            return [c for c, (chk, _) in rows.items() if chk.get()]
        def selected_cfg():
            """Ticked rows minus the identity ones -- those are readable but never
            written, exported or copied, however the user ticks them."""
            return [c for c in selected() if c not in SOMENTE_LEITURA]
        def paced(items, make_text, start_msg, done_msg, passo=BATCH, espera=250):
            """Walk a list through the event loop; a plain sleep would freeze the UI
            for the whole run and starve the reply reader.

            Sending is not the same as being heard: the tracker sleeps after
            SLEEPT minutes and then ignores everything. Count the replies and say
            so, otherwise an empty table looks like a working one."""
            notify(start_msg)
            antes = recebidos[0]

            def confere():
                if recebidos[0] == antes:
                    notify("SEM RESPOSTA: o rastreador nao devolveu nada -- ele "
                           "dorme sozinho depois de alguns minutos parado. Mexa "
                           "nele ou ligue a ignicao e tente de novo.", tema.ERRO)
                else:
                    notify(f"{done_msg} ({recebidos[0] - antes} valores recebidos)",
                           tema.OK)

            def step(i=0):
                if not link.open:
                    notify("porta fechou no meio da operacao", tema.ERRO)
                    return
                if i >= len(items):
                    root.after(1500, confere)     # let the last replies land
                    return
                if send_command(make_text(items[i:i + passo])) is False:
                    return          # send_command already said why on the bar
                root.after(espera, step, i + passo)
            step()
        def do_read():
            """Pull the tracker's current config. Checked rows only, or all of them."""
            if not require_link():
                return
            marcados = selected()
            targets = list(marcados or ALL_COMMANDS)
            escopo = "marcados" if marcados else "todos"
            paced(targets, lambda batch: "".join(f"#{k}" for k in batch),
                  f"LER: pedindo {len(targets)} parametros ({escopo})...",
                  f"LER: {len(targets)} pedidos enviados -- respostas abaixo")
        def do_read_all():
            """Auto-read fired once on connect -- ignores ticks, reads everything."""
            if not link.open:
                return
            paced(ALL_COMMANDS, lambda batch: "".join(f"#{k}" for k in batch),
                  f"AUTO-LEITURA: puxando os {len(ALL_COMMANDS)} parametros...",
                  f"AUTO-LEITURA: {len(ALL_COMMANDS)} pedidos enviados")
        def do_write():
            """Send what is on screen: checked rows, or every row that has a value."""
            if not require_link():
                return
            sel = selected_cfg() or [c for c, (_, v) in rows.items()
                                     if v.get().strip() and c not in SOMENTE_LEITURA]
            if not sel:
                notify("ENVIAR: nenhum parametro preenchido", tema.ERRO)
                messagebox.showinfo("J16", "Nenhum parametro preenchido para enviar.")
                return
            pairs = [(c, rows[c][1].get().strip()) for c in sel]
            fazer_backup(len(pairs))
            # ponytail: one key per frame on writes. BATCH=6 was measured on
            # reads, where the line is just "#KEY#KEY..."; six writes carry their
            # values too and the firmware stops reading mid-line -- that is the
            # "Write timeout" right after Importar, with the port dead after it.
            paced(pairs, lambda batch: "".join(f"#{k}={v}" for k, v in batch),
                  "ENVIAR: gravando " + ", ".join(f"{k}={v}" for k, v in pairs[:4])
                  + (f" e mais {len(pairs) - 4}..." if len(pairs) > 4 else "..."),
                  f"ENVIAR: {len(pairs)} gravacoes enviadas -- confira os (confirmado)",
                  passo=1, espera=400)
        def fazer_backup(quantos):
            """Foto do que o rastreador tem AGORA, gravada antes de qualquer
            escrita. Guarda o que foi lido do aparelho (last_values), nao o que
            esta na tela: para desfazer, o que vale e o estado anterior dele.

            Sem valor lido ainda, salva a tela mesmo e diz isso no nome, senao
            o tecnico acha que tem ponto de retorno e nao tem.
            """
            pasta = pasta_backup()
            if pasta is None:
                notify("BACKUP: nao consegui criar a pasta -- gravando assim "
                       "mesmo, sem ponto de retorno", tema.ALERTA)
                return
            do_aparelho = {k: limpo_ascii(v) for k, v in last_values.items()
                           if v and k not in SOMENTE_LEITURA}
            if do_aparelho:
                valores, origem = do_aparelho, "lido do rastreador"
            else:
                valores = {c: limpo_ascii(v.get())
                           for c, (_, v) in rows.items()
                           if v.get().strip() and c not in SOMENTE_LEITURA}
                origem = "SO DA TELA -- nada foi lido do rastreador ainda"
            caminho = os.path.join(pasta, nome_backup())
            try:
                escrever_ini(caminho, valores)
            except OSError as e:
                notify(f"BACKUP: falhou -- {e}. Gravando assim mesmo.",
                       tema.ALERTA)
                return
            write_log(f"    backup ({origem}): {caminho}")
            notify(f"BACKUP: {len(valores)} parametros salvos em "
                   f"{os.path.basename(caminho)} antes de gravar {quantos}",
                   tema.ACENTO)

        def do_export():
            notify("EXPORTAR: escolha onde salvar...")
            path = filedialog.asksaveasfilename(defaultextension=".ini",
                                                filetypes=[("Config J16", "*.ini")])
            if not path:
                notify("EXPORTAR: cancelado", tema.ERRO)
                return
            values = {c: limpo_ascii(v.get()) for c, (_, v) in rows.items()
                      if v.get().strip() and c not in SOMENTE_LEITURA}
            try:
                escrever_ini(path, values)
            except OSError as e:
                notify(f"EXPORTAR: falhou -- {e}", tema.ERRO)
                messagebox.showerror("J16", f"Nao salvou o arquivo:\n{e}")
                return
            notify(f"EXPORTAR: {len(values)} parametros salvos em {path}", tema.OK)
        def do_import():
            notify("IMPORTAR: escolha o arquivo...")
            path = filedialog.askopenfilename(
                filetypes=[("Configuracoes J16", "*.ini *.txt"), ("Todos", "*.*")])
            if not path:
                notify("IMPORTAR: cancelado", tema.ERRO)
                return
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    items, descartadas = parse_kv(f.read())
            except OSError as e:
                notify(f"IMPORTAR: nao consegui abrir -- {e}", tema.ERRO)
                messagebox.showerror("J16", f"Nao consegui ler o arquivo:\n{e}")
                return
            if not items:
                notify("IMPORTAR: nenhuma linha CHAVE=VALOR reconhecida", tema.ERRO)
                messagebox.showerror(
                    "J16", "O arquivo nao tem linhas no formato CHAVE=VALOR.")
                return
            # The file becomes the selection: leftover ticks from a previous
            # read would ride along and get written too, and nobody asked for
            # those. Clear first, then tick exactly what the file brought.
            marcar(False)
            aplicados, ignorados, protegidos, suspeitos = [], [], [], []
            for cmd, value in items.items():
                key = cmd.upper()
                if key in SOMENTE_LEITURA:
                    protegidos.append(key)
                    continue
                if key not in rows:
                    ignorados.append(key)
                    continue
                if valor_suspeito(value):
                    suspeitos.append(f"{key}={value!r}")
                    continue
                antes = rows[key][1].get()
                rows[key][1].set(value)
                rows[key][0].set(True)
                aplicados.append(key)
                write_log(f"      {key}: {antes or '(vazio)'} -> {value}")
            resumo = (f"IMPORTAR: {len(aplicados)} parametros na tela"
                      + (f", {len(ignorados)} desconhecidos ignorados" if ignorados else "")
                      + (f", {len(protegidos)} de identificacao preservados" if protegidos else "")
                      + (f", {descartadas} linhas fora do padrao" if descartadas else ""))
            if suspeitos:
                # conferido e reprovado -- fica na tela para o tecnico olhar,
                # mas nada e enviado sozinho
                notify(resumo + f", {len(suspeitos)} valores suspeitos -- NAO enviei",
                       tema.ERRO)
                messagebox.showwarning(
                    "J16 -- importar",
                    "O arquivo tem valores que nao parecem validos, entao nada "
                    "foi enviado:\n\n"
                    + "\n".join(suspeitos[:10])
                    + "\n\nCorrija o arquivo, ou ajuste na tela e clique "
                      "Enviar parametros.")
                return
            if not aplicados:
                notify(resumo + " -- nada para enviar", tema.ERRO)
                return
            if not link.open:
                notify(resumo + " -- conecte a porta e clique Enviar parametros",
                       tema.ALERTA)
                return
            notify(resumo + " -- arquivo conferido, gravando...", tema.OK)
            do_write()
        def do_copy(com_nome):
            """Marked rows, or every filled row when nothing is marked. Identity
            fields have no checkbox so they only ride along in the 'all' case --
            leave them out, same as export does."""
            # copying is harmless, so a tick means "copy exactly this" even for the
            # identity rows; only the empty-selection fallback skips them
            alvo = selected() or [c for c in ALL_COMMANDS
                                  if c not in SOMENTE_LEITURA]
            linhas = []
            for c in alvo:
                v = rows[c][1].get().strip()
                if v:
                    linhas.append(f"{c}={v}" if com_nome else v)
            if not linhas:
                notify("COPIAR: nenhum campo preenchido", tema.ERRO)
                return
            root.clipboard_clear()
            root.clipboard_append("\n".join(linhas))
            notify(f"COPIAR: {len(linhas)} campos no clipboard "
                   f"({'nome=valor' if com_nome else 'so valores'})", tema.OK)
        def copy_menu():
            m = tk.Menu(root, tearoff=0)
            m.add_command(label="Copiar apenas valores",
                          command=lambda: do_copy(False))
            m.add_command(label="Copiar com nome dos campos",
                          command=lambda: do_copy(True))
            m.update_idletasks()      # so reqheight is real -> menu opens upward
            m.tk_popup(copy_btn.winfo_rootx(),
                       copy_btn.winfo_rooty() - m.winfo_reqheight())
        def toggle_conn():
            if link.open:
                link.close()
                conn_btn.config(text="Conectar", style="Outline.TButton")
                status.set("DESCONECTADO", tema.ERRO)
                notify("Porta fechada", tema.ERRO)
                refresh_ports()
                return
            try:
                link.connect(port_var.get().split()[0], baud_var.get())
            except Exception as e:
                notify(f"Não abriu a porta -- {e}", tema.ERRO)
                messagebox.showerror("J16", f"Não abriu a porta:\n{e}")
                set_conn_style(False)
                return
            conn_btn.config(text="Desconectar", style="TButton")
            set_conn_style(False)
            status.set("CONECTADO  " + port_var.get().split()[0], tema.OK)
            notify(f"Conectado em {port_var.get().split()[0]} @ {baud_var.get()} "
                   "-- lendo os parâmetros e ligando o monitor", tema.OK)
            # one full read per connection, so the screen shows the real device
            root.after(300, do_read_all)
            # e o monitor sobe sozinho: ninguem conecta um rastreador para NAO
            # ver o que ele esta fazendo. O botao continua la para parar.
            root.after(1200, moni_iniciar)
        def set_conn_style(ready):
            conn_btn.config(style="Primary.TButton" if ready else "Outline.TButton",
                            cursor="hand2" if ready else "")
        def refresh_ports():
            """Rescan and claim this panel's own tracker: panel 0 takes the first
            device found, panel 1 the second, so two panels never fight over one
            port. Nothing to claim -> neutral button and a manual choice."""
            achados = detect_devices()      # already one entry per physical tracker
            listados = achados + [p for p in ports() if p not in achados]
            port_cb.config(values=listados or ports())
            if link.open:
                return
            if len(achados) > indice:
                port_var.set(achados[indice])
                set_conn_style(True)
                notify(f"Rastreador {indice + 1} em "
                       f"{achados[indice].split()[0]} -- clique Conectar", tema.OK)
            elif not listados:
                # No COM port at all in the system. On a fresh machine that is
                # almost always the missing USB driver, not a missing tracker --
                # saying so beats "0 detectado(s)", which sends the tech hunting
                # the cable.
                set_conn_style(False)
                notify("Nenhuma porta COM no sistema -- se o rastreador está "
                       "plugado, falta o driver USB. Veja a pasta Drivers "
                       "(leia o README)", tema.ERRO)
            else:
                set_conn_style(False)
                notify(f"Nenhum rastreador livre para este painel "
                       f"({len(achados)} detectado(s) de {len(listados)} porta(s))",
                       tema.ALERTA)
        conn_btn.config(command=toggle_conn)
        bar = ttk.Frame(rodape_painel, padding=(6, 8))
        # Hierarquia: gravar e a acao principal, ler e secundaria, arquivo e
        # discreto. Assim o tecnico acha o botao certo sem ler os cinco.
        # Dois assuntos diferentes: o que fala com o rastreador e o que mexe
        # em arquivo. Separados, ninguem exporta querendo gravar.
        _topico(bar, "RASTREADOR")
        ttk.Button(bar, text="Enviar", style="Primary.TButton",
                   command=do_write).pack(side="left")
        ttk.Button(bar, text="Ler", style="Outline.TButton",
                   command=do_read).pack(side="left", padx=6)
        _divisor(bar)
        _topico(bar, "ARQUIVO")
        ttk.Button(bar, text="Importar", style="Ghost.TButton",
                   command=do_import).pack(side="left", padx=2)
        ttk.Button(bar, text="Exportar", style="Ghost.TButton",
                   command=do_export).pack(side="left", padx=2)
        copy_btn = ttk.Button(bar, text="Copiar ▴", style="Ghost.TButton",
                              command=copy_menu)
        copy_btn.pack(side="left", padx=2)
        def limpar_log():
            log.config(state="normal")
            log.delete("1.0", "end")
            log.config(state="disabled")
        ttk.Button(bar, text="Limpar log", style="Ghost.TButton",
                   command=limpar_log).pack(side="right")
        marca_rodape = tk.Label(bar, text=ASSINATURA, bg=tema.BG,
                                fg=cor_marca(tema.BG), font=(tema.FONTE, 8))
        marca_rodape.pack(side="right", padx=14)
        marcas.append(marca_rodape)
        # Status of the last action, always visible -- the console log is on another
        # tab, so a click made from the Parametros tab would otherwise look ignored.
        def _tingir(cor, alfa=0.13):
            """Sem canal alfa no tk: mistura a cor com o fundo da janela."""
            c = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
            f = tuple(int(tema.BG[i:i + 2], 16) for i in (1, 3, 5))
            return "#%02x%02x%02x" % tuple(
                int(c[i] * alfa + f[i] * (1 - alfa)) for i in range(3))

        banner = tk.Frame(rodape_painel, bg=_tingir(tema.ACENTO))
        # Barra de botoes em cima, banner de aviso embaixo, ambos dentro do
        # holder que ja esta ancorado no fundo -- nada de reempacotar.
        bar.pack(fill="x")
        banner.pack(fill="x", padx=6, pady=(4, 6))
        faixa_banner = tk.Frame(banner, bg=tema.ACENTO, width=3)
        faixa_banner.pack(side="left", fill="y")
        icone_lbl = tk.Label(banner, text="\u2139", fg=tema.ACENTO,
                             bg=_tingir(tema.ACENTO), font=tema.F_BOLD,
                             padx=8, pady=6)
        icone_lbl.pack(side="left")
        action_lbl = tk.Label(banner, text="pronto", anchor="w", justify="left",
                              fg=tema.ACENTO, bg=_tingir(tema.ACENTO),
                              font=tema.F_TXT, pady=6)
        action_lbl.pack(side="left", fill="x", expand=True)
        # --- background reader --------------------------------------------------
        def reader():
            while True:
                if link.open:
                    try:
                        data = link.read_any()
                    except Exception as e:
                        # A reset makes the device drop off USB mid-read. Report
                        # it once and hang up, instead of looping on a port that
                        # no longer exists.
                        rx_q.put(("caiu", str(e)))
                        time.sleep(0.5)
                        continue
                    if data:
                        rx_q.put(("rx", data))
                time.sleep(0.05)
        threading.Thread(target=reader, daemon=True).start()
        pending = bytearray()
        texto_solto = bytearray()   # linhas de texto que o decode pulou
        recebidos = [0]      # boxed so drain() can bump it without a nonlocal
        txt_idle = [0]       # drain passes the text buffer sat unchanged
        def flush_text(force=False):
            """Anything in `pending` that is not an ATYS frame is a plain-text reply
            (PARAM#, STATUS#, VERSION# ...). Print it line by line once a line is
            complete, or after ~1s of silence so a tail with no newline still shows.
            """
            if not pending or proto.MARKER in pending:
                return
            blob = pending.decode("latin-1", "replace")
            if not (force or "\n" in blob or "\r" in blob or txt_idle[0] >= 12):
                return
            for ln in blob.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                if ln.strip():
                    write_log(f"RX  (texto) {ln.strip()}")
            pending.clear()
            txt_idle[0] = 0
        def drain():
            before = bytes(pending)
            while not rx_q.empty():
                kind, payload = rx_q.get()
                if kind == "caiu":
                    # the port vanished under us -- almost always a reset
                    moni_parar("")
                    try:
                        link.close()
                    except Exception:
                        pass
                    conn_btn.config(text="Conectar", style="Outline.TButton")
                    status.set("DESCONECTADO", tema.ERRO)
                    notify("A porta caiu -- normal logo depois de um Reset. "
                           "Espere o rastreador voltar e clique Conectar.", tema.ALERTA)
                    refresh_ports()
                    continue
                if kind == "err":
                    write_log(f"ERRO  {payload}")
                    continue
                pending.extend(payload)
                # O decode pula tudo que nao for quadro ATYS. Com o monitor
                # ligado sempre vem um quadro logo depois, entao qualquer linha
                # de texto era comida ali dentro. Agora ela sai pelo descarte.
                descarte = bytearray()
                frames, rest = proto.decode(bytes(pending), descarte)
                pending[:] = rest
                if descarte:
                    texto_solto.extend(descarte)
                # O decode so entende quadros ATYS e descarta o resto. Mas o
                # modulo tambem cospe linhas de texto de posicao -- e e delas
                # que saem velocidade, proa e HDOP, exatamente como no ComTools.
                # Jogar fora era o motivo de esses campos ficarem vazios aqui.
                if b"\n" in bytes(pending):
                    feitas, _, sobra = bytes(pending).rpartition(b"\n")
                    pending[:] = bytearray(sobra)
                    texto_solto.extend(feitas + b"\n")
                if b"\n" in bytes(texto_solto):
                    feitas, _, sobra = bytes(texto_solto).rpartition(b"\n")
                    texto_solto[:] = bytearray(sobra[-512:])
                    for crua in feitas.replace(b"\r", b"\n").split(b"\n"):
                        txt = crua.decode("latin-1", "replace").strip()
                        if not txt:
                            continue
                        campos = proto.parse_texto_gps(txt)
                        if not campos:
                            write_log(f"RX  (texto) {txt}")
                            continue
                        write_log(f"RX  (posicao em texto) {txt}")
                        for nome, valor in campos.items():
                            if nome in moni:
                                moni[nome].set(valor)
                        if "_lat" in campos and "_lon" in campos:
                            set_pos(campos["_lat"], campos["_lon"])
                for mtype, seq, text in frames:
                    if mtype in (proto.ACK_MONI_SYS, proto.ACK_MONI_GPS):
                        campos = (proto.parse_moni_sys(text)
                                  if mtype == proto.ACK_MONI_SYS
                                  else proto.parse_moni_gps(text))
                        if moni_mudo[0] >= 8:
                            notify("MONITOR: rastreador acordou", tema.OK)
                        moni_mudo[0] = 0
                        for nome, valor in campos.items():
                            if nome in moni:
                                moni[nome].set(valor)
                        if mtype == proto.ACK_MONI_GPS:
                            set_pos(campos.get("_lat"), campos.get("_lon"))
                        continue          # one line per second would drown the log
                    if isinstance(text, (bytes, bytearray)):
                        # any other binary reply -- parse_values only speaks str,
                        # so raw bytes must never reach it
                        rotulo = {proto.ACK_UNSUPPORTED: "opcode nao suportado",
                                  proto.ACK_OK0: "aceito",
                                  proto.ACK_OK1: "aceito"}.get(
                                      mtype, proto.EVENTOS.get(mtype, "binario"))
                        write_log(f"RX  [0x{mtype:04X}] {rotulo}: {text.hex(' ')}")
                        if mtype == proto.ACK_COLISAO_GET:
                            for nome, valor in proto.parse_colisao(text).items():
                                write_log(f"      {nome} = {valor}")
                        continue
                    what = {proto.ACK_READ: "leitura",
                            proto.ACK_WRITE: "gravacao"}.get(mtype, f"0x{mtype:04X}")
                    write_log(f"RX  [{what}] {text or '(vazio)'}")
                    for key, value in proto.parse_values(text).items():
                        old = last_values.get(key)
                        if old is None or old == value:
                            write_log(f"      {key} = {value}")
                        else:
                            write_log(f"      {key}: {old} -> {value}  (confirmado)")
                        last_values[key] = value
                        recebidos[0] += 1
                        if key in rows:
                            rows[key][1].set(value)
                            marca_sujo(key)
                    # counter only -- notify() would flood the log with one line per frame
                    action_lbl.config(
                        text=f"resposta do rastreador: {recebidos[0]} valores "
                             f"recebidos (último: {text[:60]})", fg=tema.OK)
            txt_idle[0] = txt_idle[0] + 1 if bytes(pending) == before else 0
            flush_text()
            root.after(80, drain)

        root.after(80, drain)
        refresh_ports()          # after action_lbl exists, so notify() can draw
        return SimpleNamespace(link=link, rows=rows, notify=notify,
                               refresh=refresh_ports, indice=indice,
                               moni_parar=moni_parar, enviar=send_command)

    # One panel per tracker found, two at most -- past that the columns get too
    # narrow to read and the table is the whole point.
    quantos = max(1, min(2, len(detect_devices())))
    for i in range(quantos):
        painel = ttk.Frame(paned)
        paned.add(painel, weight=1)
        paineis.append(montar_painel(painel, i))

    def clonar(origem, destino):
        """Copy one tracker's settings onto the other panel's screen. Nothing is
        written to the device -- the tech reviews the values, then hits Enviar."""
        if len(paineis) < 2:
            return
        a, b = paineis[origem], paineis[destino]
        copiados = 0
        for cmd, (_, val) in a.rows.items():
            v = val.get().strip()
            if v and cmd not in SOMENTE_LEITURA:
                b.rows[cmd][1].set(v)
                b.rows[cmd][0].set(True)
                copiados += 1
        letra = "AB"
        b.notify(f"CLONAR: {copiados} parametros vieram do painel {letra[origem]}"
                 " -- confira e clique Enviar parametros", tema.OK)

    rodape = ttk.Frame(root, padding=(8, 4))
    rodape.pack(fill="x")
    if len(paineis) > 1:
        ttk.Button(rodape, text="Copiar  A → B",
                   command=lambda: clonar(0, 1)).pack(side="left", padx=4)
        ttk.Button(rodape, text="Copiar  B → A",
                   command=lambda: clonar(1, 0)).pack(side="left", padx=4)
        ttk.Label(rodape, foreground=tema.TXT2,
                  text="clona a configuracao de um painel no outro (so na tela)"
                  ).pack(side="left", padx=10)
    else:
        ttk.Label(rodape, foreground=tema.TXT2,
                  text="Um rastreador detectado. Plugue um segundo e reabra o "
                       "programa para configurar os dois lado a lado."
                  ).pack(side="left")

    def on_close():
        # always hand every COM port back to the OS, however the window closes
        for p in paineis:
            try:
                p.moni_parar()
                p.link.close()
            except Exception:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        for p in paineis:
            try:
                p.link.close()
            except Exception:
                pass


def selftest():
    proto.selftest()
    tema.selftest()
    ajuda.selftest()
    assert len(ALL_COMMANDS) == len(set(ALL_COMMANDS)), "comando duplicado"
    assert proto.read_frame(["FREQ", "APN"]) == \
        proto.encode("#FREQ#APN", proto.MSG_READ)
    assert hexdump(b"AB") == "41 42  |AB|"
    # identity rows must never leak into a write or a file
    assert SOMENTE_LEITURA <= set(ALL_COMMANDS)
    assert "IMEI" in SOMENTE_LEITURA and "FREQ" not in SOMENTE_LEITURA
    # a .txt of the colleague's notes must parse like an .ini
    pares, _ = parse_kv("SZCS#FREQ=15#PULSE=15  //nota\n[secao]\nAPN=x.br\n")
    assert pares == {"FREQ": "15", "PULSE": "15", "APN": "x.br"}, pares
    assert len(MONI_ESTADOS) == 27

    # cloning one panel onto another carries settings but never identity
    origem = {"FREQ": "15", "APN": "x.br", "IMEI": "8626", "SPEED": ""}
    destino = {k: "" for k in origem}
    for k, v in origem.items():
        if v.strip() and k not in SOMENTE_LEITURA:
            destino[k] = v
    assert destino == {"FREQ": "15", "APN": "x.br", "IMEI": "", "SPEED": ""}, destino

    # the friendlier widgets must still describe real parameters
    assert LIGA_DESLIGA <= set(ALL_COMMANDS), LIGA_DESLIGA - set(ALL_COMMANDS)
    assert set(ESCOLHAS) <= set(ALL_COMMANDS), set(ESCOLHAS) - set(ALL_COMMANDS)
    assert not (LIGA_DESLIGA & set(ESCOLHAS)), "parametro em dois formatos"
    # a ready-made action must be something send_command can actually parse,
    # and must never be one of the opcodes that cut power or wipe the server
    for _rot, texto, _d in ACOES:
        assert texto.startswith(("#", "moni:")), texto
        if texto.startswith("moni:"):
            assert int(texto[5:], 16) not in proto.MSG_PERIGOSO, texto
        else:
            assert all(k in ALL_COMMANDS for k in texto.lstrip("#").split("#")), texto
    # every group heading has its one-line explanation
    assert set(GRUPO_AJUDA) == set(COMMANDS), set(GRUPO_AJUDA) ^ set(COMMANDS)
    assert GRUPO_INFO in COMMANDS
    # "marcar todos" must never arm an identity row
    marcaveis = [c for c in ALL_COMMANDS
                 if c not in SOMENTE_LEITURA and GRUPO_DE[c] != GRUPO_INFO]
    assert not (set(marcaveis) & SOMENTE_LEITURA)
    assert "IMEI" not in marcaveis and "ICCID" not in marcaveis
    assert "FREQ" in marcaveis and len(marcaveis) == 82, len(marcaveis)
    # a assinatura e a versao existem e aparecem no titulo
    assert AUTOR == "Felipe Gonçalves Lopes", AUTOR
    assert AUTOR in ASSINATURA and FEITO_EM in ASSINATURA, ASSINATURA
    # o Sobre explica sozinho: nada de mandar o usuario procurar arquivo
    assert len(SOBRE_TECNICO) >= 5
    for titulo, conteudo in SOBRE_TECNICO:
        assert titulo and len(conteudo) > 80, titulo
        assert ".md" not in conteudo, titulo
    assert VERSAO.count(".") == 1 and VERSAO.replace(".", "").isdigit(), VERSAO

    # o nome do backup tem data e hora e nada que o Windows recuse
    n = nome_backup(datetime.datetime(2026, 9, 11, 11, 46, 0))
    assert n == "configuracao backup 2026-09-11 11-46-00.ini", n
    assert not (set(n) & set(chr(58) + chr(42) + chr(63) + chr(34) + chr(60)
                             + chr(62) + chr(124))), n
    assert nome_backup() != nome_backup(datetime.datetime(2000, 1, 1))
    assert limpo_ascii("ab" + chr(0) + "c") == "abc"

    # sintaxe do fabricante e chave pelada chegam no mesmo quadro ATYS
    assert normalizar_comando("SZCS#APN=x.br") == ("#APN=x.br", "gravar")
    assert normalizar_comando("CXCS#APN") == ("#APN", "ler")
    assert normalizar_comando("#FREQ#APN") == ("#FREQ#APN", None)
    assert normalizar_comando("APN") == ("#APN", None)
    assert normalizar_comando("FREQ=60") == ("#FREQ=60", None)
    assert normalizar_comando("apn") == ("#apn", None)
    # o que nao e parametro continua sendo texto, e texto esta porta nao aceita
    assert normalizar_comando("PARAM#") == (None, None)
    assert normalizar_comando("RELAY,1#") == (None, None)
    assert normalizar_comando("") == (None, None)
    # CXCS forca leitura mesmo com '=' escrito por engano
    assert normalizar_comando("CXCS#FREQ=60")[1] == "ler"

    # a recusa tem de dar o motivo certo
    assert classificar_recusa("PARAM#") == "sms"
    assert classificar_recusa("RELAY,1#") == "sms"
    assert classificar_recusa("STATUS#") == "sms"
    assert classificar_recusa("0x0202 LER") == "formato"
    # tipo de quadro nao pode ser sugerido como opcode
    assert "nao e um comando" in dica_hex("0202") and "#CHAVE" in dica_hex("0202")
    assert dica_hex("0201").count("GRAVACAO") == 1
    assert dica_hex("0101") == " Para opcode use moni:0101."
    assert classificar_recusa("asdf") == "formato"
    assert classificar_recusa("") == "formato"

    # importar so grava sozinho se cada valor passar por esta peneira
    assert not valor_suspeito("60") and not valor_suspeito("operadora.exemplo.br")
    assert valor_suspeito("") and valor_suspeito("x" * 61)
    assert valor_suspeito("ab" + chr(0)) and valor_suspeito("caf" + chr(233))
    # os estilos de "nao gravado" existem para campo de texto e para combo
    import tkinter as _tk
    from tkinter import ttk as _ttk
    _r = _tk.Tk(); _r.withdraw()
    tema.aplicar(_r)
    _e = _ttk.Style(_r)
    assert _e.lookup("Sujo.TEntry", "foreground") == tema.ALERTA
    assert _e.lookup("Sujo.TCombobox", "foreground") == tema.ALERTA
    _r.destroy()

    print("j16gui selftest ok -", len(ALL_COMMANDS), "comandos,",
          sum(len(l) for l in MONI_SISTEMA) + len(MONI_GPS), "campos de monitor")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        selftest()
    else:
        run_gui()
