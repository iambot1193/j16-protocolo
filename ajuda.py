#!/usr/bin/env python3
"""Ajuda contextual por grupo e por campo do Configurador J16.

Conteudo separado da GUI so para nao inchar j16gui. Cada campo tem no maximo
tres linhas -- o que faz, o formato e um exemplo -- porque um popover que vira
paragrafo ninguem le. O que nao tem verbete cai no fallback, que monta a ajuda
a partir da descricao curta e do tipo do campo.
"""

# Uma frase por grupo, dita para quem nunca mexeu.
GRUPO = {
    "Servidor e APN": (
        "Para onde o rastreador manda a posicao e por qual chip ele sai para "
        "a internet. Errar aqui e o aparelho nao aparecer na plataforma."),
    "Rastreamento": (
        "De quanto em quanto tempo ele posiciona, e o que faz ele mandar um "
        "envio fora desse tempo: uma curva, uma parada, excesso de velocidade."),
    "Ignicao e bloqueio": (
        "Como ele sabe que o carro ligou (fio laranja ou acelerometro) e como "
        "corta o combustivel quando voce manda bloquear."),
    "Economia (sleep)": (
        "Quando o aparelho dorme para gastar menos bateria, e o que continua "
        "ligado enquanto dorme."),
    "Vibracao": (
        "O sensor de movimento interno: o quao sensivel ele e e o que um "
        "tranco dispara -- alerta, GPS, envio."),
    "Alarmes SMS": (
        "Quais eventos viram SMS ou ligacao para os numeros SOS. Tudo aqui e "
        "0 desligado / 1 ligado, fora os proprios numeros."),
    "Protocolo": (
        "O formato dos pacotes que ele manda para a plataforma. So mexa se a "
        "plataforma pedir um protocolo especifico."),
    "RFID / iButton (so J16 Plus)": (
        "Leitor de tag para identificar motorista. O J16 simples nao tem "
        "leitor, entao aqui nao responde nada."),
    "Audio / escuta": (
        "Microfone: a partir de que ruido ele dispara e quanto espera para "
        "disparar de novo."),
    "Informacoes do dispositivo": (
        "Identidade do aparelho e do chip. So leitura -- nunca e gravado."),
    "Acesso e diversos": (
        "Senha, telefone e ajustes soltos que nao couberam nos outros grupos."),
}

