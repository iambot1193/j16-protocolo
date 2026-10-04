#!/usr/bin/env python3
"""J16 tracker configurator: parameter table, import/export, free-command console.

Replacement for ComTools (ENTools_V1065). The command names come from strings
in that program's binary; the wire format lives in j16proto and was recovered
by disassembling its frame builder, then verified against a real device.

    python j16gui.py
    python j16gui.py --selftest
"""
import argparse, configparser, datetime, json, os, queue, sys, threading, time
import webbrowser
from types import SimpleNamespace

import ajuda
import j16proto as proto
import tema

VERSAO = "1.7"
AUTOR = "Felipe Gonçalves Lopes"
FEITO_EM = "setembro de 2026"
ASSINATURA = f"{AUTOR}  \u00b7  {FEITO_EM}"

# Command names come from strings in ENTools_V1065.exe; the descriptions come
# from the field notes in "CONFIGURADOR J16 FELIPINHO/MATERIAL". Grouped for
# the UI only -- the firmware does not care about the grouping.
#
# Every name here was read back from a J16_10D6J_B44_V5.56 device, except the
# RFID group -- the Voxter "Comandos J16 Plus" sheet documents those and the
# plain J16 on hand has no reader, so it answers nothing for them.
# DNS_ENABLE and TIMING_RESET answered nothing on read but the colleague's notes
# set them explicitly, so they are kept as write-only (greyed, see NAO_CONFIRMADOS).
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
        ("VIBL", "sensibilidade do sensor: 1 a 6 (0 e 7+ o G900L recusa)"),
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
    # Found by diffing the command names out of ENTools_V1067.exe against this
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
        ("ICCID", "ICCID do chip  (G900L: so com o log de diagnostico ligado)"),
        ("IMSI", "IMSI do chip  (G900L: so com o log de diagnostico ligado)"),
        ("GPS_VER", "versao do modulo GPS"),
        ("TERIID", "ID do terminal"),
        ("SOFTVERSION", "versao do firmware"),
        ("EQUTYPE", "tipo de equipamento"),
    ],
    # Alarmes e agenda do Cantrack G900L. Nao existem no dicionario do J16 --
    # ficam escondidos em qualquer outro modelo, como o grupo RFID. Todos foram
    # lidos e regravados no aparelho em 14-09-2026; a forma de gravacao e
    # "CHAVE,valor#", nao "SZCS#CHAVE=valor" (ver proto.cantrack_escrita).
    "Alarmes e agenda (so Cantrack G900L)": [
        ("SENALM", "alarme do sensor: OFF, ou ON,modo -- ligar reescreve o VIBL"),
        ("MOVING", "deslocamento: OFF, ou ON,x,y -- so liga com posicao valida"),
        ("ACCALM", "avisa quando a ignicao liga: OFF ou ON,0"),
        ("ACCOFFALM", "avisa quando a ignicao desliga: OFF ou ON,0"),
        ("SOSALM", "alarme de SOS, ex ON,0"),
        ("STOCKADEALM", "alarme de cerca: OFF (o ON deste firmware nao foi achado)"),
        ("POWERALM", "corte de energia, ex ON,0,5,5"),
        ("BATALM", "bateria fraca, ex ON,0"),
        ("TIMER", "intervalo ignicao ligada,desligada (s), ex 20,3600"),
        ("HBT", "heartbeat ligada,desligada (s), ex 180,300 -- quer os dois"),
        ("GMT", "fuso: sinal,hora,minuto, ex W,0,0"),
        ("GT06SEL", "versao do protocolo GT06: V1.8 ou V3"),
        ("GT06GPRSGMT", "hora dos pacotes GT06 no fuso local"),
        ("RFID_ENABLE", "leitor de tag: 0 desliga, 1 liga"),
        ("CENTER", "numero central -- forma de gravacao nao verificada"),
        ("DRV", "perfil de conducao -- so leitura, vem do PARAM#"),
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
GRUPO_PLUS = "RFID / iButton (so J16 Plus)"   # so aparece quando um Plus responde
GRUPO_G900L = "Alarmes e agenda (so Cantrack G900L)"  # idem, para o outro firmware

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
    "Alarmes e agenda (so Cantrack G900L)": "alarmes e intervalos que so este firmware tem -- gravam por CHAVE,valor#",
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
    # Ordem confirmada nas strings do ENTools: "Ptl Select:TQ", "Ptl
    # Select:808", "Ptl Select:GT06" -- nessa sequencia, entao 0/1/2.
    "PTL_SEL": [("0", "TQ / Tianqin / H02"), ("1", "JT808"), ("2", "GT06")],
    "808SEL": [("0", "JT808 de 2011"), ("1", "JT808 de 2013")],
    # Fuso do G900L: "sinal,hora,minuto". Grava como "GMT,W,3,0#". Sao os
    # mesmos fusos do GMT_SET do J16, so que na sintaxe deste firmware.
    "GMT": [("E,0,0", "UTC / GMT 0 -- padrao do portal"),
            ("W,3,0", "GMT-3 Brasilia"),
            ("W,4,0", "GMT-4 Mato Grosso do Sul, Amazonas"),
            ("W,5,0", "GMT-5 Acre")],
    # Alarmes do G900L. Medido em 14-09-2026: "ON" pelado e recusado em
    # silencio -- ligar exige o parametro junto ("SENALM,ON,0#"). Desligar
    # nunca precisa dele. MOVING e STOCKADEALM ficam de fora: o MOVING quer
    # dois argumentos E uma posicao valida ("NOT POS MOVING ON FAIL" sem fix),
    # e o STOCKADEALM recusou toda forma de ON testada -- lista fechada ali
    # seria uma promessa que o firmware nao cumpre.
    "SENALM": [("OFF", "desligado"), ("ON,0", "ligado")],
    "ACCALM": [("OFF", "desligado"), ("ON,0", "ligado")],
    "ACCOFFALM": [("OFF", "desligado"), ("ON,0", "ligado")],
    # Formas que o proprio aparelho devolveu na leitura de 15-09-2026 e aceitou
    # de volta com SETOK. Sao liga/desliga na pratica: o argumento nunca muda.
    "SOSALM": [("OFF", "desligado"), ("ON,0", "ligado")],
    "BATALM": [("OFF", "desligado"), ("ON,0", "ligado")],
    "POWERALM": [("OFF", "desligado"), ("ON,0,5,5", "ligado (padrao de fabrica)")],
    # Os dois unicos valores que o configurador do fabricante oferece: a lista
    # "GT06 Protocol" do Cantrack PCTool tem V1.8 e V3, nessa ordem.
    "GT06SEL": [("0", "V1.8 -- pacote classico"), ("1", "V3 -- pacote estendido")],
    "VIBL": [("1", "1 - mais sensivel"), ("2", "2"), ("3", "3"),
             ("4", "4"), ("5", "5"), ("6", "6 - menos sensivel")],
    "SOURCE_OFF_TYPE": [("0", "condicionado (so em condicao segura)"),
                        ("1", "imediato")],
    # Mesma ideia dos tres campos do ENTools (sinal, hora, minuto), so que ja
    # resolvidos nos fusos que se usa de verdade.
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

# O G900L nao entende NADA da lista acima: ela e do dialeto ATYS do J16, e aqui
# o firmware simplesmente engole a linha sem responder -- o tecnico clicava e via
# a resposta do STATUS# do monitor passando, achando que tinha funcionado.
# Estes sao os comandos medidos no aparelho em 14-09-2026, todos com resposta
# confirmada; o ";" enfileira, um comando por quadro.
ACOES_CANTRACK = [
    ("Versão e identificação", "VERSION#;PARAM#",
     "firmware, IMEI e os parametros gerais"),
    ("Servidor e APN", "SERVER#;APN#",
     "para onde ele manda os dados e por qual chip"),
    ("Estado agora", "STATUS#",
     "bateria, tensao, ignicao, GPRS, sinal e rele"),
    ("Posição do GPS", "WHERE#",
     "coordenada, rumo, velocidade e hora"),
    ("Link do mapa", "POSITION#",
     "a mesma posicao como link do Google Maps"),
    ("Odômetro", "MILEAGE#",
     "quilometragem acumulada no aparelho"),
    ("Torre de celular", "CELL#",
     "mcc, mnc, LAC e celula -- vazio sem registro"),
    ("Intervalos de envio", "TIMER#;HBT#",
     "intervalo com e sem ignicao, e o heartbeat"),
    ("Fuso horário", "GMT#",
     "fuso gravado no aparelho"),
    ("Limite de velocidade", "SPEED#",
     "alarme de excesso: OFF ou o limite"),
    ("Alarmes de movimento", "SENALM#;MOVING#;STOCKADEALM#",
     "vibracao, deslocamento e cerca"),
    ("Alarmes elétricos", "POWERALM#;BATALM#",
     "corte de energia e bateria fraca"),
    ("Alarmes de ignição", "ACCALM#;ACCOFFALM#;SOSALM#",
     "ignicao ligada, desligada e botao SOS"),
    ("Números centrais", "CENTER#",
     "quem recebe alarme por SMS e chamada"),
    ("Chaves de protocolo", "CXCS#GT06ICCID;CXCS#GT06METER;CXCS#GT06IEXVOL",
     "ICCID, odometro e tensao nos pacotes"),
    ("Sono e desconexão", "CXCS#PULSE;CXCS#SLPDISCONNECT",
     "heartbeat e o que ele desliga dormindo"),
    ("iButton / RFID", "RFID,ENABLE#;RFID,GETSYNC#;RFID,MULRSQ#",
     "estado do leitor e as tags cadastradas"),
    # Modo de teste do configurador do fabricante, achado no Cantrack PCTool.
    # Unica forma conhecida de ler o ICCID deste aparelho.
    ("Modo teste: entrar", "AT+ZDR=debug",
     "autoteste a cada 3 s -- ICCID, satelites, mV e checklist OK/NG"),
    ("Modo teste: sair", "AT+ZDR=exitdebug",
     "para o autoteste -- sem isto ele fala sozinho para sempre"),
    # Log de diagnostico do proprio firmware. Traz o que nenhum comando traz:
    # IMSI, CSQ, intervalos em uso e o servidor com que ele esta falando.
    ("Log de diagnostico: ligar", "<ZDRCMD*LOG:1>",
     "bloco completo a cada 6 s -- IMSI, CSQ, servidor, limiares do sensor"),
    ("Log de diagnostico: desligar", "<ZDRCMD*LOG:0>",
     "para o bloco -- o AT+ZDR=exitdebug NAO para este"),
    ("Reiniciar rastreador", "RESET#",
     "reinicia o aparelho -- a porta cai por ~10 s"),
]

# Cadastro de tag do J16 Plus. Sao comandos de verdade (terminam em #), da folha
# "J16 PLUS - PORTAL SSX" -- nasceram no portal, mas comando e comando: fica aqui
# pronto para disparar, como o do odometro. Se esta porta USB nao responder, o
# resumo da fila diz "sem resposta" e ninguem fica no escuro.
# {TAG} = o programa pergunta o numero antes de mandar.
ACOES_RFID = [
    ("Consultar tags", "RFID,MULREQ#", "lista as tags ja cadastradas"),
    ("Informações da tag", "RFID,GETSYNC#", "estado da sincronizacao de tags"),
    ("Adicionar tag", "RFID,SU,{TAG}#", "cadastra uma tag (iButton: leia em U)"),
    ("Remover tag", "RFID,SD,{TAG}#", "apaga uma tag especifica"),
    ("Verificar tag", "RFID,AL,{TAG}#", "pergunta se a tag e valida"),
    ("Limpar TODAS as tags", "RFID,DL#", "apaga o cadastro inteiro -- sem volta"),
    ("Sincronização automática", "RFID,AUTOSYNC,1#", "liga a sincronizacao"),
    ("Relé normalmente aberto", "RFID,RELAYNO#", "modo NA do bloqueio"),
    ("Relé normalmente fechado", "RFID,RELAYNC#", "modo NF -- padrao de fabrica"),
    ("Tempo para ignição", "RFID,ONTIME,1#", "minutos ate liberar a ignicao"),
]

# Live status shown by the vendor tool's "Euqipment Moni Windows". The field
# names and the System Status wording were lifted from ENTools_V1067.exe, so the
# panel matches theirs one to one once the stream is decoded.
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
                            ("Defences", "Modo defesa"), ("Sleep", "Sleep")]),
    # "_modelo" nao vem do rastreador como os outros: quem preenche e o
    # handshake, aqui dentro. Fica no topo do card Sistema porque e a primeira
    # pergunta de quem liga dois paineis lado a lado -- qual e qual.
    ("Sistema", [("_modelo", "Rastreador"),
                 ("System Status", "Estado"), ("Run Time", "Tempo ligado"),
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
     ("Vibration", "Movimento"), ("Sleep", "Sleep"),
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
    ("Status", "GPS"), ("Satellite", "Satélites"), ("com sinal", "Com sinal"),
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
    "CENTER", "DRV", "GPS_VER",
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


# Comandos de texto que mexem em estado e nao tem desfazer. O console e livre
# de proposito -- este dicionario e o unico freio, e vale nos dois dialetos.
# A lista do lado Cantrack saiu do dicionario extraido do Cantrack PCTool, em
# docs/engenharia-reversa/ENGENHARIA_REVERSA_G900L.md.
PERIGOSOS = {
    "FACTORY": "FACTORY apaga TODA a configuracao do rastreador e nao tem volta.",
    "RESET": "RESET reinicia o aparelho. A porta USB cai por uns 10 segundos.",
    "RELAY": "RELAY aciona o rele de bloqueio -- pode cortar a alimentacao do "
             "veiculo agora mesmo.",
    "LOCK": "LOCK tranca o aparelho. Sem a senha certa depois, ele nao aceita "
            "mais comando nenhum.",
    "SETPWD": "SETPWD troca a senha do aparelho. Errar aqui tranca voce do lado "
              "de fora.",
    "SERVEROFF": "SERVEROFF desliga o envio para o servidor -- o rastreador para "
                 "de aparecer na plataforma.",
    "EXTPOWSAFE": "Comando de corte de alimentacao externa.",
}


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


def chaves_legiveis_cantrack():
    """As chaves que o G900L devolve, por CXCS# ou por consulta propria. Sai da
    propria lista de leitura para nao virar uma segunda lista que envelhece
    sozinha."""
    chaves = {e.split("#", 1)[1] for e in proto.CANTRACK_LEITURA
              if e.upper().startswith("CXCS#")}
    for cmd, ks in proto.CANTRACK_CONSULTA_PARAM.items():
        if cmd in proto.CANTRACK_LEITURA:
            chaves.update(ks)
    return chaves


def consultas_cantrack(chaves):
    """Os comandos que devolvem estas chaves, sem repetir comando."""
    alvos = []
    for k in chaves:
        cmd = next((c for c, ks in proto.CANTRACK_CONSULTA_PARAM.items()
                    if k in ks), f"CXCS#{k}")
        if cmd not in alvos:
            alvos.append(cmd)
    return alvos


def _primeiro_numero(texto):
    """'14 (fraco)' -> 14.0 ;  '4.30V' -> 4.3 ;  '--' -> None."""
    num = ""
    for c in str(texto or ""):
        if c.isdigit() or (c == "." and num and "." not in num):
            num += c
        elif num:
            break
    try:
        return float(num)
    except ValueError:
        return None


# Limiares das cinco barras de sinal, na escala CSQ padrao (0-31; 99 = sem
# leitura). 14 -- o que este aparelho marca na bancada -- acende tres.
_NIVEIS_CSQ = (2, 7, 12, 17, 22)


def barra_csq(valor):
    """CSQ -> barra de 5 niveis. Vazio quando nao ha leitura."""
    n = _primeiro_numero(valor)
    if n is None or n >= 99:
        return ""
    return "".join("▮" if n >= t else "▯" for t in _NIVEIS_CSQ)


def pct_bateria(valor):
    """'4.30V' -> 100. Celula de litio: 3,4 V vazia, 4,2 V cheia.

    E estimativa por tensao em repouso, nao medicao de carga -- sob consumo a
    tensao cai e a conta subestima. Serve para o olho na bancada, nao para
    laudo.
    """
    v = _primeiro_numero(valor)
    if v is None or not 2.5 <= v <= 5.0:
        return None
    return max(0, min(100, round((v - 3.4) / 0.8 * 100)))


def _classificar(texto, ruins, bons):
    """Palavra do painel -> 'falha', 'ok' ou '?'. Ruins primeiro: "nao
    registrado" contem "registrado", e testar o bom antes pintaria de verde
    justamente o caso que interessa."""
    t = (texto or "").strip().lower()
    if not t or t in ("--", "?"):
        return "?"
    if any(r in t for r in ruins):
        return "falha"
    if any(b in t for b in bons):
        return "ok"
    return "?"


# Cada campo com leitura boa e ruim de verdade. O que nao esta aqui fica na cor
# normal: pintar tudo e o mesmo que nao pintar nada.
_REGRAS_COR = {
    "REG": (("nao", "não", "fora"), ("sim", "registrado")),
    "Power": (("ausente", "cortada"), ("presente", "conectada")),
    "SIM": (("ausente",), ("presente",)),
    "Status": (("off", "sem", "nao"), ("on", "fix", "a")),
    "System Status": (("offline", "reset", "fly"), ("online", "normal connect")),
    "Defences": ((), ("armado",)),
}


def cor_do_campo(nome, valor, cores):
    """Cor de um valor do painel; None = cor padrao.

    `cores` e um dicionario com ok/alerta/erro/apagado -- passar as cores em vez
    de ler o tema aqui e o que deixa esta funcao testavel sem interface.
    """
    v = (valor or "").strip()
    if not v or v == "--":
        return None
    if nome == "CSQ":
        n = _primeiro_numero(v)
        if n is None or n >= 99:
            return None
        return cores["ok"] if n >= 17 else cores["alerta"] if n >= 10 else cores["erro"]
    if nome == "Voltage":
        n = _primeiro_numero(v)
        if n is None:
            return None
        if n >= 20:                      # instalacao de 24 V
            return cores["ok"] if n >= 23 else cores["alerta"] if n >= 22 else cores["erro"]
        if n < 1:                        # 0,00 V = sem alimentacao externa
            return cores["erro"]
        return cores["ok"] if n >= 11.8 else cores["alerta"] if n >= 11 else cores["erro"]
    if nome == "Battery":
        n = _primeiro_numero(v)
        if n is None:
            return None
        return cores["ok"] if n >= 3.9 else cores["alerta"] if n >= 3.6 else cores["erro"]
    if nome == "Sleep":
        return cores["alerta"] if _classificar(v, (), ("dormindo",)) == "ok"             else cores["ok"]
    if nome == "ACC":
        return cores["ok"] if _classificar(v, (), ("on", "ligada")) == "ok" else None
    regra = _REGRAS_COR.get(nome)
    if not regra:
        return None
    estado = _classificar(v, *regra)
    return {"ok": cores["ok"], "falha": cores["erro"]}.get(estado)


def sufixo_do_campo(nome, valor):
    """Texto curto que acompanha o valor na mesma linha. '' quando nao ha."""
    if nome == "Battery":
        pct = pct_bateria(valor)
        return f"({pct}%)" if pct is not None else ""
    return ""


ETAPAS_CONEXAO = ("Chip", "Torre", "Dados", "Servidor")


def etapas_conexao(vals):
    """As quatro etapas ate o portal -> [(rotulo, 'ok'|'falha'|'?')].

    O '?' existe de proposito: o G900L nao reporta chip nem contador de socket,
    e acender verde numa etapa que ninguem mediu e pior que nao mostrar nada --
    manda o tecnico procurar o problema no lugar errado.
    """
    chip = _classificar(vals.get("SIM"), ("ausente",), ("presente",))
    torre = _classificar(vals.get("REG"), ("nao", "não", "fora"),
                         ("sim", "registrado"))
    dados = _classificar(vals.get("System Status"), ("offline",),
                         ("online", "normal connect"))
    enviados = _primeiro_numero(vals.get("Socket Send"))
    if dados == "ok" or (enviados or 0) > 0:
        servidor = "ok"
    elif dados == "falha":
        servidor = "falha"
    else:
        servidor = "?"
    return list(zip(ETAPAS_CONEXAO, (chip, torre, dados, servidor)))


def dica_rede(vals):
    """Uma linha de diagnostico quando os numeros da tela se contradizem."""
    csq = _primeiro_numero(vals.get("CSQ"))
    reg = _classificar(vals.get("REG"), ("nao", "não", "fora"),
                       ("sim", "registrado"))
    if csq is not None and 10 <= csq < 99 and reg == "falha":
        return ("Sinal chega, mas o chip nao registra na operadora. Olhe "
                "bloqueio do chip, saldo ou fatura do M2M, e se a antena cobre "
                "a banda da regiao -- mexer na APN nao resolve isto.")
    return ""


def cor_da_linha(txt):
    """Cor pelo tipo da linha, como um terminal de verdade: azul o que
    sai, verde o que volta, vermelho o que falhou."""
    t = txt.lstrip()
    if t.startswith("TX"):
        return "tx"
    # A recusa do proprio aparelho vem DENTRO de uma linha RX, entao tem de ser
    # testada antes dela -- senao sai verde, igual a uma resposta boa.
    alto = t.upper()
    if any(m in alto for m in ("CFG CMD UNKNOWN", "ERROR", "FAIL", "NOT POS",
                               "SEM RESPOSTA", "TIMEOUT")):
        return "err"
    if t.startswith("RX"):
        return "rx"
    if t.startswith(("ERRO", "nao enviado", "FALHA", "BLOQUEADO")):
        return "err"
    return "val" if txt.startswith(" ") else ""


# Gravar servidor, APN ou o leitor de tag faz o G900L se reiniciar sozinho.
# Medido em 15/09/2026: "SZCS#SERVIP=..." responde "CFGSZCS,SERVIP", depois vem
# "[DEF]Update_File_type:7" e logo "==>>app_user_reset:10". Tudo que for enviado
# durante o boot se perde -- o aparelho ecoa o comando em vez de responder.
REINICIAM_O_APARELHO = {"SERVIP", "SERVPORT", "APN", "USERPPP", "PWPPP",
                        "RFID_ENABLE"}

# Linhas que o proprio aparelho imprime ao reiniciar.
_SINAIS_REINICIO = ("app_user_reset", "restart_type", ">>power_msg",
                    "power-on information", "param mutex create")

# Segundos de silencio de reinicio antes de acreditar que ele voltou. Medido:
# do "app_user_reset" ate o aparelho responder de novo deu cerca de 13 s.
ESPERA_REINICIO = 16


def linha_de_reinicio(txt):
    """A linha diz que o aparelho esta reiniciando?"""
    t = (txt or "").lower()
    return any(sinal in t for sinal in _SINAIS_REINICIO)


def separar_reinicios_inuteis(pairs, lidos):
    """Divide o lote em (enviar, ja_iguais).

    So as seis chaves que reiniciam o aparelho entram no segundo grupo, e so
    quando o valor da tela e igual ao que o rastreador acabou de reportar:
    regravar o mesmo endereco de servidor custa um boot de 13 s e nao muda nada.
    Nas outras chaves reenviar e barato, e as vezes proposital -- o SERVIP que
    "volta ao de fabrica sozinho" so aparece quando a leitura DIFERE, e ai o par
    nao e igual e vai junto normalmente.
    """
    iguais = [(k, v) for k, v in pairs
              if k in REINICIAM_O_APARELHO and lidos.get(k) == v]
    resto = [(k, v) for k, v in pairs if (k, v) not in iguais]
    return resto, iguais


def ordem_de_gravacao(pairs):
    """Poe por ultimo o que derruba o aparelho.

    Sem isto o lote comeca por SERVIP, o rastreador reinicia no meio e as
    gravacoes seguintes caem no vazio -- foi o que aconteceu no teste de
    15/09/2026, em que 29 chaves foram enviadas e nenhuma pode ser conferida.
    """
    depois = [p for p in pairs if p[0] in REINICIAM_O_APARELHO]
    return [p for p in pairs if p[0] not in REINICIAM_O_APARELHO] + depois


def freq_do_timer(valor):
    """TIMER do G900L -> FREQ da tela.

    PARAM# devolve "TIMER:20,3600" e TIMER# devolve "TIMER ACC ON:20s,ACC
    OFF:3600s". Nos dois o primeiro numero e o intervalo com a ignicao ligada,
    que e exatamente o FREQ. Sem isso o campo fica em branco a toa: o valor
    estava chegando, so com outro nome.
    """
    import re
    achado = re.search(r"\d+", valor or "")
    return achado.group() if achado else None


def comparar_gravacao(esperado, lidos, sem_leitura=()):
    """O que foi pedido x o que o aparelho devolveu na releitura.
    Devolve (confirmados, divergentes, sem_resposta, nao_confirmaveis).

    `sem_leitura` sao as chaves que o aparelho GRAVA mas nao LE (no G900L:
    SERVIP, SERVPORT, APN, USERPPP, PWPPP, FREQ). Elas nao podem entrar em
    "sem resposta": a gravacao pode ter dado certo e nao ha como perguntar.
    Chamar isso de falha e mentir para o tecnico.

    Separado da tela porque e a regra que decide se a gravacao deu certo."""
    ok, divergentes, mudos, sem_conferir = [], [], [], []
    for chave, queria in esperado.items():
        if chave in sem_leitura:
            sem_conferir.append(chave)
            continue
        veio = lidos.get(chave)
        if veio is None:
            mudos.append(chave)
        elif limpo_ascii(veio).strip() == limpo_ascii(queria).strip():
            ok.append(chave)
        else:
            divergentes.append((chave, queria, veio))
    return ok, divergentes, mudos, sem_conferir


def separar_comandos(texto):
    """'a;b;;c ' -> ['a', 'b', 'c']. O ';' e nosso, nao do firmware."""
    return [p.strip() for p in texto.split(";") if p.strip()]


def linha_de_monitor(line):
    """Esta linha do log nasceu do laco do monitor?

    O monitor pergunta STATUS# e WHERE# (ou os dois quadros binarios) uma vez
    por segundo, para sempre. Sao tres a seis linhas por pergunta, e em um
    minuto elas empurram para fora da tela qualquer coisa que o tecnico quisesse
    ler. Reconhecer pelo texto e grosseiro de proposito: nao ha marca de origem
    na linha, e errar aqui esconde uma linha a mais, nunca manda nada errado.
    """
    t = line.strip()
    if t.startswith(("TX", "RX")) and ("STATUS#" in t or "WHERE#" in t
                                       or "moni:" in t):
        return True
    if "cmdAckStr:Battery:" in t or "cmdAckStr:LastPosition" in t:
        return True
    return t.split(" = ")[0] in ("lat", "lon", "gid", "rele")


# Rastros que o G900L cospe sozinho na porta AT: pilha TCP, GSM, GPS, gSensor.
# Nao sao resposta a nada que o configurador perguntou.
_RUIDO = ("[socket]", "[gsm]", "[kks]", "[wifi]", "[gps]", "[his]", "[def]",
          "[gsensor]", "socketerr", "socket_close", "create socket",
          "dns_to_ip", "zdr_socketconnect", "gettypesockopt", "tcpip[",
          "app_tcpip_client", "user_app_close_fd", "kks_send", "nust:",
          "clean_locat_step", "cache_queue_length", "==>zdrcmd",
          "pos_info_stream", "data_insert_fs", "write_point", "aid_agps",
          "ephemer_check", "sys_tim", "agps xlen", "send_agps_len",
          "inject again", "turning point",
          # fluxo de dados quando conectado ao servidor: posicao subindo e o
          # ACK voltando, a cada 2 s -- inunda o log e esconde as respostas
          "kks_rev", "kks_his_send")


def linha_de_ruido(line):
    """Esta linha e debug interno do rastreador, e nao resposta ao programa?

    O aparelho fala sozinho o tempo todo -- tenta o servidor, apanha, fecha o
    socket e recomeca a cada 14 s. Isso empurra para fora da tela a unica coisa
    que o tecnico esta lendo: o que ele mandou e o que voltou. Resposta de
    comando, confirmacao de gravacao e sinal de reinicio nunca entram aqui: sao
    a prova do servico.
    """
    t = (line or "").strip().lower()
    if not t.startswith(("tx", "rx")):
        return False
    if ("cmdackstr" in t or "setok" in t or "readok" in t
            or linha_de_reinicio(t)):
        return False
    # eco do pacote GT06 cru (posicao/heartbeat subindo, "7878..0d0a" ou
    # "7979..0d0a"): so hex, nao e resposta a comando -- puro ruido de uplink
    if "(texto) 7878" in t or "(texto) 7979" in t:
        return True
    return any(m in t for m in _RUIDO)


def arquivo_meus_comandos():
    """Os comandos que o tecnico salvou. Moram junto dos backups porque e a
    mesma pergunta ('onde da para escrever?') ja resolvida la."""
    pasta = pasta_backup()
    return None if pasta is None else os.path.join(pasta, "meus_comandos.json")


def ler_meus_comandos():
    caminho = arquivo_meus_comandos()
    if not caminho or not os.path.exists(caminho):
        return []
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []                    # arquivo torto nao derruba o programa
    return [(str(d.get("rotulo", "")), str(d.get("texto", "")))
            for d in dados if isinstance(d, dict) and d.get("texto")]


def salvar_meus_comandos(lista):
    caminho = arquivo_meus_comandos()
    if not caminho:
        return False
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump([{"rotulo": r, "texto": t} for r, t in lista],
                      f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    return True


def arquivo_modelos():
    """Configuracoes nomeadas prontas pra carregar em rastreador novo. Mesma
    pasta dos backups, mesmo motivo do meus_comandos.json."""
    pasta = pasta_backup()
    return None if pasta is None else os.path.join(pasta, "modelos.json")


def ler_modelos():
    caminho = arquivo_modelos()
    if not caminho or not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in dados.items() if isinstance(v, dict)} \
        if isinstance(dados, dict) else {}


def salvar_modelos(modelos):
    caminho = arquivo_modelos()
    if not caminho:
        return False
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(modelos, f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    return True


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
LETRAS = "AB"      # nome curto de cada painel, usado na tela e nos avisos
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


def porta_modem(device):
    """A porta 'modem' do mesmo aparelho, se existir.

    Descoberto em 15-09-2026: a porta AT do G900L e sequestrada pelo aplicativo
    do rastreador (responde CFG CMD UNKNOWN ate para 'AT'), mas a porta MODEM ao
    lado tem o interpretador AT do SIMCom inteiro e livre. E de la que saem
    ICCID, IMSI e operadora -- que pela porta de configuracao so apareciam
    ligando o log de diagnostico.
    """
    try:
        from serial.tools import list_ports
        descr = {p.device: (p.description or "").lower()
                 for p in list_ports.comports()}
    except Exception:
        return None
    for irma in portas_irmas(device):
        if "modem" in descr.get(irma, ""):
            return irma
    return None


def ler_chip(device, espera=1.0):
    """ICCID, IMSI e operadora pela porta modem. {} se nao der.

    Abre, pergunta, fecha: a porta nao fica presa, e quem esta configurando
    continua usando a porta AT ao mesmo tempo.
    """
    porta = porta_modem(device)
    if not porta:
        return {}
    import serial
    achados = {}
    try:
        s = serial.Serial(porta, 115200, timeout=0.2)
        s.dtr = s.rts = False
    except Exception:
        return {}
    try:
        for cmd, chave in (("AT+CICCID", "ICCID"), ("AT+CIMI", "IMSI"),
                           ("AT+COPS?", "_operadora")):
            s.write((cmd + chr(13) + chr(10)).encode())
            s.flush()
            fim, buf = time.time() + espera, b""
            while time.time() < fim:
                buf += s.read(4096)
            for linha in buf.decode("latin-1", "replace").splitlines():
                linha = linha.strip()
                if not linha or linha in ("OK", cmd) or linha.startswith("AT"):
                    continue
                if "ERROR" in linha:
                    break
                valor = linha.partition(":")[2].strip() or linha
                achados[chave] = valor.strip('"')
                break
    finally:
        s.close()
    return achados


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
     "Nada aqui veio de manual. O metodo foi desmontar a ferramenta do\n"
     "fabricante e ler o codigo dela.\n\n"
     "O tratador de respostas dela e uma tabela de saltos compilada assim:\n\n"
     "  add eax, -base      ; base = primeiro opcode da tabela\n"
     "  cmp eax, n\n"
     "  jmp [tabela + eax*4]\n\n"
     "Ou seja: a posicao na tabela E o numero do comando, e o texto que\n"
     "aquele trecho imprime e o nome dele. Cinco tabelas dessas deram todos\n"
     "os opcodes de evento -- colisao, gSensor, tempo de parada.\n\n"
     "Os nomes de parametro sairam das strings do binario; o significado de\n"
     "cada um foi conferido lendo do aparelho de verdade."),
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
     "Nomes vem do binario do fabricante. Descricoes, onde nao havia nota de\n"
     "campo, sao interpretacao -- e estao marcadas como tal."),
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
             "recuperado desmontando a ferramenta do fabricante e conferido\n"
             "contra um aparelho real, quadro por quadro.\n\n"
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

    try:
        import serial  # noqa: F401
    except ImportError:
        # ports()/detect_devices() engolem este mesmo erro e devolvem lista
        # vazia -- sem isto aqui o tecnico via "0 portas" e ia procurar driver
        # USB errado quando o problema e so o pacote Python faltando.
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Falta o pyserial",
            "O configurador precisa do pacote pyserial e ele nao esta "
            "instalado neste Python.\n\nRode no terminal:\n"
            "pip install pyserial",
        )
        return

    root = tk.Tk()
    root.title(f"Configurador J16  {VERSAO}")
    root.geometry("1280x720")

    style = tema.aplicar(root, tema.modo_salvo())
    root.minsize(1100, 640)

    # One tracker per panel, side by side. Each owns its port, its reader
    # thread and its own copy of the table -- nothing is shared, so two
    # trackers can be read and written at the same time.
    # Grid, nao pack, pelo mesmo motivo do rodape de cada painel (ver comentario
    # em montar_painel): o notebook tem altura minima grande, e com pack o rodape
    # da janela era espremido ate os botoes "Copiar A -> B" virarem fatias de 2px.
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.grid(row=0, column=0, sticky="nsew")
    paineis = []
    ao_trocar_tema = []     # repinte do log de cada painel, ver alterna_tema

    def montar_painel(pai, indice):
        link = Link()
        rx_q = queue.Queue()
        # Layout em grid, nao pack: o notebook tem uma altura minima grande (a
        # aba Monitoramento). Com pack, ao encolher a janela o pack nao consegue
        # espremer o notebook e rouba a altura do rodape -- os botoes viravam
        # fatias de 1px. No grid, so a linha do notebook (weight 1) encolhe; a
        # do rodape guarda a altura natural sempre.
        pai.grid_rowconfigure(2, weight=1)
        pai.grid_columnconfigure(0, weight=1)
        # --- connection bar -----------------------------------------------------
        top = tk.Frame(pai, bg=tema.CARD, padx=10, pady=8)
        top.grid(row=0, column=0, sticky="ew")
        tk.Frame(pai, bg=tema.BORDA, height=1).grid(row=1, column=0, sticky="ew")
        rodape_painel = tk.Frame(pai, bg=tema.BG)
        rodape_painel.grid(row=3, column=0, sticky="ew")
        # Com dois paineis, "painel da esquerda" nao e nome: o tecnico troca de
        # cadeira e perde a referencia. A letra fica colada na barra de porta,
        # que e onde ele olha para saber qual aparelho esta mexendo.
        if quantos > 1:
            tk.Label(top, text=f" {LETRAS[indice]} ", bg=tema.ACENTO,
                     fg=tema.ACENTO_TXT, font=tema.F_BOLD, padx=4, pady=2
                     ).pack(side="left", padx=(0, 10))
        tk.Label(top, text="PORTA", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left")
        port_var = tk.StringVar()
        # com dois paineis cada um tem metade da largura: 32 chars aqui empurram
        # o badge de status para fora da barra
        port_cb = ttk.Combobox(top, textvariable=port_var,
                               width=32 if quantos < 2 else 18)
        port_cb.pack(side="left", padx=(8, 4))
        atualizar_btn = ttk.Button(top, text="atualizar", width=9,
                                   style="Ghost.TButton",
                                   command=lambda: refresh_ports())
        atualizar_btn.pack(side="left")
        tk.Label(top, text="BAUD", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left", padx=(14, 0))
        baud_var = tk.StringVar(value="115200")
        baud_cb = ttk.Combobox(
            top, textvariable=baud_var, width=8,
            values=["115200", "9600", "19200", "38400", "57600", "921600"])
        baud_cb.pack(side="left", padx=8)
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

        def repintar_painel():
            """O Text do log guarda as cores nas tags, que nao entram no repinte
            automatico; as marcas de ambar tambem precisam da cor nova."""
            log.configure(bg=tema.TERM, fg=tema.LOG_NEUTRO,
                          highlightbackground=tema.BORDA)
            for nome, cor in (("tx", tema.LOG_TX), ("rx", tema.LOG_RX),
                              ("err", tema.LOG_ERR), ("val", tema.LOG_VAL),
                              ("hora", tema.LOG_HORA)):
                log.tag_configure(nome, foreground=cor)
            revisar_sujos()
        ao_trocar_tema.append(repintar_painel)

        def alterna_tema():
            novo = "claro" if tema.MODO == "escuro" else "escuro"
            tema.trocar(root, novo)
            tema_btn.config(text=rotulo_tema())
            for f in ao_trocar_tema:   # os dois paineis, nao so o do botao
                f()
            # o tema e preferencia de tela, nao evento do rastreador: no
            # historico ele so empurrava linha de comando pra cima.

        # Sobre e Tema mexem na janela inteira, nao neste rastreador: com dois
        # paineis duas copias so roubariam a largura do badge de status, que
        # sumia espremido. Um par so, no painel da esquerda.
        if indice == 0:
            tema_btn = ttk.Button(top, width=14, style="Outline.TButton",
                                  command=alterna_tema, text=rotulo_tema())
            tema_btn.pack(side="right")
            ttk.Button(top, text="Sobre", width=8, style="Ghost.TButton",
                       command=lambda: abrir_sobre(root)).pack(side="right", padx=6)
        # --- notebook -----------------------------------------------------------
        # clam is the only stock theme that honours tab background/padding, which is
        # what makes the active tab actually stand out from the window.
        nb = ttk.Notebook(pai, padding=6)
        nb.grid(row=2, column=0, sticky="nsew")
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
        modelo = ["J16"]   # "J16" ou "J16 Plus" -- definido no handshake
        # "atys" = quadro binario do J16. "cantrack" = comando de texto
        # terminado em "#" do G900L, que recusa todo quadro binario. Quem
        # decide e o aperto de mao na conexao, nao o usuario.
        dialeto = ["atys"]
        sessao_iniciada = [False]   # leitura e monitor sobem uma vez so
        ao_trocar_modelo = []   # callbacks(nome) rodados quando o modelo muda
        # O J16 simples nao tem leitor de tag: o grupo RFID fica escondido ate
        # um Plus se identificar, para nao poluir a tela com campos que aquele
        # aparelho nunca responde.
        oculto_modelo = {c for grp in (GRUPO_PLUS, GRUPO_G900L)
                         for c, _ in COMMANDS[grp]}

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
            # Todo campo ocupa a MESMA largura, seja caixa de texto, lista ou
            # par de botoes: o widget se estica ate a coluna, em vez de cada um
            # pedir a largura que quer. Sem isto a lista sai mais larga que a
            # caixa de texto da linha de cima e a coluna das descricoes vira
            # uma serra.
            inner_grid.columnconfigure(2, minsize=250)
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
                    linha_lig.grid(row=r, column=2, sticky="ew", padx=4)
                    campo = linha_lig
                elif cmd in ESCOLHAS and editavel:
                    opcoes = ESCOLHAS[cmd]
                    rotulos = [f"{v} - {t}" for v, t in opcoes]
                    cb = ttk.Combobox(inner_grid, values=rotulos, width=28,
                                      state="readonly")
                    cb.grid(row=r, column=2, sticky="ew", padx=4)

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
                elif cmd == "MOVING" and editavel:
                    # "OFF" ou "ON,raio,modo" -- tres caixas, nenhuma digitavel.
                    # R=100..1000 m e M=0/1/2 saem do manual do fabricante
                    # (docs/fontes-externas/chinagpstracker_j16.txt): digitado a
                    # mao, qualquer outra forma o firmware recusa calado.
                    MOV_MODOS = ["0 - so GPRS", "1 - GPRS e SMS",
                                 "2 - GPRS, SMS e chamada"]
                    linha_mov = ttk.Frame(inner_grid, style="Card.TFrame")
                    mov_on = ttk.Combobox(linha_mov, width=9, state="readonly",
                                          values=["desligado", "ligado"])
                    mov_raio = ttk.Combobox(
                        linha_mov, width=5, state="readonly",
                        values=[str(n) for n in range(100, 1001, 100)])
                    mov_modo = ttk.Combobox(linha_mov, width=22,
                                            state="readonly", values=MOV_MODOS)
                    mov_on.pack(side="left")
                    mov_raio.pack(side="left", padx=(6, 0))
                    tk.Label(linha_mov, text="m", bg=tema.CARD, fg=tema.TXT2,
                             font=tema.F_TXT).pack(side="left", padx=(3, 0))
                    mov_modo.pack(side="left", padx=(8, 0))

                    def mov_trava(raio=mov_raio, modo=mov_modo, chave=mov_on):
                        ligado = chave.get() == "ligado"
                        for w_ in (raio, modo):
                            w_.config(state="readonly" if ligado else "disabled")

                    def mov_escreve(*_a, v=val, chave=mov_on, raio=mov_raio,
                                    modo=mov_modo):
                        mov_trava()
                        if chave.get() != "ligado":
                            v.set("OFF")
                            return
                        v.set(f"ON,{raio.get() or '1000'},{(modo.get() or '0')[0]}")

                    def mov_le(*_a, v=val, chave=mov_on, raio=mov_raio,
                               modo=mov_modo):
                        partes = v.get().strip().upper().split(",")
                        chave.set("ligado" if partes[0] == "ON" else "desligado")
                        if len(partes) == 3:
                            raio.set(partes[1])
                            for op in MOV_MODOS:
                                if op.startswith(partes[2]):
                                    modo.set(op)
                        mov_trava()

                    for w_ in (mov_on, mov_raio, mov_modo):
                        w_.bind("<<ComboboxSelected>>", mov_escreve)
                    val.trace_add("write", mov_le)
                    mov_le()
                    linha_mov.grid(row=r, column=2, sticky="ew", padx=4)
                    campo = linha_mov
                elif cmd == "PWPPP" and editavel:
                    # senha do APN: escondida por padrao, com botao para conferir
                    # o que foi digitado antes de gravar
                    linha_senha = ttk.Frame(inner_grid, style="Card.TFrame")
                    ent = ttk.Entry(linha_senha, textvariable=val, width=24,
                                    show="•")
                    ent.pack(side="left", fill="x", expand=True)
                    olho = ttk.Button(linha_senha, text="ver", width=8,
                                      style="Ghost.TButton")
                    def ver_senha(ent=ent, olho=olho):
                        escondida = bool(ent.cget("show"))
                        ent.config(show="" if escondida else "•")
                        olho.config(text="ocultar" if escondida else "ver")
                    olho.config(command=ver_senha)
                    olho.pack(side="left", padx=(4, 0))
                    linha_senha.grid(row=r, column=2, sticky="ew", padx=4)
                    campo = linha_senha
                else:
                    campo = ttk.Entry(inner_grid, textvariable=val, width=30,
                                      state="readonly" if so_leitura else "normal")
                    campo.grid(row=r, column=2, sticky="ew", padx=4)
                ws.append(campo)

                opcoes_campo = ESCOLHAS.get(cmd)
                # Sem '(i)' por linha: a ajuda abre pousando o mouse no nome ou
                # na descricao do parametro. Eram 106 icones numa coluna so,
                # disputando atencao com o valor -- que e o que se le aqui.
                abrir_ajuda = (
                    lambda e, c=cmd, d=description, oc=opcoes_campo,
                    rp=(cmd not in NAO_CONFIRMADOS),
                    ro=(cmd in SOMENTE_LEITURA): tema.popover(
                        root, *ajuda.do_campo(
                            c, d,
                            ajuda.tipo_do_campo(c, LIGA_DESLIGA, ESCOLHAS, ro),
                            opcoes=oc, respondeu=rp, so_leitura=ro)[::1],
                        e.x_root + 12, e.y_root + 8))
                tema.ajuda_no_hover(nomes[cmd][0], abrir_ajuda)

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
                tema.ajuda_no_hover(w, abrir_ajuda)

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
                if cmd in oculto_modelo:      # grupo RFID so no J16 Plus
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

        def rotulo_status():
            """Pinta o badge de conexao, sempre com o modelo junto.

            Antes o 'J16' simples ficava escondido, por nao acrescentar nada. Com
            dois paineis abertos acrescenta sim: sem o nome nao da para saber se
            o painel identificou um J16 ou se ainda nao identificou nada."""
            if not link.open:
                return
            txt = ("CONECTADO  " + port_var.get().split()[0]
                   + "  ·  " + modelo[0])
            status.set(txt, tema.OK)

        def responder_cantrack(resposta):
            """Uma resposta ">>cmdAckStr:..." do G900L vira campo na tela.

            E aqui tambem que o dialeto e decidido: so este firmware responde
            "VER:" ao VERSION#, entao a primeira resposta dessas ja prova quem
            esta do outro lado e troca o resto do programa de trilho.
            """
            if resposta.startswith("VER:") and dialeto[0] != "cantrack":
                dialeto[0] = "cantrack"
                set_modelo("Cantrack G900L", "por VERSION#")
                notify("Cantrack G900L reconhecido -- comandos de texto "
                       "terminados em # (o dicionario do J16 nao vale aqui)",
                       tema.OK)
                root.after(200, iniciar_sessao)
            if "CFG CMD UNKNOWN" in resposta.upper():
                write_log("      traducao: o aparelho recebeu o quadro e disse "
                          "que NAO conhece esse comando neste firmware -- "
                          "reenviar nao muda nada.", "err")
                # No G900L o monitor pergunta STATUS#/WHERE#, que este firmware
                # responde. A recusa aqui e de outro comando -- tipicamente um
                # digitado no console -- e derrubar o monitor por causa dela
                # deixava o painel congelado sem ninguem entender por que.
                if dialeto[0] != "cantrack":
                    moni_sem_suporte()
                return
            campos, chaves = proto.parse_cantrack(resposta)
            # O G900L nao tem chave "FREQ", mas tem o valor: e o primeiro numero
            # do TIMER (intervalo com ignicao ligada). Vem tanto no PARAM# quanto
            # no TIMER#. Traduzir aqui e o que tira o campo do branco.
            if "TIMER" in chaves and "FREQ" not in chaves:
                achado = freq_do_timer(chaves["TIMER"])
                if achado:
                    chaves["FREQ"] = achado
            # O contador de silencio so zerava no quadro BINARIO, que este
            # firmware nunca manda: o G900L respondia tudo e mesmo assim levava
            # "provavelmente em sleep" depois de 8 perguntas. Resposta e
            # resposta, venha em quadro ou em texto.
            if campos or chaves:
                if moni_mudo[0] >= 8:
                    notify("MONITOR: rastreador acordou", tema.OK)
                moni_mudo[0] = 0
            for nome, valor in campos.items():
                if nome in moni:
                    moni[nome].set(valor)
                else:
                    # campo que a tela do J16 nao tem (SDK, APP, IMEI, TIMER...):
                    # vai para o log com o nome do aparelho, em vez de sumir
                    write_log(f"      {nome.lstrip('_')} = {valor}")
                recebidos[0] += 1
            for chave, valor in chaves.items():
                write_log(f"      {chave} = {valor}")
                last_values[chave] = valor
                recebidos[0] += 1
                if chave in rows:
                    rows[chave][1].set(valor)
                    marca_sujo(chave)
            if "_lat" in campos:
                set_pos(campos.pop("_lat"), campos.pop("_lon"))
            elif "Latitude" in campos:
                set_pos(None, None)       # respondeu posicao, mas sem fix
            if campos:
                marcar_fonte("resposta de texto do G900L")

        def aplicar_dialeto_monitor():
            """Some com as linhas que este dialeto nunca vai preencher.

            Vinte campos presos em "--" nao sao informacao nenhuma: quem olha
            fica esperando um numero que o firmware nao tem como mandar.
            """
            so_cantrack = dialeto[0] == "cantrack"
            for nome, (lbl, val) in moni_widgets.items():
                mostra = not so_cantrack or nome in proto.CANTRACK_CAMPOS_TELA
                for w in (lbl, val):
                    w.grid() if mostra else w.grid_remove()

        def set_modelo(nome, motivo=""):
            """Handshake: define o perfil. J16 Plus tem RFID/iButton e responde
            49 bytes no GPS; o simples nao tem o leitor. Descoberto pela versao
            de firmware (contem RFID/PLUS) ou por qualquer parametro RFID* que
            volte com valor.

            `motivo` e a prova: sem ela o campo diz "J16" e o tecnico nao sabe
            se o aparelho foi mesmo reconhecido ou se e so o palpite inicial."""
            if "_modelo" in moni:
                moni["_modelo"].set(f"{nome} ({motivo})" if motivo else nome)
            if modelo[0] == nome:
                return
            modelo[0] = nome
            if nome == "Cantrack G900L":
                # Deixar 77 linhas mortas na tela nao e informacao, e ruido: o
                # tecnico fica tentando gravar campo que este firmware ignora.
                oculto_modelo.clear()
                oculto_modelo.update(c for c in ALL_COMMANDS
                                     if c not in proto.CANTRACK_PARAMS)
            elif nome == "J16 Plus":
                oculto_modelo.clear()
                oculto_modelo.update(c for c, _ in COMMANDS[GRUPO_G900L])
            else:
                oculto_modelo.update(c for grp in (GRUPO_PLUS, GRUPO_G900L)
                                     for c, _ in COMMANDS[grp])
            aplicar_filtro()
            aplicar_dialeto_monitor()
            rotulo_status()
            for f in ao_trocar_modelo:
                f(nome)
            notify(f"MODELO: {nome} identificado", tema.OK)

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
            """Limpa campos na tela -- nunca toca no rastreador. Regras:
            so mexe no que esta VISIVEL (grupo aberto, nao filtrado, do modelo
            certo); se ha campos marcados, limpa so os marcados visiveis; sem
            marcados, limpa todos os visiveis. IMEI/ICCID/IMSI e demais campos
            so-leitura ficam de fora sempre -- sao do hardware."""
            marcados = {c for c, (chk, _) in rows.items() if chk.get()}
            alvos = []
            for cmd, _desc, ws in linhas:
                if cmd in SOMENTE_LEITURA:
                    continue
                if not ws[0].winfo_viewable():      # escondido: nao conta
                    continue
                if marcados and cmd not in marcados:
                    continue
                alvos.append(cmd)
            if not alvos:
                notify("ZERAR: nenhum campo visivel para limpar", tema.ALERTA)
                return
            escopo = "marcados" if marcados else "todos os visiveis"
            if not tema.perguntar(
                    root, "Zerar campos",
                    f"Apaga o valor de {len(alvos)} campos ({escopo}) na tela.\n\n"
                    "O rastreador nao e alterado: nada e enviado.\n\nConfirma?"):
                return
            n = 0
            for cmd in alvos:
                chk, val = rows[cmd]
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
        moni_widgets = {}  # field name -> (rotulo, valor), para esconder linha

        # A aba nao rolava: com o card GPS + os blocos Rede/Veiculo/Sistema (e o
        # iButton no Plus) a coluna ficava mais alta que o notebook e o fim dela
        # -- os botoes "Ver no mapa"/"Copiar coordenada" e a nota abaixo do GPS --
        # saia cortado, sem scrollbar para alcancar. Mesmo padrao canvas+Scrollbar
        # da aba Parametros (ver `corpo`/`canvas`/`inner` acima).
        mon_corpo = ttk.Frame(mon_tab)
        mon_corpo.pack(fill="both", expand=True)
        mon_canvas = tk.Canvas(mon_corpo, highlightthickness=0, bg=tema.BG)
        mon_scroll = ttk.Scrollbar(mon_corpo, orient="vertical",
                                   command=mon_canvas.yview)
        mon_tab = tk.Frame(mon_canvas, bg=tema.BG)
        mon_tab.bind("<Configure>",
                     lambda e: mon_canvas.configure(scrollregion=mon_canvas.bbox("all")))
        mon_janela = mon_canvas.create_window((0, 0), window=mon_tab, anchor="nw")
        mon_canvas.bind("<Configure>",
                        lambda e: mon_canvas.itemconfigure(mon_janela, width=e.width))
        mon_canvas.configure(yscrollcommand=mon_scroll.set)
        mon_canvas.pack(side="left", fill="both", expand=True)
        mon_scroll.pack(side="right", fill="y")

        def _mon_wheel(e):
            top_frac, bot_frac = mon_canvas.yview()
            if top_frac <= 0.0 and bot_frac >= 1.0:
                return
            mon_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        mon_canvas.bind("<Enter>", lambda e: mon_canvas.bind_all("<MouseWheel>", _mon_wheel))
        mon_canvas.bind("<Leave>", lambda e: mon_canvas.unbind_all("<MouseWheel>"))

        def cores_estado():
            return {"ok": tema.OK, "alerta": tema.ALERTA, "erro": tema.ERRO,
                    "apagado": tema.TXT3}

        def moni_campo(parent, nome, dica, r, c=0, largura=16):
            """Uma linha rotulo/valor dentro de um card. Sem dado mostra '--'
            apagado, em vez de texto cru."""
            lbl = tk.Label(parent, text=dica, bg=tema.CARD, fg=tema.TXT2,
                           font=tema.F_TXT, anchor="w")
            lbl.grid(row=r, column=c * 2, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value="--")
            val = tk.Label(parent, text="--", bg=tema.CARD, fg=tema.TXT,
                           font=tema.F_BOLD, anchor="w", width=largura)
            val.grid(row=r, column=c * 2 + 1, sticky="w", pady=2)

            def pintar(*_):
                v = var.get().strip()
                sufixo = sufixo_do_campo(nome, v)
                val.configure(text=f"{v} {sufixo}".strip() if v else "--",
                              fg=cor_do_campo(nome, v, cores_estado())
                              or (tema.TXT3 if v in ("", "--") else tema.TXT))
            var.trace_add("write", pintar)
            moni[nome] = var
            moni_widgets[nome] = (lbl, val)
            return val

        passo_widgets, rede_ui = [], []
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
                grande = tk.Label(topo, textvariable=var, bg=tema.CARD,
                                  fg=tema.ACENTO, font=tema.F_GRANDE)
                grande.pack(side="left")
                barra = tk.Label(topo, text="", bg=tema.CARD, fg=tema.TXT2,
                                 font=tema.F_GRANDE)
                barra.pack(side="left", padx=(8, 0))
                tk.Label(topo, text=rotulo, bg=tema.CARD, fg=tema.TXT2,
                         font=tema.F_TXT).pack(side="left", padx=(8, 0), pady=(8, 0))

                def pintar_destaque(*_, nome=nome, var=var, grande=grande,
                                    barra=barra):
                    v = var.get().strip()
                    cor = cor_do_campo(nome, v, cores_estado())
                    grande.configure(fg=cor or tema.ACENTO)
                    if nome == "CSQ":
                        barra.configure(text=barra_csq(v), fg=cor or tema.TXT2)

                var.trace_add("write", pintar_destaque)
                moni[nome] = var
                linha0 = 1
            for r, (nome, rotulo) in enumerate(campos):
                # "Cantrack G900L (por VERSION#)" nao cabe na largura padrao,
                # e um nome de aparelho cortado no meio nao identifica nada
                moni_campo(caixa, nome, rotulo, r + linha0,
                           largura=30 if nome == "_modelo" else 16)
            if titulo == "Rede":
                # Fluxo ate o portal. Sinal forte com "Registrado: nao" e o caso
                # que mais custa tempo de bancada -- olhando quatro bolinhas o
                # tecnico ve em que degrau parou, em vez de somar campos de
                # cabeca.
                passos = tk.Frame(caixa, bg=tema.CARD)
                passos.grid(row=80, column=0, columnspan=6, sticky="w",
                            pady=(10, 0))
                for j, etapa in enumerate(ETAPAS_CONEXAO):
                    if j:
                        tk.Label(passos, text="›", bg=tema.CARD,
                                 fg=tema.TXT3, font=tema.F_TXT
                                 ).pack(side="left", padx=4)
                    w = tk.Label(passos, text=f"● {etapa}", bg=tema.CARD,
                                 fg=tema.TXT3, font=tema.F_TXT)
                    w.pack(side="left")
                    passo_widgets.append(w)
                dica_rede_lbl = tk.Label(caixa, text="", bg=tema.CARD,
                                         fg=tema.ALERTA, font=tema.F_TXT,
                                         wraplength=300, justify="left")
                dica_rede_lbl.grid(row=81, column=0, columnspan=6, sticky="w",
                                   pady=(8, 0))
                rede_ui.append(dica_rede_lbl)

        def revisar_rede(*_):
            """Repinta as quatro etapas e a dica. Chamada por trace nos campos
            que alimentam as duas -- nao em laco: o painel so muda quando um
            valor muda."""
            vals = {k: v.get() for k, v in moni.items()}
            cores = {"ok": tema.OK, "falha": tema.ERRO, "?": tema.TXT3}
            for w, (etapa, estado) in zip(passo_widgets, etapas_conexao(vals)):
                w.configure(text=f"● {etapa}", fg=cores[estado])
            if rede_ui:
                rede_ui[0].configure(text=dica_rede(vals))

        for _campo in ("SIM", "REG", "System Status", "Socket Send", "CSQ"):
            if _campo in moni:
                moni[_campo].trace_add("write", revisar_rede)
        revisar_rede()

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

        # Sem isto nao da para separar "o aparelho esta parado" de "o campo
        # congelou": os dois aparecem na tela como um numero que nao muda. O
        # carimbo anda a cada quadro recebido, entao hora parada = nada chegando.
        var_fonte = tk.StringVar(value="--")
        tk.Label(gps, text="Ultima leitura", bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_TXT).grid(row=91, column=0, sticky="w", pady=(6, 0))
        tk.Label(gps, textvariable=var_fonte, bg=tema.CARD, fg=tema.TXT2,
                 font=tema.F_TXT, anchor="w").grid(
                     row=91, column=1, columnspan=5, sticky="w", pady=(6, 0))

        def marcar_fonte(qual):
            var_fonte.set(f"{datetime.datetime.now():%H:%M:%S}  \u00b7  {qual}")

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
                               state="disabled", style="Cmd.TButton",
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

        # --- iButton / RFID: so o J16 Plus tem o leitor -------------------
        # O card espelha o que os parametros RFID* do aparelho responderam --
        # nao inventa uma "ultima tag", que so a plataforma recebe (0x17) e cujo
        # formato nesta porta USB nao foi confirmado. Aparece so no Plus.
        # Vai na mesma grade dos cards Rede/Veiculo/Sistema (nao embaixo do GPS):
        # a aba Monitoramento nao tem rolagem, entao um card a mais na vertical
        # ficava cortado abaixo da area visivel.
        ibut_mold, ibut = tema.card(grade, "iButton / RFID  (J16 Plus)")

        def _rfid_sn(cmd, texto):
            r = ibut.grid_size()[1]
            tk.Label(ibut, text=texto, bg=tema.CARD, fg=tema.TXT2,
                     font=tema.F_TXT, anchor="w").grid(row=r, column=0,
                                                       sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value="--")
            tk.Label(ibut, textvariable=var, bg=tema.CARD, fg=tema.TXT,
                     font=tema.F_BOLD, anchor="w").grid(row=r, column=1, sticky="w")

            def espelha(*_, c=cmd, v=var, t=texto):
                bruto = rows[c][1].get().strip() if c in rows else ""
                if t.endswith("?"):        # campo liga/desliga
                    v.set({"1": "sim", "0": "nao"}.get(bruto, bruto or "--"))
                else:
                    v.set(bruto or "--")
            if cmd in rows:
                rows[cmd][1].trace_add("write", espelha)
            espelha()

        _rfid_sn("RFIDENABLE", "Leitura de tag habilitada?")
        _rfid_sn("RFIDRECEN", "Envia leitura à plataforma?")
        _rfid_sn("RFIDNOACCT", "Término de condução (s)")
        _rfid_sn("RFIDSFDELAY", "Timer p/ armar bloqueio (s)")
        tk.Label(ibut, bg=tema.CARD, fg=tema.TXT2, font=tema.F_TXT,
                 justify="left", anchor="w", wraplength=220,
                 text="Cadastro de tag (adicionar, consultar, limpar) está em "
                      "Comandos livres → Comandos prontos. São comandos da folha "
                      "do portal SSX: se esta porta USB não responder, o resumo "
                      "avisa e o cadastro tem de ir pelo portal."
                 ).grid(row=90, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def _mostra_ibutton(nome):
            if nome == "J16 Plus":
                if not ibut_mold.winfo_manager():
                    grade.columnconfigure(3, weight=1, uniform="mon")
                    ibut_mold.grid(row=0, column=3, sticky="nsew", padx=(0, 8))
            elif ibut_mold.winfo_manager():
                ibut_mold.grid_remove()
        ao_trocar_modelo.append(_mostra_ibutton)
        _mostra_ibutton(modelo[0])       # estado inicial (escondido no J16)
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
                        marcar_fonte(f"telemetria de {porta}")
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
        # Rastreador lento ou porta USB instavel nao aguenta 2,5 perguntas por
        # segundo. "automatica" mantem o que sempre foi: 400 ms no quadro
        # binario, 1 s na resposta de texto, que e mais longa.
        TAXAS = {"automatica": None, "0,5 s": 500, "1 s": 1000,
                 "2 s": 2000, "5 s": 5000}
        taxa_var = tk.StringVar(value="automatica")
        moni_on = [None]        # after() id of the running poll, None when stopped
        moni_mudo = [0]         # polls sent since the last status frame came back
        def moni_parar(msg="MONITOR: parado", cor=tema.ERRO):
            if moni_on[0] is not None:
                root.after_cancel(moni_on[0])
                moni_on[0] = None
                notify(msg, cor)
        def moni_sem_suporte():
            """Firmware que nao implementa 0x0100/0x0101 responde "CFG CMD
            UNKNOWN" a cada pergunta. Como o ciclo pergunta 2,5 vezes por
            segundo, isso vira uma enxurrada que afoga o console e nunca vai
            virar dado. Para o monitor na primeira recusa."""
            moni_parar("MONITOR: este firmware nao tem os quadros de status "
                       "(0x0100/0x0101) -- parei de perguntar. Posicao e "
                       "velocidade, se vierem, chegam pelas linhas de texto do "
                       "proprio aparelho.", tema.ALERTA)

        def moni_ciclo(vez=0):
            """Alternate the two requests 400ms apart, so the system panel and the
            GPS panel each refresh a bit faster than once a second. The firmware
            answers requests and never streams, so asking is what keeps it live."""
            if not link.open:
                moni_parar("MONITOR: porta fechou", tema.ERRO)
                return
            if dialeto[0] == "cantrack":
                # Nao existe quadro de status binario neste firmware: o estado
                # sai de STATUS# e a posicao de WHERE#, alternados.
                pedido = proto.CANTRACK_MONITOR[vez % len(proto.CANTRACK_MONITOR)]
            else:
                op = proto.MSG_MONI_SYS if vez % 2 == 0 else proto.MSG_MONI_GPS
                pedido = f"moni:{op:04X}"
            if send_command(pedido) is False:
                moni_parar("MONITOR: falha ao enviar", tema.ERRO)
                return
            # The tracker sleeps after SLEEPT minutes and then answers nothing.
            # Say so, otherwise the panel just shows stale numbers forever.
            moni_mudo[0] += 1
            if moni_mudo[0] == 8:
                notify("MONITOR: rastreador nao responde -- provavelmente em "
                       "sleep. Mexa nele ou ligue a ignicao para acordar.", tema.ALERTA)
            # 400ms da conta do quadro binario; a resposta de texto e mais
            # longa e a porta do G900L ja se mostrou instavel -- 1s la.
            espera = TAXAS.get(taxa_var.get()) or (
                400 if dialeto[0] == "atys" else 1000)
            moni_on[0] = root.after(espera, moni_ciclo, vez + 1)

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
        # Numero parado nao diz se o aparelho esta quieto ou se o programa
        # travou. O ponto pisca a cada resposta que chega, entao ponto apagado
        # e silencio de verdade.
        pulso = ttk.Label(mon_bar, text="●", foreground=tema.TXT3)
        pulso.pack(side="left", padx=(8, 2))
        ttk.Label(mon_bar, text="a cada", foreground=tema.TXT2
                  ).pack(side="left", padx=(8, 2))
        ttk.Combobox(mon_bar, textvariable=taxa_var, values=list(TAXAS),
                     width=11, state="readonly").pack(side="left", padx=2)
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
        # O log anda sozinho ate o usuario subir nele. Com o monitor ligado sao
        # ~2 linhas por segundo: sem isso, ler qualquer coisa acima do fim e
        # impossivel -- a rolagem arranca a linha do olho no meio da leitura.
        # Tudo que ja foi escrito, para o filtro poder redesenhar sem perder
        # nada. O teto existe porque uma sessao de bancada de uma hora com o
        # monitor ligado passa de 100 mil linhas.
        LOG_MAX = 20000
        historico = []
        # Linhas que o aparelho respondeu de verdade (fora a tagarelice da pilha
        # TCP). E o que a fila de comandos usa para dizer quem respondeu: o
        # contador de VALORES nao serve, porque "CFGSZCS,APN,USERPPP" e uma
        # confirmacao legitima e nao carrega valor nenhum.
        rx_uteis = [0]
        filtro_log = tk.StringVar(value="tudo")
        busca_log_var = tk.StringVar()

        busca_row = tk.Frame(con_tab, bg=tema.BG)
        busca_row.pack(fill="x", padx=6, pady=(6, 0))
        tk.Label(busca_row, text="BUSCA", bg=tema.BG, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left", padx=(0, 6))
        busca_ent = ttk.Entry(busca_row, textvariable=busca_log_var, width=28)
        busca_ent.pack(side="left")
        ttk.Button(busca_row, text="limpar", width=8, style="Ghost.TButton",
                   command=lambda: busca_log_var.set("")).pack(side="left", padx=4)
        tk.Label(busca_row, text="EXIBIR", bg=tema.BG, fg=tema.TXT2,
                 font=tema.F_BOLD).pack(side="left", padx=(16, 6))
        ttk.Combobox(busca_row, textvariable=filtro_log, state="readonly",
                     width=24,
                     values=["tudo", "so comandos e respostas",
                             "so comandos e respostas do usuario",
                             "so erros e alertas"]).pack(side="left")

        log_box = tk.Frame(con_tab, bg=tema.BG)
        log_box.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        log = tk.Text(log_box, height=20, wrap="none", font=tema.F_MONO,
                      state="disabled", insertwidth=0, cursor="arrow",
                      bg=tema.TERM, fg=tema.LOG_NEUTRO, relief="flat",
                      padx=10, pady=8, selectbackground=tema.BORDA,
                      highlightthickness=1, highlightbackground=tema.BORDA)
        log_rol = ttk.Scrollbar(log_box, orient="vertical", command=log.yview)
        log.pack(side="left", fill="both", expand=True)
        log_rol.pack(side="right", fill="y")
        seguir_log = [True]

        def log_rolou(inicio, fim):
            """Unica fonte da verdade: a posicao da barra. No fim = segue;
            subiu = para. Voltar ao fim na mao ja religa, sem clicar em nada."""
            log_rol.set(inicio, fim)
            seguir_log[0] = float(fim) >= 0.999
            if seguir_log[0]:
                desce_btn.place_forget()
            else:
                desce_btn.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-10)

        def descer_log():
            log.see("end")
            seguir_log[0] = True
            desce_btn.place_forget()

        desce_btn = ttk.Button(log_box, text="▼ novas linhas",
                               style="Primary.TButton", command=descer_log)
        log.configure(yscrollcommand=log_rolou)
        for nome, cor in (("tx", tema.LOG_TX), ("rx", tema.LOG_RX),
                          ("err", tema.LOG_ERR), ("val", tema.LOG_VAL),
                          ("hora", tema.LOG_HORA), ("hex", tema.LOG_HORA)):
            log.tag_configure(nome, foreground=cor)
        log.tag_configure("achado", background=tema.ALERTA, foreground=tema.BG)
        # The vendor tool's "EquManage" panel. Only Reset is wired: its handler
        # in ENTools_V1067 does nothing but set opcode 0x0300, while PowerON and
        # PowerOff carry no OnClick at all in the vendor's own form -- they are
        # dead buttons there, so there is nothing to copy.
        equ_row = ttk.LabelFrame(con_tab, text="Controle do equipamento", padding=6)
        equ_row.pack(fill="x", pady=(6, 0))

        def do_reset():
            if not require_link():
                return
            if not tema.perguntar(
                    root, "Reiniciar rastreador", "Reinicia o rastreador agora.\n\n"
                    "A configuração não se perde. O aparelho some da porta por "
                    "uns 10 segundos e volta sozinho.\n\nConfirma?",
                    perigo=True):
                notify("RESET: cancelado", tema.ERRO)
                return
            moni_parar("")
            # o G900L nao fala ATYS: o quadro binario do J16 ele descarta calado
            send_command("RESET#" if dialeto[0] == "cantrack"
                         else f"moni:{proto.MSG_RESET:04X}", usuario=True)
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
            # {TAG} e o unico buraco: o comando de cadastro precisa do numero da
            # tag, e digitar a linha inteira na mao e onde o erro aparece.
            if "{TAG}" in texto:
                tag = tema.pedir_texto(
                    root, rotulo, "Numero da tag / iButton:\n"
                                  "(iButton: leia em U, da esquerda para a direita)")
                if not tag or not tag.strip():
                    notify(f"{rotulo}: cancelado", tema.ERRO)
                    return
                texto = texto.replace("{TAG}", tag.strip())
            if texto == "RFID,DL#" and not tema.perguntar(
                    root, "Limpar tags",
                    "Apaga TODAS as tags cadastradas no aparelho.\n\n"
                    "Nao tem como desfazer pelo configurador.\n\nConfirma?",
                    perigo=True):
                notify("LIMPAR TAGS: cancelado", tema.ERRO)
                return
            cmd_var.set(texto)
            on_send()
            notify(f"COMANDO PRONTO: {rotulo}", tema.OK)

        def bloco_acoes(itens, linha0):
            """Desenha os botoes em duas colunas e devolve a linha seguinte.

            Duas colunas porque numa so a lista passa do fim da aba e os ultimos
            comandos ficam inalcancaveis -- o painel nao rola."""
            metade = (len(itens) + 1) // 2
            for n, (rotulo, texto, dica) in enumerate(itens):
                alvo = (do_reset if texto in (f"moni:{proto.MSG_RESET:04X}",
                                              "RESET#")
                        else lambda t=texto, r=rotulo: disparar(t, r))
                estilo = ("Perigo.TButton" if texto in ("RFID,DL#", "RESET#")
                          else "Cmd.TButton")
                lin, col = linha0 + n % metade, (n // metade) * 2
                ttk.Button(acoes_pane, text=rotulo, width=26, command=alvo,
                           style=estilo
                           ).grid(row=lin, column=col, sticky="ew", pady=2,
                                  padx=(0, 4))
                ttk.Label(acoes_pane, text=dica, style="CardDica.TLabel",
                          wraplength=250
                          ).grid(row=lin, column=col + 1, sticky="w",
                                 padx=(8, 16))
            return linha0 + metade

        def montar_acoes(_nome=None):
            """Refaz o painel no dialeto do aparelho que esta na porta.

            Os botoes nascem antes do handshake, entao a lista do J16 e so o
            palpite inicial; quando o modelo aparece, este callback troca tudo.
            Deixar a lista errada na tela e pior que nao ter painel: o comando
            sai, o firmware ignora, e a resposta do monitor passando logo abaixo
            parece confirmacao."""
            for w in acoes_pane.winfo_children():
                w.destroy()
            if modelo[0] == "Cantrack G900L":
                bloco_acoes(ACOES_CANTRACK, 0)
                return
            fim = bloco_acoes(ACOES, 0)
            # Bloco do cadastro de tag, separado: e o unico grupo que muda estado
            # no aparelho (e so o Plus responde), entao nao se mistura com as
            # consultas de cima.
            ttk.Label(acoes_pane, style="CardDica.TLabel", wraplength=560,
                      text="── Cadastro de tag / iButton (só J16 Plus) — comandos "
                           "da folha do portal SSX; se esta porta USB não "
                           "responder, o resumo diz “sem resposta”."
                      ).grid(row=fim, column=0, columnspan=4, sticky="w",
                             pady=(10, 4))
            bloco_acoes(ACOES_RFID, fim + 1)

        montar_acoes()
        ao_trocar_modelo.append(montar_acoes)

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

        # --- comandos personalizados -------------------------------------
        # O mesmo painel dos prontos, so que a lista e do tecnico: o comando
        # que ele monta uma vez vira botao e sobrevive ao fechar o programa.
        meus = ler_meus_comandos()
        meus_pane = ttk.LabelFrame(
            con_tab, padding=6,
            text="Comandos personalizados -- os seus, salvos neste computador")

        def desenha_meus():
            for w in meus_pane.winfo_children():
                w.destroy()
            if not meus:
                ttk.Label(meus_pane, style="CardDica.TLabel", wraplength=560,
                          text="Nenhum ainda. Digite o comando no campo abaixo "
                               "(pode ter ; para varios) e clique em Salvar "
                               "comando."
                          ).grid(row=0, column=0, sticky="w", pady=2)
            for n, (rotulo, texto) in enumerate(meus):
                ttk.Button(meus_pane, text=rotulo, width=26,
                           style="Cmd.TButton",
                           command=lambda t=texto, r=rotulo: disparar(t, r)
                           ).grid(row=n, column=0, sticky="ew", pady=2, padx=(0, 4))
                ttk.Label(meus_pane, text=texto, style="CardDica.TLabel",
                          wraplength=380
                          ).grid(row=n, column=1, sticky="w", padx=(8, 8))
                ttk.Button(meus_pane, text="remover", style="Ghost.TButton",
                           command=lambda i=n: remove_meu(i)
                           ).grid(row=n, column=2, sticky="w")
            ttk.Button(meus_pane, text="＋ Salvar comando do campo abaixo",
                       style="Outline.TButton", command=salva_meu
                       ).grid(row=len(meus) + 1, column=0, columnspan=3,
                              sticky="w", pady=(8, 0))

        def salva_meu():
            texto = cmd_var.get().strip()
            if not texto:
                notify("SALVAR: digite o comando no campo de baixo primeiro",
                       tema.ERRO)
                return
            rotulo = tema.pedir_texto(
                root, "Salvar comando", f"Nome do botao para:\n\n{texto}")
            if not rotulo or not rotulo.strip():
                notify("SALVAR: cancelado", tema.ERRO)
                return
            meus.append((rotulo.strip()[:26], texto))
            if salvar_meus_comandos(meus):
                notify(f"SALVO: '{rotulo.strip()}' virou botao", tema.OK)
            else:
                notify("SALVO na tela, mas nao consegui gravar o arquivo -- "
                       "some ao fechar", tema.ALERTA)
            desenha_meus()

        def remove_meu(i):
            rotulo = meus[i][0]
            if not tema.perguntar(root, "Remover comando",
                                  f"Remover o comando '{rotulo}'?"):
                return
            meus.pop(i)
            salvar_meus_comandos(meus)
            notify(f"REMOVIDO: {rotulo}", tema.ALERTA)
            desenha_meus()

        def alterna_meus():
            if meus_pane.winfo_manager():
                meus_pane.pack_forget()
                log.configure(height=20)
                meus_btn.config(text="Comandos personalizados ▾")
            else:
                log.configure(height=6)
                desenha_meus()
                meus_pane.pack(fill="x", padx=4, pady=(4, 0), after=equ_row)
                meus_btn.config(text="Comandos personalizados ▴")

        meus_btn = ttk.Button(equ_row, text="Comandos personalizados ▾",
                              style="Outline.TButton", command=alterna_meus)
        meus_btn.pack(side="left", padx=4)
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
        # Ligado, o monitor escreve ~5 linhas por segundo e enterra o resto. O
        # filtro so vale enquanto o monitor roda, e a linha escondida nao volta
        # -- o dado dela esta no painel de telemetria, que continua atualizando.
        esconder_moni = tk.BooleanVar(value=True)
        ttk.Checkbutton(entry_row, text="ocultar ruido no log",
                        variable=esconder_moni).pack(side="right", padx=6)
        # Last value seen for each key, so a write can be logged as old -> new.
        last_values = {}
        # origem do ultimo TX: True = o usuario mandou (console/botao), False =
        # automatico (monitor, auto-leitura, aperto de mao). As respostas herdam
        # a origem do comando que as provocou, para o filtro "so do usuario".
        ultimo_tx_user = [False]

        def visivel_no_filtro(tag, usuario=False):
            f = filtro_log.get()
            if f == "so comandos e respostas":
                return tag in ("tx", "rx", "err")
            if f == "so comandos e respostas do usuario":
                return usuario and tag in ("tx", "rx", "err")
            if f == "so erros e alertas":
                return tag == "err"
            return True

        def inserir_linha(hora, line, tag):
            """Escreve uma linha ja classificada. O dump hexadecimal sai em cor
            apagada: ele dobra o comprimento da linha e quase nunca e o que se
            procura -- opaco, para de disputar o olho com o texto."""
            log.insert("end", hora, "hora")
            corpo, sep, hexa = line.partition("  [")
            log.insert("end", corpo, tag)
            if sep:
                log.insert("end", "  [" + hexa, "hex")
            log.insert("end", chr(10))

        def write_log(line, tag=None):
            if esconder_moni.get() and tag is None and (
                    (moni_on[0] is not None and linha_de_monitor(line))
                    or linha_de_ruido(line)):
                return          # laco do monitor e tagarelice do proprio aparelho
            if line.startswith("RX") and not linha_de_ruido(line):
                rx_uteis[0] += 1
            hora = f"{datetime.datetime.now():%H:%M:%S}  "
            tag = tag or cor_da_linha(line)
            usuario = ultimo_tx_user[0]
            historico.append((hora, line, tag, usuario))
            del historico[:-LOG_MAX]            # o log nao pode crescer sem fim
            if not visivel_no_filtro(tag, usuario):
                return
            log.config(state="normal")          # log is read-only for the user;
            inserir_linha(hora, line, tag)
            if seguir_log[0]:                   # parado? a nova espera la embaixo
                log.see("end")
            log.config(state="disabled")        # flip back so no caret, no typing
            destacar_busca()

        def redesenhar_log(*_):
            """Refaz o log inteiro a partir do historico. So roda quando o
            filtro muda -- por linha seria uma redesenhada por quadro."""
            log.config(state="normal")
            log.delete("1.0", "end")
            for hora, line, tag, usuario in historico:
                if visivel_no_filtro(tag, usuario):
                    inserir_linha(hora, line, tag)
            log.config(state="disabled")
            log.see("end")
            destacar_busca()

        def destacar_busca(*_):
            """Pinta de amarelo toda ocorrencia do termo buscado."""
            log.tag_remove("achado", "1.0", "end")
            termo = busca_log_var.get().strip()
            if len(termo) < 2:
                return
            inicio, achados = "1.0", 0
            while achados < 500:                # busca sem fim trava a tela
                pos = log.search(termo, inicio, "end", nocase=True)
                if not pos:
                    break
                marca = pos + "+" + str(len(termo)) + "c"
                log.tag_add("achado", pos, marca)
                inicio, achados = marca, achados + 1
        filtro_log.trace_add("write", redesenhar_log)
        busca_log_var.trace_add("write", destacar_busca)
        # Ctrl+F leva para a busca do console de qualquer aba -- e o atalho que
        # a mao ja procura sozinha.
        root.bind("<Control-f>", lambda _e: (nb.select(con_tab),
                                             busca_ent.focus_set()))

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
            tema.avisar(root, "Porta desconectada",
                        "Conecte a porta primeiro.", "alerta")
            return False
        def conferir_perigo(cmd):
            """Pergunta antes do que nao tem volta. False se o usuario desistir.

            Vale para os dois dialetos: um comando de texto perigoso nao fica
            menos perigoso por ter sido digitado a mao no console.
            """
            base = cmd.upper().rstrip("#").split(",")[0].split("=")[0].strip()
            aviso = PERIGOSOS.get(base)
            if aviso is None and base.startswith("EXTPOWSAFE"):
                aviso = PERIGOSOS["EXTPOWSAFE"]
            if aviso is None:
                return True
            if tema.perguntar(root, base, aviso + "\n\nEnviar mesmo assim?",
                              perigo=True):
                return True
            notify(f"{base}: cancelado", tema.ALERTA)
            return False

        def send_command(text, usuario=False):
            """A '=' anywhere in the text makes it a write; otherwise it is a read.
            Returns False if the write to the port failed, so a batch can stop
            instead of throwing a Tk callback exception on every remaining item.

            usuario=True marca que o comando saiu do console/botao (nao do monitor
            nem da auto-leitura), para o filtro "so do usuario" do log.
            """
            if not link.open:
                return False
            ultimo_tx_user[0] = usuario
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
            elif dialeto[0] == "cantrack":
                # O G900L recusa quadro binario. Tudo que o usuario digitar sai
                # como texto puro, inclusive "CXCS#GT06SEL", que neste firmware
                # ja E o comando de fio.
                cmd = "".join(c for c in text if 32 <= ord(c) < 127).strip()
                if not conferir_perigo(cmd):
                    return False
                payload = (cmd + "\r\n").encode("latin-1", "replace")
                write_log(f"TX  (texto) {cmd}")
            elif normalizar_comando(text)[0]:
                # '#KEY' / '#KEY=v' -> the ATYS binary config protocol. Tambem
                # entra aqui 'SZCS#KEY=v', 'CXCS#KEY' e a chave pelada.
                original, text = text, normalizar_comando(text)[0]
                forcar = normalizar_comando(original)[1]
                if original.strip() != text:
                    write_log(f"    {original.strip()}  ->  {text}")
                write = "=" in text if forcar is None else forcar == "gravar"
                if write and "=" not in text:
                    # 'SZCS#APN' parece leitura e nao e: SZCS quer dizer GRAVAR,
                    # entao isso vira um quadro de gravacao com o corpo vazio --
                    # que no firmware apaga o valor (0x0301 vazio limpa SERVIP e
                    # APN). O sintoma na tela e uma resposta vazia, facil de ler
                    # como "o aparelho nao respondeu" enquanto o campo foi pro
                    # brejo. Recusa aqui, que e por onde passam console, botao e
                    # fila, e diz o prefixo certo.
                    chave = text.lstrip("#").split("#")[0].strip()
                    notify(f"{text}: SZCS quer dizer GRAVAR, e sem '=' isso "
                           f"apagaria {chave} no aparelho. Para LER use "
                           f"CXCS#{chave} ou so #{chave}; para gravar, "
                           f"#{chave}=valor.", tema.ERRO)
                    write_log(f"    RECUSADO {text} -- gravacao sem valor apaga "
                              f"o parametro. Leitura e #{chave}.", "err")
                    return False
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
                if not conferir_perigo(cmd):
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
                conn_btn.config(text="Conectar"); set_conn_style(False)
                status.set("DESCONECTADO", tema.ERRO)
                notify(f"falha ao enviar pra porta -- {e}. A porta foi fechada; "
                       "espere uns 2s e clique Conectar.", tema.ERRO)
                return False
            return True
        def on_send(_=None):
            text = cmd_var.get().strip()
            if not (text and require_link()):
                return
            # ";" separa comandos: szcs#freq=15;szcs#pulse=15. O firmware nao
            # entende o ";" -- quem separa somos nos, um quadro por comando,
            # mesma regra da gravacao em lote que trava a porta.
            if ";" in text:
                fila = separar_comandos(text)
                cmd_var.set("")
                enviar_fila(fila, usuario=True)
                return
            if send_command(text, usuario=True) is not False:
                notify(f"COMANDO: {text} enviado -- resposta no historico acima")
            cmd_var.set("")

        def enviar_fila(fila, usuario=False):
            """Manda a fila e diz, no fim, qual comando respondeu e qual nao.
            Sem o resumo o tecnico le um historico corrido e nao sabe se o
            terceiro comando entrou."""
            marcas = []          # (comando, respostas recebidas ate aqui)

            def passo(i=0):
                if not link.open:
                    notify("porta fechou no meio da fila", tema.ERRO)
                    return
                if i >= len(fila):
                    root.after(2500, lambda: resumo())
                    return
                marcas.append([fila[i], rx_uteis[0]])
                if send_command(fila[i], usuario=usuario) is False:
                    marcas[-1][1] = None      # nem saiu
                    return
                # 1,5 s entre comandos: gravar APN, servidor ou senha REINICIA o
                # G900L, e a confirmacao volta 1 a 3 s depois. Com 500 ms a
                # resposta de um caia na conta do seguinte -- ou de ninguem.
                root.after(1500, passo, i + 1)

            def resumo():
                write_log(f"    fila de {len(fila)} comandos:")
                aceitos = 0
                for n, (cmd, antes) in enumerate(marcas):
                    proximo = (marcas[n + 1][1] if n + 1 < len(marcas)
                               else rx_uteis[0])
                    if antes is None:
                        estado = "nao enviado"
                    elif proximo is not None and proximo > antes:
                        estado, aceitos = "respondeu", aceitos + 1
                    else:
                        estado = "sem resposta"
                    write_log(f"      {cmd}  -- {estado}")
                cor = tema.OK if aceitos == len(fila) else tema.ALERTA
                notify(f"FILA: {aceitos} de {len(fila)} comandos responderam "
                       "-- detalhe no historico", cor)

            notify(f"FILA: enviando {len(fila)} comandos separados por ;")
            passo()
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
        ocupado = [""]       # nome do lote em andamento, "" quando livre

        def livre_para(oque):
            """Duas sequencias na mesma porta se atropelam: os comandos chegam
            intercalados, o firmware junta os pedacos no buffer e a conferencia
            de uma le a resposta da outra. Um lote por vez."""
            if not ocupado[0]:
                return True
            notify(f"{oque}: espere -- {ocupado[0]} ainda esta em andamento",
                   tema.ALERTA)
            return False

        def paced(items, make_text, start_msg, done_msg, passo=BATCH, espera=250,
                  depois=None, rotulo=""):
            """Walk a list through the event loop; a plain sleep would freeze the UI
            for the whole run and starve the reply reader.

            Sending is not the same as being heard: the tracker sleeps after
            SLEEPT minutes and then ignores everything. Count the replies and say
            so, otherwise an empty table looks like a working one.

            `depois` roda quando a ultima resposta ja teve tempo de chegar -- e o
            gancho de quem precisa ler o que voltou (conferencia de gravacao)."""
            notify(start_msg)
            antes = recebidos[0]
            ocupado[0] = rotulo or ocupado[0]

            def confere():
                if rotulo:
                    ocupado[0] = ""
                if recebidos[0] == antes:
                    notify("SEM RESPOSTA: o rastreador nao devolveu nada -- ele "
                           "dorme sozinho depois de alguns minutos parado. Mexa "
                           "nele ou ligue a ignicao e tente de novo.", tema.ERRO)
                elif done_msg:
                    notify(f"{done_msg} ({recebidos[0] - antes} valores recebidos)",
                           tema.OK)
                if depois is not None:
                    depois()

            def step(i=0):
                if not link.open:
                    if rotulo:
                        ocupado[0] = ""
                    if pendente[0]:
                        recuperar_porta()   # reinicio do aparelho: retoma depois
                        return
                    notify("porta fechou no meio da operacao", tema.ERRO)
                    return
                if i >= len(items):
                    root.after(1500, confere)     # let the last replies land
                    return
                if send_command(make_text(items[i:i + passo])) is False:
                    if rotulo:
                        ocupado[0] = ""
                    return          # send_command already said why on the bar
                root.after(espera, step, i + passo)
            step()
        def do_read():
            """Pull the tracker's current config. Checked rows only, or all of them."""
            if not require_link() or not livre_para("LER"):
                return
            marcados = selected()
            if dialeto[0] == "cantrack":
                alvos = ([f"CXCS#{k}" for k in marcados] if marcados
                         else list(proto.CANTRACK_LEITURA))
                escopo = "marcados" if marcados else "tudo que ele responde"
                paced(alvos, lambda lote: lote[0],
                      f"LER: {len(alvos)} consultas ({escopo})...",
                      f"LER: {len(alvos)} consultas enviadas",
                      passo=1, espera=450)
                return
            targets = list(marcados or ALL_COMMANDS)
            escopo = "marcados" if marcados else "todos"
            paced(targets, lambda batch: "".join(f"#{k}" for k in batch),
                  f"LER: pedindo {len(targets)} parametros ({escopo})...",
                  f"LER: {len(targets)} pedidos enviados -- respostas abaixo")
        def do_read_all():
            """Auto-read fired once on connect -- ignores ticks, reads everything."""
            if not link.open:
                return
            if dialeto[0] == "cantrack":
                # Um comando por vez: o G900L nao concatena chaves, e a resposta
                # dele vem em linha de texto, que chega mais devagar.
                paced(proto.CANTRACK_LEITURA, lambda lote: lote[0],
                      f"AUTO-LEITURA: {len(proto.CANTRACK_LEITURA)} consultas no "
                      "G900L...",
                      f"AUTO-LEITURA: {len(proto.CANTRACK_LEITURA)} consultas "
                      "enviadas", passo=1, espera=450)
                return
            paced(ALL_COMMANDS, lambda batch: "".join(f"#{k}" for k in batch),
                  f"AUTO-LEITURA: puxando os {len(ALL_COMMANDS)} parametros...",
                  f"AUTO-LEITURA: {len(ALL_COMMANDS)} pedidos enviados")
        def do_write():
            """Send what is on screen: checked rows, or every row that has a value."""
            if not require_link() or not livre_para("ENVIAR"):
                return
            sel = selected_cfg() or [c for c, (_, v) in rows.items()
                                     if v.get().strip() and c not in SOMENTE_LEITURA]
            if not sel:
                notify("GRAVAR: nenhum parametro preenchido", tema.ERRO)
                tema.avisar(root, "Enviar parametros",
                            "Nenhum parametro preenchido para enviar.")
                return
            pairs = ordem_de_gravacao([(c, rows[c][1].get().strip())
                                       for c in sel])
            # Regravar servidor ou APN com o valor que o aparelho ja tem custa um
            # reinicio de 13 s e nao muda nada. Ficam de fora do envio, mas
            # continuam no lote da conferencia: a tela so pode afirmar que estao
            # certos depois de ler de volta.
            enviar, ja_iguais = separar_reinicios_inuteis(pairs, last_values)
            for chave, valor in ja_iguais:
                write_log(f"      {chave}: ja esta {valor} no aparelho -- nao "
                          f"reenviado (regravar esta chave o reiniciaria)")
            if not enviar:
                notify(f"GRAVAR: os {len(pairs)} valores ja estao no aparelho "
                       "-- nada a gravar, conferindo", tema.OK)
                conferir_gravacao(pairs)
                return
            fazer_backup(len(enviar))
            resumo = ("GRAVAR: gravando "
                      + ", ".join(f"{k}={v}" for k, v in enviar[:4])
                      + (f" e mais {len(enviar) - 4}..." if len(enviar) > 4
                         else "...")
                      + (f" ({len(ja_iguais)} ja iguais, fora do envio)"
                         if ja_iguais else ""))
            # ponytail: one key per frame on writes, nos dois dialetos. BATCH=6
            # was measured on reads, where the line is just "#KEY#KEY..."; six
            # writes carry their values too and the firmware stops reading
            # mid-line -- that is the "Write timeout" right after Importar, with
            # the port dead after it. O G900L nem concatena.
            if dialeto[0] == "cantrack":
                # APN, usuario e senha viram um comando so -- separados nao grudam
                enviar = proto.juntar_apn(enviar, last_values)
                paced(enviar, lambda lote: proto.cantrack_escrita(*lote[0]),
                      resumo,
                      f"GRAVAR: {len(enviar)} gravacoes enviadas -- conferindo...",
                      passo=1, espera=450, rotulo="uma gravacao",
                      depois=lambda: conferir_gravacao(pairs))
                return
            paced(enviar, lambda batch: "".join(f"#{k}={v}" for k, v in batch),
                  resumo,
                  f"GRAVAR: {len(enviar)} gravacoes enviadas -- conferindo...",
                  passo=1, espera=400, rotulo="uma gravacao",
                  depois=lambda: conferir_gravacao(pairs))

        def recuperar_porta(tentativas=0):
            """Reconecta sozinho e termina a conferencia que ficou pela metade.

            Medido em 15/09/2026: ao gravar SERVIP o G900L reinicia, e a USB dele
            SOME da maquina 15,6 s depois do comando, voltando 5 s mais tarde no
            mesmo COM. A espera de 16 s acabava bem na hora da queda: a
            conferencia comecava com a porta morta e o tecnico via "sem resposta"
            numa gravacao que tinha dado certo. Aqui a queda deixa de ser o fim da
            operacao e vira mais um passo dela.
            """
            if not pendente[0]:
                return
            if tentativas == 0:
                dialeto_salvo[0] = dialeto[0]
                if link.open:
                    link.close()
                conn_btn.config(text="Conectar"); set_conn_style(False)
                notify("A porta caiu no reinicio do rastreador -- reconectando "
                       "sozinho para terminar a conferencia", tema.ALERTA)
            if tentativas > 40:                     # 40 x 1,5 s = 60 s
                notify("RECONEXAO: o rastreador nao voltou em 60 s. Conecte a "
                       "mao e clique Ler para ver como ficou.", tema.ERRO)
                pendente[0] = None
                refresh_ports()
                return
            # A porta DESTE painel. Pegar a primeira da lista funcionava com um
            # rastreador so; com dois, a primeira e a do outro painel -- que ja
            # esta aberta -- e a reconexao gastava os 60 s tentando abrir uma
            # porta que nunca ia ceder. O aparelho volta no mesmo COM.
            achados = detect_devices()
            meu = (port_var.get().split() or [""])[0]
            alvo = (meu if any(a.split()[0] == meu for a in achados)
                    else (achados[indice].split()[0]
                          if len(achados) > indice else ""))
            if alvo:
                try:
                    link.connect(alvo, baud_var.get())
                except Exception:
                    pass
            if not link.open:
                root.after(1500, recuperar_porta, tentativas + 1)
                return
            # E o MESMO aparelho que acabou de reiniciar: refazer o aperto de mao
            # dispararia a auto-leitura inteira por cima da conferencia.
            dialeto[0] = dialeto_salvo[0]
            sessao_iniciada[0] = True
            conn_btn.config(text="Desconectar"); set_conn_style(False)
            rotulo_status()
            notify(f"RECONECTADO em {alvo.split()[0]} -- terminando a "
                   "conferencia da gravacao", tema.OK)
            root.after(2000, lambda: _conferir_gravacao(pendente[0]))

        def esperar_aparelho(seguir, tentativas=0):
            """Segura a conferencia enquanto o rastreador estiver reiniciando.

            Gravar servidor ou APN derruba o G900L sozinho. Perguntar a um
            aparelho em boot devolve silencio, e silencio aqui virava "29 sem
            resposta" -- um relatorio de falha para uma gravacao que deu certo.
            """
            if pendente[0] and not link.open:
                recuperar_porta()               # caiu durante a espera
                return
            se_falta = ESPERA_REINICIO - (time.time() - reinicio[0])
            if reinicio[0] and se_falta > 0 and tentativas < 45:
                if tentativas == 0:
                    notify("O aparelho reiniciou sozinho depois da gravacao "
                           "(normal ao mexer em servidor, APN ou leitor de "
                           "tag) -- esperando ele voltar para conferir",
                           tema.ALERTA)
                root.after(1000, lambda: esperar_aparelho(seguir, tentativas + 1))
                return
            reinicio[0] = 0.0
            seguir()

        def conferir_gravacao(pairs):
            pendente[0] = pairs
            esperar_aparelho(lambda: _conferir_gravacao(pairs))

        def _conferir_gravacao(pairs):
            """Grava e acreditar nao e a mesma coisa: o firmware aceita o quadro,
            responde, e mesmo assim volta ao valor de fabrica (o SERVIP que
            'reseta sozinho' apareceu assim). So le de volta os campos gravados e
            compara um a um -- sucesso so quando bate.

            A releitura tem de sair no MESMO dialeto da gravacao: no G900L e
            CXCS#CHAVE, e so para as chaves que ele responde. As outras ele grava
            sem deixar perguntar -- essas ficam como 'nao confirmavel', nunca
            como falha."""
            esperado = dict(pairs)
            for k in esperado:
                last_values.pop(k, None)     # forca leitura nova, nao o eco antigo
            if dialeto[0] == "cantrack":
                legiveis = chaves_legiveis_cantrack()
                mudas = [k for k in esperado if k not in legiveis]
                alvos = consultas_cantrack([k for k in esperado if k in legiveis])
                if not alvos:
                    relatar_gravacao(esperado, mudas)
                    return
                paced(alvos, lambda lote: lote[0],
                      f"CONFERINDO: relendo {len(esperado) - len(mudas)} de "
                      f"{len(esperado)} parametros gravados...", "",
                      passo=1, espera=450, rotulo="uma conferencia",
                      depois=lambda: relatar_gravacao(esperado, mudas))
                return
            paced(list(esperado), lambda b: "".join(f"#{k}" for k in b),
                  f"CONFERINDO: relendo os {len(esperado)} parametros gravados...",
                  "", rotulo="uma conferencia",
                  depois=lambda: relatar_gravacao(esperado, ()))

        def relatar_gravacao(esperado, sem_leitura=()):
            pendente[0] = None          # a conferencia chegou ao fim
            ok, divergentes, mudos, sem_conferir = comparar_gravacao(
                esperado, last_values, sem_leitura)
            write_log(f"    conferencia: {len(ok)} confirmados, "
                      f"{len(divergentes)} divergentes, {len(mudos)} sem "
                      f"resposta, {len(sem_conferir)} nao confirmaveis")
            for k, queria, veio in divergentes:
                write_log(f"      {k}: gravei {queria}, o aparelho tem {veio}"
                          "  (NAO GRAVOU)")
            for k in mudos:
                write_log(f"      {k}: sem resposta na releitura")
            for k in sem_conferir:
                write_log(f"      {k}: gravado -- este aparelho nao devolve esta "
                          "chave, nao da para conferir")
            if divergentes or mudos:
                notify(f"GRAVAR: {len(ok)} de {len(esperado)} confirmados -- "
                       f"{len(divergentes)} nao gravaram, {len(mudos)} sem "
                       "resposta. Veja o historico.", tema.ERRO)
            elif sem_conferir:
                notify(f"GRAVAR: {len(ok)} confirmados; {len(sem_conferir)} "
                       "gravados que este aparelho nao deixa reler "
                       "(SERVIP, APN e afins) -- confira no portal.", tema.ALERTA)
            else:
                notify(f"GRAVAR: os {len(ok)} parametros foram gravados e "
                       "conferidos no aparelho.", tema.OK)
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
                tema.avisar(root, "Exportar", f"Nao salvou o arquivo:\n{e}", "erro")
                return
            notify(f"EXPORTAR: {len(values)} parametros salvos em {path}", tema.OK)
        def aplicar_config(items, titulo, descartadas=0):
            """Enche a tela com {CHAVE: valor} e grava na hora se a porta ja
            estiver aberta -- caminho comum do Importar e do Carregar modelo:
            plugar, carregar, pronto."""
            # The dict becomes the selection: leftover ticks from a previous
            # read would ride along and get written too, and nobody asked for
            # those. Clear first, then tick exactly what this brought.
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
            resumo = (f"{titulo.upper()}: {len(aplicados)} parametros na tela"
                      + (f", {len(ignorados)} desconhecidos ignorados" if ignorados else "")
                      + (f", {len(protegidos)} de identificacao preservados" if protegidos else "")
                      + (f", {descartadas} linhas fora do padrao" if descartadas else ""))
            if suspeitos:
                # conferido e reprovado -- fica na tela para o tecnico olhar,
                # mas nada e enviado sozinho
                notify(resumo + f", {len(suspeitos)} valores suspeitos -- NAO enviei",
                       tema.ERRO)
                tema.avisar(
                    root, titulo,
                    "Tem valores que nao parecem validos, entao nada foi "
                    "enviado:\n\n"
                    + "\n".join(suspeitos[:10])
                    + "\n\nCorrija e tente de novo, ou ajuste na tela e clique "
                      "Enviar parametros.")
                return
            if not aplicados:
                notify(resumo + " -- nada para enviar", tema.ERRO)
                return
            if not link.open:
                notify(resumo + " -- conecte a porta e clique Enviar parametros",
                       tema.ALERTA)
                return
            notify(resumo + " -- conferido, gravando...", tema.OK)
            do_write()
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
                tema.avisar(root, "Importar",
                            f"Nao consegui ler o arquivo:\n{e}", "erro")
                return
            if not items:
                notify("IMPORTAR: nenhuma linha CHAVE=VALOR reconhecida", tema.ERRO)
                tema.avisar(root, "Importar",
                            "O arquivo nao tem linhas no formato CHAVE=VALOR.",
                            "erro")
                return
            aplicar_config(items, "Importar", descartadas)
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
        def iniciar_sessao():
            """Leitura completa e monitor, no dialeto que o aperto de mao achou.

            Chamada pelos dois caminhos -- pela resposta do VERSION# e pelo
            tempo limite -- e por isso ela mesma se tranca depois da primeira.
            """
            if sessao_iniciada[0] or not link.open:
                return
            sessao_iniciada[0] = True
            if dialeto[0] == "atys":
                set_modelo("J16", "nao respondeu VERSION#")
            notify("lendo os parâmetros e ligando o monitor", tema.OK)
            do_read_all()
            root.after(1200, moni_iniciar)
            buscar_chip()

        def buscar_chip():
            """ICCID, IMSI e operadora pela porta modem, sem atrapalhar a leitura.

            Numa thread porque abrir porta serial bloqueia, e com root.after para
            voltar ao Tk: a porta do chip e outra, entao isso roda em paralelo
            com a leitura dos parametros na porta de configuracao.
            """
            device = (port_var.get().split() or [""])[0]
            if not device:
                return

            def aplicar(achados):
                for chave, valor in achados.items():
                    if chave in rows:
                        rows[chave][1].set(valor)
                        last_values[chave] = valor
                    else:
                        write_log(f"      {chave.lstrip('_')} = {valor}")
                if achados:
                    notify(f"CHIP: {len(achados)} campos lidos pela porta modem",
                           tema.OK)

            def trabalho():
                try:
                    achados = ler_chip(device)
                except Exception:
                    achados = {}
                root.after(0, lambda: aplicar(achados))

            threading.Thread(target=trabalho, daemon=True).start()

        def toggle_conn():
            if link.open:
                link.close()
                conn_btn.config(text="Conectar"); set_conn_style(False)
                status.set("DESCONECTADO", tema.ERRO)
                notify("Porta fechada", tema.ERRO)
                refresh_ports()
                return
            try:
                link.connect(port_var.get().split()[0], baud_var.get())
            except Exception as e:
                notify(f"Não abriu a porta -- {e}", tema.ERRO)
                tema.avisar(root, "Conectar", f"Não abriu a porta:\n{e}", "erro")
                set_conn_style(False)
                return
            conn_btn.config(text="Desconectar"); set_conn_style(False)
            set_conn_style(False)
            dialeto[0] = "atys"
            sessao_iniciada[0] = False
            set_modelo("J16", "perguntando quem e")
            rotulo_status()
            notify(f"Conectado em {port_var.get().split()[0]} @ {baud_var.get()} "
                   "-- identificando o aparelho", tema.OK)
            # Primeiro o aperto de mao, depois o resto. Mandar quadro binario
            # para um G900L so enche o log de "CFG CMD UNKNOWN", e mandar texto
            # para um J16 nao responde nada -- entao ninguem fala antes de saber
            # com quem esta falando. VERSION# e a pergunta: so o G900L responde.
            root.after(300, lambda: send_command(proto.CANTRACK_VERSAO))
            # Se ninguem responder, e J16: segue no dialeto binario de sempre.
            root.after(1800, iniciar_sessao)
        def set_conn_style(ready):
            if link.open:
                # porta aberta: o unico caminho deste botao e derrubar a sessao
                conn_btn.config(style="Danger.TButton", cursor="hand2")
            else:
                conn_btn.config(
                    style="Primary.TButton" if ready else "Outline.TButton",
                    cursor="hand2" if ready else "")
            # porta e velocidade sao escolha de antes de conectar: mexer com a
            # sessao aberta so derruba a conexao por engano
            estado = "disabled" if link.open else "normal"
            atualizar_btn.config(state=estado)
            baud_cb.config(state="disabled" if link.open else "readonly")
            port_cb.config(state=estado)
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
        # Dentro da aba Parametros, nao no rodape do painel: tudo aqui mexe na
        # TABELA. Mesmo motivo que levou Salvar/Limpar log para dentro do
        # console. No rodape sobra o banner de status, que vale para as tres abas.
        bar = ttk.Frame(par_tab, padding=(6, 8))
        # Hierarquia: gravar e a acao principal, ler e secundaria, arquivo e
        # discreto. Assim o tecnico acha o botao certo sem ler os cinco.
        # Dois assuntos diferentes: o que fala com o rastreador e o que mexe
        # em arquivo. Separados, ninguem exporta querendo gravar.
        _topico(bar, "RASTREADOR")
        ttk.Button(bar, text="Gravar", style="Primary.TButton",
                   command=do_write).pack(side="left")
        ttk.Button(bar, text="Ler", style="Outline.TButton",
                   command=do_read).pack(side="left", padx=6)
        copy_btn = ttk.Button(bar, text="Copiar parametros ▴",
                              style="Ghost.TButton", command=lambda: copy_menu())
        copy_btn.pack(side="left", padx=2)
        _divisor(bar)
        _topico(bar, "CONFIGURAÇÃO")
        ttk.Button(bar, text="Importar", style="Ghost.TButton",
                   command=do_import).pack(side="left", padx=2)
        ttk.Button(bar, text="Exportar", style="Ghost.TButton",
                   command=do_export).pack(side="left", padx=2)
        # Metade da largura nao cabe os tres grupos numa linha so: o MODELO
        # saia pela direita e o botao Carregar simplesmente nao existia na tela.
        bar2 = bar if quantos < 2 else ttk.Frame(par_tab, padding=(6, 0))
        if bar2 is bar:
            _divisor(bar)
        _topico(bar2, "MODELO")
        modelo_var = tk.StringVar()
        modelo_cb = ttk.Combobox(bar2, textvariable=modelo_var, width=14,
                                 state="readonly",
                                 values=sorted(ler_modelos().keys()))
        modelo_cb.pack(side="left", padx=2)
        def refresh_modelos():
            modelo_cb.config(values=sorted(ler_modelos().keys()))
        def do_salvar_modelo():
            nome = tema.pedir_texto(root, "Salvar modelo",
                                    "Nome do modelo:")
            if not nome:
                notify("MODELO: cancelado", tema.ERRO)
                return
            values = {c: limpo_ascii(v.get()) for c, (_, v) in rows.items()
                      if v.get().strip() and c not in SOMENTE_LEITURA}
            if not values:
                notify("MODELO: nenhum parametro preenchido para salvar",
                       tema.ERRO)
                return
            modelos = ler_modelos()
            modelos[nome] = values
            if not salvar_modelos(modelos):
                notify("MODELO: nao consegui salvar", tema.ERRO)
                tema.avisar(root, "Salvar modelo",
                            "Nao consegui gravar o arquivo de modelos.", "erro")
                return
            refresh_modelos()
            modelo_var.set(nome)
            notify(f"MODELO: '{nome}' salvo com {len(values)} parametros",
                   tema.OK)
        todos_var = tk.BooleanVar(value=False)
        def do_carregar_modelo():
            # o fluxo rapido: plugar o rastreador novo, clicar Carregar,
            # pronto -- ja aplica e grava se a porta estiver aberta. Com
            # "todas as portas" marcado, replica no(s) outro(s) painel(is)
            # conectado(s) que baterem o mesmo modelo -- ate 2 ao mesmo
            # tempo, que e o maximo que o app abre lado a lado.
            nome = modelo_var.get()
            if not nome:
                notify("MODELO: escolha um modelo na lista", tema.ERRO)
                return
            modelos = ler_modelos()
            if nome not in modelos:
                notify(f"MODELO: '{nome}' nao existe mais na pasta -- "
                       "atualizando lista", tema.ERRO)
                refresh_modelos()
                return
            items = modelos[nome]
            aplicar_config(items, f"Modelo {nome}")
            if not todos_var.get():
                return
            outros = [p for p in paineis if p.indice != indice]
            gravados, pulados = [], []
            for p in outros:
                if not p.link.open:
                    pulados.append(f"painel {LETRAS[p.indice]} (nao conectado)")
                    continue
                if p.modelo[0] != modelo[0]:
                    pulados.append(f"painel {LETRAS[p.indice]} "
                                   f"({p.modelo[0]}, esperava {modelo[0]})")
                    continue
                p.carregar(items, f"Modelo {nome}")
                gravados.append(f"painel {LETRAS[p.indice]}")
            if gravados or pulados:
                notify(f"MODELO: replicado em {', '.join(gravados) or 'nenhum'}"
                       + (f" -- pulei {'; '.join(pulados)}" if pulados else ""),
                       tema.OK if gravados else tema.ALERTA)
        ttk.Button(bar2, text="Salvar", style="Ghost.TButton",
                   command=do_salvar_modelo).pack(side="left", padx=2)
        ttk.Button(bar2, text="Carregar", style="Primary.TButton",
                   command=do_carregar_modelo).pack(side="left", padx=2)
        ttk.Checkbutton(bar2, text="todas as portas", variable=todos_var
                        ).pack(side="left", padx=(2, 0))
        def limpar_log():
            historico.clear()
            log.config(state="normal")
            log.delete("1.0", "end")
            log.config(state="disabled")
        def salvar_log():
            """Grava o historico INTEIRO, nao o que o filtro deixa ver -- log
            pela metade anexado num chamado tecnico nao prova nada."""
            if not historico:
                notify("SALVAR LOG: nada para salvar", tema.ALERTA)
                return
            caminho = filedialog.asksaveasfilename(
                defaultextension=".txt", filetypes=[("Texto", "*.txt")],
                initialfile=f"log J16 {datetime.datetime.now():%Y-%m-%d %H-%M-%S}.txt")
            if not caminho:
                return
            with open(caminho, "w", encoding="utf-8") as f:
                for hora, line, _tag, _u in historico:
                    f.write(hora + line + chr(10))
            notify(f"SALVAR LOG: {len(historico)} linhas em {caminho}", tema.OK)

        # Ficam no topo do console, nao no rodape dos parametros: sao acoes do
        # terminal, e no rodape competiam com Enviar/Ler sem ter nada a ver.
        ttk.Button(busca_row, text="Limpar log", style="Ghost.TButton",
                   command=limpar_log).pack(side="right")
        ttk.Button(busca_row, text="Salvar log", style="Ghost.TButton",
                   command=salvar_log).pack(side="right", padx=6)
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
        if bar2 is not bar:
            bar2.pack(side="bottom", fill="x")   # empilha de baixo para cima
        bar.pack(side="bottom", fill="x")
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
        reinicio = [0.0]     # hora do ultimo sinal de reinicio vindo do aparelho
        pendente = [None]    # gravacao esperando conferencia, mesmo se a porta cair
        dialeto_salvo = [""]  # dialeto de antes da queda: e o mesmo aparelho
        pedaco = [""]        # resposta de texto que chegou pela metade
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
                    conn_btn.config(text="Conectar"); set_conn_style(False)
                    status.set("DESCONECTADO", tema.ERRO)
                    if pendente[0]:
                        recuperar_porta()
                        continue
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
                        # Uma resposta longa as vezes chega partida: o
                        # ">>cmdAckStr:SERVER:1,www.gps2828.com" vem numa linha e
                        # o ",7018,0;SERVER:0,...;, len:55" na seguinte. Metade da
                        # resposta nao tem campos suficientes para o parser, e o
                        # resto nem comeca com cmdAckStr -- era assim que SERVIP e
                        # SERVPORT sumiam da conferencia. O ", len:N" e o fim de
                        # verdade: sem ele, a linha continua.
                        juntou = bool(pedaco[0])
                        if juntou:
                            txt, pedaco[0] = pedaco[0] + txt, ""
                        if "cmdAckStr:" in txt:
                            # so UMA linha de espera: se o resto nao veio na
                            # seguinte, processa o que tem. Guardar indefinidamente
                            # grudaria a resposta num log solto do aparelho.
                            if ", len:" not in txt and not juntou:
                                pedaco[0] = txt
                                continue
                            write_log(f"RX  (texto) {txt}")
                            resposta = txt.split("cmdAckStr:", 1)[1]
                            resposta = resposta.rsplit(", len:", 1)[0].strip()
                            responder_cantrack(resposta)
                            continue
                        if linha_de_reinicio(txt):
                            if not reinicio[0]:
                                # so na primeira linha do boot: o aparelho
                                # imprime dezenas delas e a traducao viraria
                                # ruido repetido
                                write_log("      traducao: o aparelho esta se "
                                          "REINICIANDO sozinho -- e o que ele "
                                          "faz ao gravar servidor, APN ou "
                                          "leitor de tag. Ele nao responde "
                                          "nada ate voltar.", "err")
                            reinicio[0] = time.time()
                        if txt.startswith("-->"):
                            # linha do log de diagnostico (<ZDRCMD*LOG:1>): traz
                            # DIF (impacto), MIL (odometro), ICCID, IMSI, CSQ...
                            # Sem isto ela ia para o log como texto e sumia.
                            responder_cantrack(txt)
                            continue
                        tranco = proto.parse_shake(txt)
                        if tranco:
                            # O G900L avisa cada solavanco por conta propria.
                            # Sem isto a linha ia para o log como texto solto e
                            # o campo Movimento ficava vazio para sempre.
                            write_log(f"RX  (sensor) {txt}")
                            for nome, valor in tranco.items():
                                if nome in moni:
                                    moni[nome].set(valor)
                            continue
                        campos = proto.parse_texto_gps(txt)
                        if not campos:
                            # Hex junto: se um dia isto for o evento de leitura de
                            # iButton (ainda nao confirmado nesta porta), o texto
                            # latin-1 sozinho pode vir ilegivel -- o hex nunca mente.
                            write_log(f"RX  (texto) {txt}  [{hexdump(crua)}]")
                            if "CFG CMD UNKNOWN" in txt.upper():
                                # mesma coisa que o 0xF002 do lado binario, so
                                # que escrita: o firmware ENTENDEU o quadro e
                                # respondeu que nao conhece o opcode. Sem esta
                                # linha parece falha de comunicacao, e o tecnico
                                # fica reenviando o que nunca vai responder.
                                write_log("      traducao: o aparelho recebeu o "
                                          "quadro e disse que NAO conhece esse "
                                          "opcode neste firmware -- reenviar nao "
                                          "muda nada.", "err")
                                moni_sem_suporte()
                            continue
                        write_log(f"RX  (posicao em texto) {txt}")
                        marcar_fonte("linha de texto da porta de configuracao")
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
                            marcar_fonte("quadro 0x8101 da porta de configuracao")
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
                        # Handshake do modelo: a versao do Plus traz RFID/PLUS
                        # no nome, e so o Plus responde os parametros RFID*.
                        if ((key == "SOFTVERSION"
                             and any(t in value.upper() for t in ("RFID", "PLUS")))
                                or (key.startswith("RFID") and value.strip())):
                            set_modelo("J16 Plus",
                                       "firmware" if key == "SOFTVERSION"
                                       else f"{key} respondeu")
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

        def vigia_portas(antes=None):
            """Hotplug: so reescaneia quando a lista de portas do sistema muda.

            Sem isto o tecnico tinha de clicar "atualizar" -- ou reabrir o
            programa -- a cada aparelho que entra na bancada. Comparar a lista
            antes de agir e o que impede o painel de piscar aviso a cada 2s.
            """
            agora = ports()
            if antes is not None and agora != antes:
                refresh_ports()
            root.after(2000, lambda: vigia_portas(agora))

        vigia_portas()

        def bate(ultimo=[0]):
            """Pisca o ponto quando o contador de valores recebidos anda.

            Comparar o contador em vez de pendurar no caminho de recepcao deixa
            o drain() como estava -- e o drain e o unico lugar que nao pode
            ganhar trabalho por quadro.
            """
            if recebidos[0] != ultimo[0]:
                ultimo[0] = recebidos[0]
                pulso.configure(foreground=tema.OK)
                root.after(200, lambda: pulso.configure(foreground=tema.TXT3))
            root.after(300, bate)

        bate()
        return SimpleNamespace(link=link, rows=rows, notify=notify,
                               refresh=refresh_ports, indice=indice,
                               moni_parar=moni_parar, enviar=send_command,
                               modelo=modelo, carregar=aplicar_config,
                               # ganchos de teste: ensaiar uma gravacao inteira
                               # sem clicar, inclusive a queda da porta
                               gravar=do_write, historico=historico,
                               dialeto=dialeto, pendente=pendente,
                               conectar=toggle_conn)

    # One panel per tracker found, two at most -- past that the columns get too
    # narrow to read and the table is the whole point.
    quantos = max(1, min(2, len(detect_devices())))
    frames = []
    for i in range(quantos):
        painel = ttk.Frame(paned)
        paned.add(painel, weight=1)
        frames.append(painel)
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
        b.notify(f"CLONAR: {copiados} parametros vieram do painel {LETRAS[origem]}"
                 " -- confira e clique Enviar parametros", tema.OK)

    rodape = ttk.Frame(root, padding=(8, 4))
    rodape.grid(row=1, column=0, sticky="ew")

    vista = tk.StringVar(value="AB")

    def aplicar_vista():
        """Esconde um painel sem fechar a porta dele.

        `forget` tira o quadro do PanedWindow e nada mais: a conexao, o monitor
        e os valores lidos continuam vivos, entao voltar para "A + B" mostra o
        painel do jeito que ele estava. Meia tela para cada um aperta as duas
        tabelas; quem esta conferindo um aparelho so quer a largura inteira.
        """
        alvo = vista.get()
        for i, f in enumerate(frames):
            quer = alvo in ("AB", LETRAS[i])
            tem = str(f) in paned.panes()
            if quer and not tem:
                # "end", nao o indice: o Tk recusa insert num indice igual ao
                # numero de paineis ("Slave index 1 out of bounds") e o erro
                # abortava o resto do laco -- o painel B nunca voltava.
                pos = i if i < len(paned.panes()) else "end"
                paned.insert(pos, f, weight=1)
            elif not quer and tem:
                paned.forget(f)

    def reabrir_configurador():
        """Fecha as portas e sobe o programa de novo.

        Quantos paineis existem e decidido na abertura: montar (ou destruir) um
        painel com a janela viva significaria refazer barra de porta, notebook,
        log e leitor de fundo no ar. Reabrir custa 3 s e nao tem canto escuro.
        """
        for p in paineis:
            try:
                p.moni_parar()
                p.link.close()
            except Exception:
                pass
        root.destroy()
        # porta fechada antes: o processo novo precisa dela livre
        if getattr(sys, "frozen", False):
            os.execv(sys.executable, [sys.executable])
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)

    if len(paineis) > 1:
        _topico(rodape, "VER")
        for rot, val in (("so A", "A"), ("so B", "B"), ("A + B", "AB")):
            ttk.Radiobutton(rodape, text=rot, value=val, variable=vista,
                            command=aplicar_vista).pack(side="left", padx=2)
        _divisor(rodape)
        ttk.Button(rodape, text="Copiar  A → B",
                   command=lambda: clonar(0, 1)).pack(side="left", padx=4)
        ttk.Button(rodape, text="Copiar  B → A",
                   command=lambda: clonar(1, 0)).pack(side="left", padx=4)
        aviso_clone = ttk.Label(
            rodape, foreground=tema.TXT2,
            text="clona a configuracao de um painel no outro (so na tela)")
        aviso_clone.pack(side="left", padx=10)
        botao_um = ttk.Button(
            rodape, style="Primary.TButton",
            text="So um rastreador na bancada -- reabrir em painel unico",
            command=reabrir_configurador)
        sumiu = [0]

        def vigia_bancada():
            """Oferece o painel unico quando o segundo aparelho some de vez.

            30 s de ausencia, nao 2: o G900L desaparece da USB por uns 20 s cada
            vez que reinicia depois de uma gravacao, e oferecer "reabrir" no meio
            disso jogaria fora a conferencia que esta esperando ele voltar. Por
            isso tambem nao conta enquanto algum painel tem gravacao pendente.
            """
            ocupado = any(p.pendente[0] for p in paineis)
            sozinho = len(detect_devices()) < 2 and not ocupado
            sumiu[0] = sumiu[0] + 1 if sozinho else 0
            quer_botao = sumiu[0] >= 15              # 15 x 2 s
            if quer_botao and not botao_um.winfo_ismapped():
                aviso_clone.pack_forget()
                botao_um.pack(side="left", padx=10)
            elif not quer_botao and botao_um.winfo_ismapped():
                botao_um.pack_forget()
                aviso_clone.pack(side="left", padx=10)
            root.after(2000, vigia_bancada)

        vigia_bancada()
    else:
        aviso_um = ttk.Label(
            rodape, foreground=tema.TXT2,
            text="Um rastreador detectado. Plugue um segundo para configurar "
                 "os dois lado a lado.")
        aviso_um.pack(side="left")

        botao_dois = ttk.Button(rodape, style="Primary.TButton",
                                text="Dois rastreadores na bancada -- reabrir "
                                     "lado a lado",
                                command=reabrir_configurador)

        def vigia_bancada():
            """Aparelho plugado depois de abrir nao cria painel sozinho.

            Antes isso era silencio: o tecnico clicava "atualizar" e nada
            acontecia. Agora o rodape troca o aviso por um botao -- ele decide
            a hora, porque reabrir joga fora o que estiver preenchido na tela.
            """
            achou_dois = len(detect_devices()) > 1
            if achou_dois and not botao_dois.winfo_ismapped():
                aviso_um.pack_forget()
                botao_dois.pack(side="left")
            elif not achou_dois and botao_dois.winfo_ismapped():
                botao_dois.pack_forget()
                aviso_um.pack(side="left")
            root.after(2000, vigia_bancada)

        vigia_bancada()

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
    # gravar so e sucesso quando a releitura bate -- o caso do SERVIP que
    # "reseta sozinho" tem de cair em divergente, nunca em confirmado
    ok, div, mudos, _nc = comparar_gravacao(
        {"FREQ": "15", "SERVIP": "203.0.113.10", "APN": "x.br"},
        {"FREQ": "15", "SERVIP": "58.61.156.56"})
    assert ok == ["FREQ"], ok
    assert div == [("SERVIP", "203.0.113.10", "58.61.156.56")], div
    assert mudos == ["APN"], mudos
    # lixo da serial nao pode virar divergencia falsa
    assert comparar_gravacao({"FREQ": "15"}, {"FREQ": "15\x00 "})[0] == ["FREQ"]
    # G900L: o que ele grava mas nao le e "nao confirmavel", NUNCA falha -- senao
    # uma gravacao boa aparece como erro so porque nao da para perguntar de volta
    _legiveis = chaves_legiveis_cantrack()
    # SERVIP/APN nao saem por CXCS# -- saem por SERVER# e APN#, medido no
    # aparelho em 14-09-2026. Sem isso a tela do G900L ficava com 5 campos vazios
    assert {"PULSE", "SERVIP", "APN"} <= _legiveis, _legiveis
    assert consultas_cantrack(["SERVIP", "SERVPORT", "PULSE"]) == \
        ["SERVER#", "CXCS#PULSE"]
    assert consultas_cantrack(["FREQ"]) == ["TIMER#"]
    # FREQ sai do TIMER, nos dois formatos que o G900L usou de verdade
    assert freq_do_timer("20,3600") == "20"                    # PARAM#
    assert freq_do_timer("20s,ACC OFF:3600s") == "20"          # TIMER#
    assert freq_do_timer("") is None and freq_do_timer(None) is None
    # o filtro do log tem de pegar o laco do monitor inteiro -- pergunta, eco do
    # firmware, resposta e os valores soltos -- sem levar junto o que o tecnico
    # mandou. Um comando pronto durante o monitor e o caso que nao pode sumir
    for _l in ("TX  (texto) STATUS#", "TX  (texto) WHERE#",
               "RX  (texto) 2026-09-14 18:38:16  [LOG]==>ZdrCmd,0; str:STATUS#",
               "RX  (texto) >>cmdAckStr:Battery:4.29V;Exvkk:12.23,0;, len:83",
               "RX  (texto) >>cmdAckStr:LastPosition! Lati:S20.4,W54.5",
               "      lat = -20.459364", "      gid = 11", "      rele = solto",
               f"TX  moni:{proto.MSG_MONI_GPS:04X}"):
        assert linha_de_monitor(_l), _l
    for _l in ("TX  (texto) SERVER#", "RX  (texto) >>cmdAckStr:APN:em,,, len:8",
               "      SERVIP = www.gps2828.com", "      PULSE = 20",
               "COMANDO PRONTO: Servidor e APN"):
        assert not linha_de_monitor(_l), _l
    assert linha_de_ruido("RX  (texto) 2026-09-15 [SOCKET](0) TCP cb SOC_CLOSE")
    assert linha_de_ruido("RX  (texto) >>>socket_close:11, getCode:107")
    # ruido do uplink quando conectado ao servidor: pacote cru e KKS
    assert linha_de_ruido("RX  (texto) 78781F121A0910062518CA0231F08D0D0A  [..]")
    assert linha_de_ruido("RX  (texto) 2026-09-16 14:28:30  KKS_REV::  [..]")
    assert linha_de_ruido("RX  (texto) 2026-09-16 14:28:32  KKS_his_send:  [..]")
    assert not linha_de_ruido("RX  (texto) >>cmdAckStr:SPDADD:ON,10,2, len:16")
    assert not linha_de_ruido("RX  (texto) >>cmdAckStr:SETOK: VIBL=1, len:13")
    assert not linha_de_ruido("TX  (texto) SZCS#VIBL=1")
    # os botoes do G900L so podem falar o dialeto dele: "#" no fim (ou CXCS#).
    # Um "#CHAVE" do J16 aqui sai pela porta e some sem resposta -- foi o que
    # acontecia antes, com a lista do J16 aparecendo para o G900L
    for _rot, _txt, _ in ACOES_CANTRACK:
        for _c in separar_comandos(_txt):
            # AT+ZDR= e <ZDRCMD*...> sao os dois canais de servico achados no
            # binario do fabricante e confirmados no aparelho -- nao terminam
            # em "#" e nem por isso estao errados.
            assert (_c.endswith("#") or _c.upper().startswith("CXCS#")
                    or _c.upper().startswith("AT+ZDR=")
                    or _c.startswith("<ZDRCMD*")), (_rot, _c)
            assert not _c.startswith("#"), (_rot, _c)
    # Toda chave da tabela do G900L tem de ter de onde vir. As de baixo nao
    # vem de comando de texto: ICCID e IMSI saem da porta modem (ler_chip) e do
    # log de diagnostico, GPS_VER e MIL (odometro) so do log de diagnostico.
    _sem_comando = {"ICCID", "IMSI", "GPS_VER", "MIL"}
    assert set(proto.CANTRACK_PARAMS) - _sem_comando <= _legiveis, \
        set(proto.CANTRACK_PARAMS) - _sem_comando - _legiveis
    _ok, _div, _mudos, _nconf = comparar_gravacao(
        {"PULSE": "20", "SERVIP": "203.0.113.10", "APN": "x.br"},
        {"PULSE": "20"},
        sem_leitura={"SERVIP", "APN"})
    assert _ok == ["PULSE"] and not _div and not _mudos, (_ok, _div, _mudos)
    assert _nconf == ["SERVIP", "APN"], _nconf
    # ";" separa comandos; vazio e espaco nao viram comando fantasma
    assert separar_comandos("szcs#freq=15; szcs#pulse=15 ;;") == \
        ["szcs#freq=15", "szcs#pulse=15"]
    # todo comando de tag ou e completo ou pede o numero -- nunca manda {TAG}
    for _r, _t, _d in ACOES_RFID:
        assert _t.endswith("#") and _t.count("{TAG}") <= 1, _t
    # comandos salvos sobrevivem ao fechar o programa, e arquivo corrompido
    # devolve lista vazia em vez de derrubar a abertura
    import tempfile
    global pasta_backup
    _pasta_real = pasta_backup
    with tempfile.TemporaryDirectory() as _tmp:
        pasta_backup = lambda: _tmp
        try:
            _meus = [("Ler APN", "#APN"), ("Fila", "szcs#freq=15;szcs#pulse=15")]
            assert salvar_meus_comandos(_meus)
            assert ler_meus_comandos() == _meus, ler_meus_comandos()
            with open(arquivo_meus_comandos(), "w", encoding="utf-8") as _f:
                _f.write("{json quebrado")
            assert ler_meus_comandos() == []
        finally:
            pasta_backup = _pasta_real
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
    assert "FREQ" in marcaveis and len(marcaveis) == 96, len(marcaveis)
    # o grupo do G900L so serve se o proprio G900L o mostrar: uma chave fora de
    # CANTRACK_PARAMS entra na tabela e o filtro de modelo a esconde logo depois
    g900l = [c for c, _ in COMMANDS[GRUPO_G900L]]
    assert set(g900l) <= proto.CANTRACK_PARAMS, set(g900l) - proto.CANTRACK_PARAMS
    assert set(g900l) <= set(chaves_legiveis_cantrack()), "sem releitura"
    assert proto.cantrack_escrita("SENALM", "OFF") == "SENALM,OFF#"
    # diagnostico do painel: as regras nao dependem de interface nenhuma
    _cores = {"ok": "verde", "alerta": "amarelo", "erro": "vermelho",
              "apagado": "cinza"}
    assert _primeiro_numero("14 (fraco)") == 14 and _primeiro_numero("4.30V") == 4.3
    assert _primeiro_numero("--") is None
    assert barra_csq("14 (fraco)") == "▮▮▮▯▯", barra_csq("14")
    assert barra_csq("31 (otimo)").count("▮") == 5
    assert barra_csq("99 (sem leitura)") == ""      # sem leitura nao acende nada
    assert pct_bateria("4.30V") == 100 and pct_bateria("3.8V") == 50
    assert pct_bateria("--") is None
    assert sufixo_do_campo("Battery", "4.30V") == "(100%)"
    assert sufixo_do_campo("CSQ", "14") == ""
    assert cor_do_campo("CSQ", "14 (fraco)", _cores) == "amarelo"
    assert cor_do_campo("CSQ", "31 (otimo)", _cores) == "verde"
    assert cor_do_campo("CSQ", "4 (ruim)", _cores) == "vermelho"
    assert cor_do_campo("Voltage", "12.43 V", _cores) == "verde"
    assert cor_do_campo("Voltage", "0.00 V", _cores) == "vermelho"
    assert cor_do_campo("Voltage", "23.8 V", _cores) == "verde"     # 24 V
    assert cor_do_campo("Battery", "3.5V", _cores) == "vermelho"
    assert cor_do_campo("REG", "nao registrado", _cores) == "vermelho"
    assert cor_do_campo("REG", "registrado", _cores) == "verde"
    assert cor_do_campo("Power", "ausente", _cores) == "vermelho"
    assert cor_do_campo("Sleep", "dormindo", _cores) == "amarelo"
    # G900L manda o parametro, nao o estado: configuracao nao e alarme
    assert cor_do_campo("Sleep", "habilitado", _cores) == "verde"
    assert cor_do_campo("Mileage", "0KM", _cores) is None   # campo sem regra
    assert cor_do_campo("CSQ", "--", _cores) is None
    # o caso da bancada: sinal chega, chip nao registra
    _tela = {"CSQ": "14 (fraco)", "REG": "nao", "System Status": "Offline"}
    assert dict(etapas_conexao(_tela)) == {"Chip": "?", "Torre": "falha",
                                           "Dados": "falha", "Servidor": "falha"}
    assert "nao registra" in dica_rede(_tela)
    _bom = {"CSQ": "25", "REG": "registrado", "System Status": "Normal Connect",
            "SIM": "presente", "Socket Send": "7"}
    assert dict(etapas_conexao(_bom)) == {"Chip": "ok", "Torre": "ok",
                                          "Dados": "ok", "Servidor": "ok"}
    assert dica_rede(_bom) == "" and dica_rede({}) == ""

    # classificacao das linhas do console
    assert cor_da_linha("TX  (texto) STATUS#") == "tx"
    assert cor_da_linha("RX  (texto) >>cmdAckStr:APN:em,,") == "rx"
    assert cor_da_linha("RX  (texto) CFG CMD UNKNOWN!!!") == "err"
    assert cor_da_linha("RX  (texto) NOT POS MOVING ON FAIL") == "err"
    assert cor_da_linha("ERRO  porta fechou") == "err"
    assert cor_da_linha("      FREQ = 20") == "val"

    _lote = [("FREQ", "20"), ("SERVIP", "a"), ("APN", "b")]
    _lidos = {"SERVIP": "a", "APN": "outra", "FREQ": "20"}
    _enviar, _iguais = separar_reinicios_inuteis(_lote, _lidos)
    # FREQ igual continua indo (reenviar e barato); SERVIP igual fica de fora
    assert _enviar == [("FREQ", "20"), ("APN", "b")], _enviar
    assert _iguais == [("SERVIP", "a")], _iguais
    assert separar_reinicios_inuteis(_lote, {}) == (_lote, [])

    # gravacao: o que reinicia o aparelho vai por ultimo, sem embaralhar o resto
    _pares = [("SERVIP", "a"), ("FREQ", "20"), ("APN", "b"), ("PULSE", "30")]
    assert ordem_de_gravacao(_pares) == [("FREQ", "20"), ("PULSE", "30"),
                                         ("SERVIP", "a"), ("APN", "b")]
    assert ordem_de_gravacao([]) == []
    assert linha_de_reinicio("==>>app_user_reset:10")
    assert linha_de_reinicio("2000-01-01 00:01:06  [LOG]==>Restart_type:10")
    assert linha_de_reinicio("******Power-on information******")
    assert not linha_de_reinicio(">>cmdAckStr:SETOK: SLEEPT=0, len:15")

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
    # SZCS sem "=" e gravacao de corpo vazio: quem envia isso apaga o parametro
    # achando que leu. O guard vive em send_command; aqui fica registrado que a
    # combinacao (forcar gravar, sem "=") existe e precisa continuar barrada.
    assert normalizar_comando("SZCS#APN") == ("#APN", "gravar")
    assert normalizar_comando("CXCS#APN") == ("#APN", "ler")
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
    assert not valor_suspeito("60") and not valor_suspeito("multigetrak.br")
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

    # o guarda de comandos sem volta e unico para os dois dialetos -- se alguem
    # tirar um nome daqui, o console volta a mandar direto
    for _perigoso in ("FACTORY", "RESET", "RELAY", "LOCK", "SETPWD",
                      "SERVEROFF", "EXTPOWSAFE"):
        assert _perigoso in PERIGOSOS, _perigoso
    assert "VERSION" not in PERIGOSOS and "STATUS" not in PERIGOSOS

    print("j16gui selftest ok -", len(ALL_COMMANDS), "comandos,",
          sum(len(l) for l in MONI_SISTEMA) + len(MONI_GPS), "campos de monitor")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        selftest()
    else:
        run_gui()