# (o que faz, formato, exemplo). Exemplo vazio quando nao faz sentido.
CAMPO = {
    "SERVIP": ("Endereco IP do servidor que recebe a posicao.",
               "IP ou dominio", "203.0.113.10"),
    "SERVPORT": ("Porta TCP desse servidor.", "1 a 65535", "5023"),
    "DNS_ENABLE": ("Liga a resolucao de nome: use so se o servidor for dominio, "
                   "nao IP.", "0 nao / 1 sim", ""),
    "SERV2_ADDR": ("Endereco de um segundo servidor (DNS). Nesta operacao nao "
                   "se usa -- deixe vazio.", "IP ou dominio", ""),
    "SERV2_PORT": ("Porta do segundo servidor. Nao se usa.", "1 a 65535", ""),
    "APN": ("APN do chip -- e o que da internet ao aparelho. Vem da operadora "
            "ou da revenda do chip.", "texto", "operadora.exemplo.br"),
    "USERPPP": ("Usuario do APN, se a operadora exigir.", "texto", "usuario"),
    "PWPPP": ("Senha do APN, se a operadora exigir.", "texto", "senha"),
    "NETSELECT": ("Em que rede ele registra.", "0/1/2 (ver opcoes)", ""),

    "FREQ": ("Com a ignicao LIGADA, de quantos em quantos segundos ele manda a "
             "posicao.", "segundos", "15"),
    "ACC_OFF_FREQ": ("Com a ignicao DESLIGADA, de quantos em quantos segundos "
                     "ele manda posicao. Costuma ser bem maior, para poupar.",
                     "segundos", "3600"),
    "PULSE": ("Batimento: de quanto em quanto tempo ele avisa a plataforma que "
              "esta vivo, mesmo sem se mexer.", "segundos", "15"),
    "ANGLE_SEND": ("Manda um envio extra quando o carro faz uma curva. Deixa o "
                   "trajeto no mapa mais fiel.", "0 nao / 1 sim", ""),
    "ANGLEVALUE": ("A curva que dispara o envio: intervalo minimo e angulo.",
                   "intervalo-angulo", "02-015"),
    "SPEED": ("Limite de velocidade. Acima disso ele pode gerar alerta.",
              "km/h (0 desliga)", "100"),
    "GPS_FINTER_EN": ("Filtro que segura a posicao tremendo quando o carro esta "
                      "parado (antiestrelamento).", "0 nao / 1 sim", ""),
    "BLIND_EN": ("Guarda a posicao mesmo sem sinal e envia quando o sinal "
                 "volta, para nao abrir buraco no trajeto.", "0 nao / 1 sim", ""),
    "GMT_SET": ("Fuso horario do aparelho.", "sinal+HH+MM", "W0400 (Mato Grosso "
                "do Sul)"),
    "TIMING_RESET": ("Reinicia sozinho todo dia a meia-noite.", "0 nao / 1 sim",
                     ""),

    "ACCLINE": ("Como ele detecta ignicao.", "0/1/17 (ver opcoes)", ""),
    "ACCLOCK": ("Trava a saida de bloqueio quando a ignicao desliga.",
                "0 nao / 1 sim", ""),
    "ACCLT": ("Tempo entre desligar a ignicao e a trava agir.", "segundos", "3"),
    "SOURCE_OFF_TYPE": ("Como o corte de combustivel acontece.",
                        "0/1 (ver opcoes)", ""),
    "POF": ("Alerta por SMS quando a energia externa e cortada.",
            "0 nao / 1 sim", ""),
    "LED_ENABLE": ("Liga o LED de status do aparelho.", "0 nao / 1 sim", ""),

    "SLEEPT": ("Minutos parado ate ele entrar em sono para poupar bateria.",
               "minutos", "3"),
    "SLPDISCONNECT": ("O que ele desliga quando dorme.", "0/1/2 (ver opcoes)",
                      ""),
    "MTK_DISSLP": ("Mantem o rastreador ligado mesmo dormindo.",
                   "0 nao / 1 sim", ""),
    "GPS_DISSLP": ("Mantem o GPS ligado mesmo dormindo.", "0 nao / 1 sim", ""),

    "VIBL": ("Sensibilidade do sensor de movimento: menor = mais sensivel.",
             "1 a 10 (aprox.)", "3"),
    "VIBCHK": ("Janela de checagem: tempo e quantidade de movimento para "
               "considerar que mexeu.", "tempo:movimento", "10:3"),
    "VIB": ("Alerta de vibracao por SMS.", "0 nao / 1 sim", ""),
    "VIBCALL": ("Alerta de vibracao por ligacao.", "0 nao / 1 sim", ""),

    "SOS_SMS_EN": ("Manda SMS para os numeros SOS nos alertas.", "0 nao / 1 sim",
                   ""),
    "SOS_CALL_EN": ("Liga para os numeros SOS nos alertas.", "0 nao / 1 sim", ""),
    "ACC_SMS_EN": ("Avisa por SMS quando liga/desliga a ignicao.",
                   "0 nao / 1 sim", ""),
    "SPDSMSEN": ("Avisa por SMS quando passa do limite de velocidade.",
                 "0 nao / 1 sim", ""),

    "PTL_SEL": ("Protocolo dos pacotes para a plataforma.", "0/1/2 (ver opcoes)",
                ""),
    "808SEL": ("Variante do protocolo JT808.", "0/1 (ver opcoes)", ""),
    "GT06ICCID": ("Manda o numero do chip (ICCID) junto.", "0 nao / 1 sim", ""),
    "GT06METER": ("Liga o odometro no pacote.", "0 nao / 1 sim", ""),
    "GT06IEXVOL": ("Manda tensao de entrada e de bateria no pacote.",
                   "0 nao / 1 sim", ""),

    "VOICE_CTRL_EN": ("Liga a escuta por microfone.", "0 desliga / 1 liga", ""),
    "VOICE_DB_VALUE": ("A partir de quantos decibeis o ruido dispara.",
                       "dB", "80"),
    "VOICE_DB_TIME": ("Segundos acima do limiar para disparar.", "segundos", "1"),
    "VOICE_REDO_DELAY": ("Espera antes de poder disparar de novo.",
                         "segundos", "0"),

    "IMEI": ("Numero de serie do aparelho na rede. So leitura.", "so leitura",
             ""),
    "ICCID": ("Numero do chip. So leitura.", "so leitura", ""),
    "IMSI": ("Identidade do assinante do chip. So leitura.", "so leitura", ""),
    "TERIID": ("ID do terminal. So leitura.", "so leitura", ""),
    "SOFTVERSION": ("Versao do firmware do aparelho. So leitura.", "so leitura",
                    ""),
    "USER": ("Nome de usuario livre para anotacao.", "texto", ""),
    "PSW": ("Senha do aparelho. So leitura aqui.", "so leitura", ""),
}


# O que CADA opcao de um seletor faz, e quando usar. E aqui que o popover
# deixa de listar o obvio e passa a ensinar.
OPCOES_AJUDA = {
    "NETSELECT": {
        "0": "Deixa o aparelho escolher a rede: usa 4G e cai para 2G se "
             "precisar. E o mais robusto -- na duvida, use este.",
        "1": "Forca so 4G. Mais rapido, mas se a area nao tem 4G o aparelho "
             "fica sem conexao.",
        "2": "Forca so 2G. Rede antiga, cobertura ampla e menos bateria; boa "
             "onde nao ha 4G.",
    },
    "ACCLINE": {
        "0": "Ignicao virtual: o aparelho deduz que ligou pela tensao, sem fio. "
             "Use quando nao da para puxar o fio de ignicao.",
        "1": "Ignicao fisica: le o fio laranja no pos-chave. E a mais confiavel "
             "-- prefira sempre que puder puxar o fio.",
        "17": "Ignicao virtual pelo acelerometro: detecta o veiculo se mexendo. "
              "Util em reboque sem chave, mas erra mais (falso ligado).",
    },
    "PTL_SEL": {
        "0": "Protocolo TQ (Tianqin/H02): formato antigo de alguns fabricantes. "
             "So use se a plataforma exigir H02.",
        "1": "JT808: padrao chines de rastreamento veicular. Use se a "
             "plataforma pedir JT808.",
        "2": "GT06: o mais comum nas plataformas brasileiras (Getrak e afins). "
             "Na duvida, e este.",
    },
    "808SEL": {
        "0": "Norma JT808 de 2011. So vale se PTL_SEL estiver em JT808; "
             "escolha conforme a plataforma.",
        "1": "Norma JT808 de 2013, com mais campos. Use se a plataforma pedir "
             "a versao nova.",
    },
    "SOURCE_OFF_TYPE": {
        "0": "Corte condicionado: o bloqueio espera uma condicao segura (sem "
             "fix ou acima de ~20 km/h ele adia). Protege o motorista.",
        "1": "Corte imediato: bloqueia na hora do comando, sem esperar. Use com "
             "criterio -- cortar em movimento e risco.",
    },
    "SLPDISCONNECT": {
        "0": "Nunca desconecta: sempre online. Gasta mais bateria, mas responde "
             "na hora.",
        "1": "Ao dormir, sai do portal mas ainda recebe SMS. Economiza dados e "
             "mantem comando por SMS.",
        "2": "Ao dormir, sai do portal e do SMS. Economia maxima -- so volta "
             "quando acorda.",
    },
    "GMT_SET": {
        "E0000": "UTC (GMT 0). A maioria das plataformas espera isto e converte "
                 "para o horario local. Recomendado.",
        "W0300": "GMT-3, horario de Brasilia -- a maior parte do Brasil.",
        "W0400": "GMT-4: Mato Grosso do Sul, Mato Grosso e parte do Amazonas.",
        "W0500": "GMT-5: Acre e oeste do Amazonas.",
    },
}


def do_campo(cmd, descricao, tipo, opcoes=None, respondeu=True, so_leitura=False):
    """Monta as linhas do popover de um campo.

    `opcoes` = lista [(codigo, texto)] quando o campo e um seletor; ai cada
    escolha vira uma linha comparativa -- e o "izinho proprio" do NETSELECT.
    Devolve (titulo, [linhas]).
    """
    verbete = CAMPO.get(cmd)
    linhas = []
    if verbete:
        oq, fmt, ex = verbete
        linhas.append(oq)
        linhas.append("")
        linhas.append(f"Formato: {fmt}")
        if ex:
            linhas.append(f"Exemplo: {ex}")
    else:
        linhas.append(descricao)
        linhas.append("")
        linhas.append(f"Tipo: {tipo}")
    if opcoes:
        linhas.append("")
        expl_opcoes = OPCOES_AJUDA.get(cmd, {})
        if expl_opcoes:
            linhas.append("O que cada opcao faz:")
        else:
            linhas.append("Opcoes:")
        for codigo, texto in opcoes:
            linhas.append(f"   {codigo} = {texto}")
            detalhe = expl_opcoes.get(codigo)
            if detalhe:
                linhas.append("EXPL:" + detalhe)
    if not respondeu:
        linhas.append("")
        linhas.append("Obs: nao respondeu no firmware V5.56 -- pode ser so de "
                      "escrita, ou este aparelho nao ter a funcao.")
    if so_leitura:
        linhas.append("")
        linhas.append("So leitura: aparece para consulta, nunca e gravado.")
    return cmd, linhas


def tipo_do_campo(cmd, liga_desliga, escolhas, so_leitura):
    if so_leitura:
        return "so leitura"
    if cmd in liga_desliga:
        return "0 desligado / 1 ligado"
    if cmd in escolhas:
        return "uma das opcoes abaixo"
    return "texto ou numero"


# O que a aba Comandos livres aceita, do simples ao detalhado -- para o botao
# de ajuda de la. Cada item e (titulo, corpo).
CONSOLE = [
    ("O basico",
     "Aqui voce fala direto com o rastreador. Digite um comando, aperte Enter "
     "e a resposta aparece no historico acima."),
    ("Ler um parametro",
     "Digite o nome com # na frente:\\n\\n"
     "   #APN            le o APN\\n"
     "   #FREQ#PULSE     le varios de uma vez\\n\\n"
     "Ou so o nome, sem nada:  APN"),
    ("Gravar um parametro",
     "Ponha = e o valor:\\n\\n"
     "   #FREQ=15                    grava 15 no FREQ\\n"
     "   #APN=operadora.exemplo.br   grava o APN\\n\\n"
     "O historico mostra o valor antigo e o novo."),
    ("Do jeito do fabricante",
     "Se voce esta acostumado com a ferramenta antiga, os prefixos dela "
     "funcionam igual:\\n\\n"
     "   SZCS#APN=x.br   grava (SZCS = gravar)\\n"
     "   CXCS#APN        le    (CXCS = ler)"),
    ("Comandos sem botao",
     "Todo comando pode ser digitado aqui, mesmo os que nao tem botao na tela. "
     "PARAM#, STATUS#, RELAY,1# e outros sao de SMS e de plataforma: o console "
     "envia, mas esta porta USB geralmente nao responde a eles. Voce vera isso "
     "anotado no historico."),
    ("Opcode e bytes crus",
     "Para os comandos de status e evento, use moni:\\n\\n"
     "   moni:0100   status do sistema\\n"
     "   moni:0101   posicao do GPS\\n\\n"
     "E para mandar bytes exatos:  hex:59 53 00 ..."),
    ("O quadro por tras",
     "#FREQ vira este quadro no fio:\\n\\n"
     "   ATYS 5953 ...01 0202 0005 2346524551 07 0D0A\\n\\n"
     "0202 e o tipo (ler), 0005 o tamanho, 2346... o texto \\"#FREQ\\". Por isso "
     "0x0202 sozinho nao faz nada: e uma etiqueta interna, nao um comando."),
]


def selftest():
    import j16gui as g
    # todo campo tem verbete ou cai no fallback sem quebrar
    for grp, cmds in g.COMMANDS.items():
        assert grp in GRUPO, grp
        for cmd, desc in cmds:
            tipo = tipo_do_campo(cmd, g.LIGA_DESLIGA, g.ESCOLHAS,
                                 cmd in g.SOMENTE_LEITURA)
            titulo, linhas = do_campo(cmd, desc, tipo)
            assert titulo == cmd and len(linhas) >= 3, cmd
    # seletor mostra as opcoes comparadas
    _t, linhas = do_campo("NETSELECT", "rede", "opcoes",
                          opcoes=g.ESCOLHAS["NETSELECT"])
    assert any("so 4G" in l for l in linhas), linhas
    # cada opcao vem com uma explicacao do que faz, nao so o rotulo
    assert any(l.startswith("EXPL:") and "robusto" in l for l in linhas), linhas
    _t, lpt = do_campo("PTL_SEL", "protocolo", "opcoes",
                       opcoes=g.ESCOLHAS["PTL_SEL"])
    assert any("brasileiras" in l for l in lpt), lpt
    # nao-confirmado e so-leitura ganham o aviso
    _t, l2 = do_campo("PHONE", "telefone", "texto", respondeu=False)
    assert any("V5.56" in x for x in l2)
    assert len(CONSOLE) >= 6 and all(len(c[1]) > 30 for c in CONSOLE)
    print("ajuda selftest ok -", len(CAMPO), "verbetes,", len(GRUPO), "grupos")


if __name__ == "__main__":
    selftest()
