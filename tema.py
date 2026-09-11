#!/usr/bin/env python3
"""Modern Industrial / Dark Telemetry skin for the J16 configurator.

Pure ttk + tk primitives, no extra dependency: the tool ships as a single exe
and a widget library would mean rewriting every widget in j16gui, which is the
one thing the refactor must not touch. 'clam' is the only stock theme that
honours background, border and padding on every element, so everything here is
built on top of it.

Nothing in this module knows about the tracker -- it only paints.
"""
import os
import tkinter as tk
from tkinter import ttk

# --- paletas ----------------------------------------------------------------
# Os nomes sao os mesmos nos dois modos; so os valores mudam. Todo o resto do
# programa fala por nome (tema.BG, tema.ACENTO), entao trocar de modo e trocar
# estes valores e repintar.
PALETAS = {
    "escuro": dict(
        BG="#0F172A", CARD="#1E293B", CARD_ALT="#172033", INPUT="#0B0F19",
        BORDA="#334155", BORDA_FORTE="#475569",
        TXT="#F8FAFC", TXT2="#94A3B8", TXT3="#64748B",
        ACENTO="#06B6D4", ACENTO_ESC="#0891B2", ACENTO_TXT="#062A33",
        OK="#10B981", ERRO="#EF4444", ALERTA="#F59E0B",
    ),
    "claro": dict(
        BG="#EEF2F7", CARD="#FFFFFF", CARD_ALT="#E2E8F0", INPUT="#F8FAFC",
        BORDA="#CBD5E1", BORDA_FORTE="#9AA8BC",
        TXT="#0F172A", TXT2="#475569", TXT3="#94A3B8",
        ACENTO="#0E7490", ACENTO_ESC="#155E75", ACENTO_TXT="#F0FDFF",
        OK="#047857", ERRO="#B91C1C", ALERTA="#B45309",
    ),
}

# O terminal fica escuro nos dois modos: e um terminal, e as cores de log
# perdem contraste em fundo claro.
TERM = "#050811"
LOG_TX = "#38BDF8"      # comando enviado
LOG_RX = "#4ADE80"      # resposta recebida
LOG_ERR = "#F87171"     # erro / timeout
LOG_NEUTRO = "#94A3B8"
LOG_VAL = "#E2E8F0"     # valores lidos
LOG_HORA = "#64748B"    # carimbo de hora

MODO = "escuro"
globals().update(PALETAS[MODO])

FONTE = "Segoe UI"
MONO = "Consolas"
F_TXT = (FONTE, 9)
F_BOLD = (FONTE, 9, "bold")
F_TIT = (FONTE, 10, "bold")
F_GRANDE = (FONTE, 18, "bold")
F_MONO = (MONO, 9)

ARQ_PREF = os.path.join(os.path.expanduser("~"), ".configurador_j16")


def modo_salvo():
    """Preferencia da ultima vez. Escuro se nunca escolheu ou se der erro."""
    try:
        with open(ARQ_PREF, encoding="utf-8") as f:
            m = f.read().strip()
        return m if m in PALETAS else "escuro"
    except OSError:
        return "escuro"


def salvar_modo(modo):
    try:
        with open(ARQ_PREF, "w", encoding="utf-8") as f:
            f.write(modo)
    except OSError:
        pass            # preferencia e conforto, nao pode derrubar o programa


def trocar(root, modo):
    """Troca a paleta e repinta o que ja esta na tela.

    Os widgets ttk se atualizam sozinhos quando o estilo muda. Os widgets tk
    (cards, banner, badge) carregam a cor gravada, entao a arvore e percorrida
    trocando cor antiga por cor nova -- assim nenhum ponto de criacao precisa
    saber que existe troca de tema.
    """
    global MODO
    if modo not in PALETAS or modo == MODO:
        return MODO
    antes = dict(PALETAS[MODO])
    MODO = modo
    globals().update(PALETAS[modo])
    de_para = {antes[k]: PALETAS[modo][k] for k in antes}
    aplicar(root)
    _repintar(root, de_para)
    salvar_modo(modo)
    return MODO


_OPCOES = ("background", "foreground", "insertbackground", "selectbackground",
           "highlightbackground", "activebackground", "activeforeground",
           "troughcolor", "disabledforeground")


def _repintar(w, de_para):
    if isinstance(w, Badge):
        w.fundo = de_para.get(w.fundo, w.fundo)
        w._cor = de_para.get(w._cor, w._cor)
        w.configure(bg=w.fundo)
        w._pintar()
        return
    for opcao in _OPCOES:
        try:
            valor = str(w.cget(opcao))
        except Exception:
            continue
        novo = de_para.get(valor)
        if novo:
            try:
                w.configure(**{opcao: novo})
            except Exception:
                pass
    for filho in w.winfo_children():
        _repintar(filho, de_para)


def aplicar(root, modo=None):
    """Paints the whole app. Call once, right after the Tk() root exists."""
    global MODO
    if modo and modo in PALETAS:
        MODO = modo
        globals().update(PALETAS[modo])
    root.configure(bg=BG)
    st = ttk.Style(root)
    st.theme_use("clam")

    st.configure(".", background=BG, foreground=TXT, fieldbackground=INPUT,
                 bordercolor=BORDA, lightcolor=BG, darkcolor=BG,
                 troughcolor=INPUT, font=F_TXT)

    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=CARD)
    st.configure("Cab.TFrame", background=CARD_ALT)
    st.configure("Term.TFrame", background=TERM)

    st.configure("TLabel", background=BG, foreground=TXT, font=F_TXT)
    st.configure("Card.TLabel", background=CARD, foreground=TXT)
    st.configure("Dica.TLabel", background=BG, foreground=TXT2)
    st.configure("CardDica.TLabel", background=CARD, foreground=TXT2)
    st.configure("Apagado.TLabel", background=BG, foreground=TXT3)
    st.configure("Titulo.TLabel", background=CARD_ALT, foreground=ACENTO,
                 font=F_TIT)
    st.configure("Valor.TLabel", background=CARD, foreground=TXT, font=F_BOLD)
    st.configure("ValorGrande.TLabel", background=CARD, foreground=ACENTO,
                 font=F_GRANDE)
    st.configure("Alerta.TLabel", background=BG, foreground=ALERTA)
    st.configure("Erro.TLabel", background=BG, foreground=ERRO)
    st.configure("Ok.TLabel", background=BG, foreground=OK)

    # --- botoes: tres niveis de hierarquia ---------------------------------
    st.configure("TButton", background=CARD, foreground=TXT, borderwidth=1,
                 focusthickness=0, padding=(12, 6), font=F_TXT,
                 relief="flat", bordercolor=BORDA)
    st.map("TButton",
           background=[("pressed", BORDA), ("active", BORDA)],
           bordercolor=[("active", BORDA_FORTE)])

    st.configure("Primary.TButton", background=ACENTO, foreground=ACENTO_TXT,
                 font=F_BOLD, bordercolor=ACENTO)
    st.map("Primary.TButton",
           background=[("pressed", ACENTO_ESC), ("active", ACENTO_ESC)],
           foreground=[("disabled", TXT3)])

    st.configure("Outline.TButton", background=BG, foreground=ACENTO,
                 bordercolor=ACENTO)
    st.map("Outline.TButton",
           background=[("pressed", CARD), ("active", CARD)],
           foreground=[("disabled", TXT3)])

    # Ghost com superficie: sem borda nenhuma, no tema claro ele vira texto
    # solto e ninguem descobre que da para clicar.
    st.configure("Ghost.TButton", background=CARD, foreground=TXT2,
                 bordercolor=BORDA, borderwidth=1, relief="solid",
                 padding=(10, 5))
    st.map("Ghost.TButton",
           background=[("pressed", CARD_ALT), ("active", CARD_ALT)],
           bordercolor=[("active", ACENTO)],
           foreground=[("active", TXT)])

    # Botao dentro de card: o TButton normal usa CARD de fundo e some quando o
    # card tambem e CARD. Este tem contraste e borda visivel.
    st.configure("Cmd.TButton", background=CARD_ALT, foreground=TXT,
                 bordercolor=BORDA_FORTE, borderwidth=1, relief="solid",
                 padding=(10, 6), anchor="w")
    st.map("Cmd.TButton",
           background=[("pressed", BORDA), ("active", BORDA)],
           foreground=[("active", ACENTO)],
           bordercolor=[("active", ACENTO)])

    st.configure("Perigo.TButton", background=BG, foreground=ERRO,
                 bordercolor=ERRO)
    st.map("Perigo.TButton", background=[("active", "#2A1015")])

    # --- campos -------------------------------------------------------------
    for nome in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(nome, fieldbackground=INPUT, background=INPUT,
                     foreground=TXT, bordercolor=BORDA, insertcolor=ACENTO,
                     arrowcolor=TXT2, padding=4, relief="flat")
        st.map(nome,
               bordercolor=[("focus", ACENTO), ("hover", BORDA_FORTE)],
               fieldbackground=[("readonly", INPUT), ("disabled", CARD)],
               foreground=[("disabled", TXT3)])
    # Campo com valor ainda nao gravado no rastreador: borda e texto ambar.
    # O nome da linha tambem ganha bolinha, mas quem esta digitando olha para o
    # campo, nao para o rotulo ao lado.
    st.configure("Sujo.TEntry", fieldbackground=INPUT, foreground=ALERTA,
                 bordercolor=ALERTA, insertcolor=ALERTA, padding=4,
                 relief="flat")
    st.map("Sujo.TEntry", bordercolor=[("focus", ALERTA), ("hover", ALERTA)],
           foreground=[("disabled", TXT3)])
    st.configure("Sujo.TCombobox", fieldbackground=INPUT, foreground=ALERTA,
                 bordercolor=ALERTA, arrowcolor=ALERTA, padding=4,
                 relief="flat")
    st.map("Sujo.TCombobox", bordercolor=[("focus", ALERTA), ("hover", ALERTA)],
           fieldbackground=[("readonly", INPUT)])

    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACENTO)
    root.option_add("*TCombobox*Listbox.selectForeground", ACENTO_TXT)

    # clam desenha o indicador com indicatorbackground/foreground -- sem isso
    # o quadradinho fica branco no meio do tema escuro
    for nome, fundo in (("TCheckbutton", BG), ("Card.TCheckbutton", CARD),
                        ("TRadiobutton", BG), ("Card.TRadiobutton", CARD)):
        st.configure(nome, background=fundo, foreground=TXT,
                     indicatorbackground=INPUT, indicatorforeground=ACENTO,
                     bordercolor=BORDA, focusthickness=0, padding=2)
        st.map(nome,
               background=[("active", fundo)],
               indicatorbackground=[("selected", INPUT), ("active", CARD_ALT),
                                    ("disabled", CARD)],
               indicatorforeground=[("selected", ACENTO)],
               bordercolor=[("selected", ACENTO), ("active", BORDA_FORTE)],
               foreground=[("disabled", TXT3)])

    # --- abas planas com linha de destaque na ativa -------------------------
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
    st.configure("TNotebook.Tab", background=BG, foreground=TXT2,
                 padding=(18, 9), borderwidth=0, font=F_TXT)
    st.map("TNotebook.Tab",
           background=[("selected", CARD), ("active", CARD_ALT)],
           foreground=[("selected", ACENTO), ("active", TXT)],
           font=[("selected", F_BOLD)])

    st.configure("TLabelframe", background=CARD, bordercolor=BORDA,
                 borderwidth=1, relief="solid")
    st.configure("TLabelframe.Label", background=CARD, foreground=ACENTO,
                 font=F_BOLD)

    st.configure("Vertical.TScrollbar", background=CARD, troughcolor=BG,
                 bordercolor=BG, arrowcolor=TXT2, relief="flat")
    st.map("Vertical.TScrollbar", background=[("active", BORDA)])
    st.configure("TPanedwindow", background=BG)
    st.configure("Sash", background=BORDA)
    st.configure("TSeparator", background=BORDA)
    st.configure("Topico.TLabel", background=BG, foreground=TXT3,
                 font=(FONTE, 8, "bold"))
    return st


def mistura(cor, fundo, alfa):
    """Cor sobre fundo com 'alfa' de opacidade. O tk nao tem canal alfa, entao
    transparencia aqui e mistura de verdade: e o que permite uma marca d'agua
    que quase some no fundo em vez de um cinza chapado."""
    c = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
    f = tuple(int(fundo[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(
        int(c[i] * alfa + f[i] * (1 - alfa)) for i in range(3))


def card(pai, titulo=None, **kw):
    """A panel: 1px border, dark fill, optional accent heading strip.

    Returns (moldura, corpo) -- pack/grid the moldura, put content in corpo.
    Square corners on purpose: tk cannot round a real frame, and faking it with
    a canvas would break every grid inside. VS Code's own panels are square.
    """
    moldura = tk.Frame(pai, bg=BORDA, padx=1, pady=1, **kw)
    dentro = tk.Frame(moldura, bg=CARD)
    dentro.pack(fill="both", expand=True)
    if titulo:
        faixa = tk.Frame(dentro, bg=CARD_ALT)
        faixa.pack(fill="x")
        tk.Frame(faixa, bg=ACENTO, width=3).pack(side="left", fill="y")
        tk.Label(faixa, text=titulo, bg=CARD_ALT, fg=ACENTO, font=F_TIT,
                 anchor="w", padx=8, pady=5).pack(side="left", fill="x")
    corpo = tk.Frame(dentro, bg=CARD, padx=10, pady=8)
    corpo.pack(fill="both", expand=True)
    return moldura, corpo


class Badge(tk.Canvas):
    """Rounded status pill with a leading dot -- [ * CONECTADO ].

    Drawn on a canvas because that is the only way tk rounds a corner. Small
    and self-contained, so it costs nothing elsewhere.
    """

    def __init__(self, pai, texto="", cor=ERRO, fundo=None, **kw):
        self.fundo = fundo or BG
        super().__init__(pai, height=24, bg=self.fundo, highlightthickness=0,
                         bd=0, **kw)
        self._cor = cor
        self._texto = texto
        self.bind("<Configure>", lambda _e: self._pintar())
        self.set(texto, cor)

    def _mistura(self, cor, fundo, alfa):
        return mistura(cor, fundo, alfa)

    def set(self, texto, cor=None):
        self._texto = texto
        if cor:
            self._cor = cor
        # 7 px por caractere subestima maiusculas em negrito; 7.6 cabe sem cortar
        largura = 40 + int(len(texto) * 7.6)
        self.configure(width=largura)
        self._pintar()

    def _pintar(self):
        self.delete("all")
        w = max(self.winfo_width(), int(self["width"]))
        h = int(self["height"])
        r = h // 2
        fundo = self._mistura(self._cor, self.fundo, 0.18)
        borda = self._mistura(self._cor, self.fundo, 0.45)
        for x in (r, w - r - 1):
            self.create_oval(x - r, 0, x + r, h - 1, fill=fundo,
                             outline=borda)
        self.create_rectangle(r, 0, w - r - 1, h - 1, fill=fundo, outline="")
        self.create_line(r, 0, w - r - 1, 0, fill=borda)
        self.create_line(r, h - 1, w - r - 1, h - 1, fill=borda)
        self.create_oval(11, h // 2 - 3, 17, h // 2 + 3, fill=self._cor,
                         outline="")
        self.create_text(23, h // 2, text=self._texto, anchor="w",
                         fill=self._cor, font=F_BOLD)


_popover_aberto = [None]


def popover(pai, titulo, linhas, x, y):
    """Balao de ajuda tematico perto de (x, y). So um aberto por vez -- abrir
    outro fecha o anterior, e clicar fora fecha. Fecha no Esc tambem."""
    import tkinter as _tk
    fechar_popover()
    win = _tk.Toplevel(pai)
    win.overrideredirect(True)      # sem barra de titulo: e um balao, nao janela
    win.configure(bg=BORDA)
    _popover_aberto[0] = win

    dentro = _tk.Frame(win, bg=CARD, padx=14, pady=12)
    dentro.pack(padx=1, pady=1)
    faixa = _tk.Frame(dentro, bg=CARD)
    faixa.pack(fill="x", anchor="w")
    _tk.Label(faixa, text="ℹ", bg=CARD, fg=ACENTO,
              font=(FONTE, 11, "bold")).pack(side="left", padx=(0, 6))
    _tk.Label(faixa, text=titulo, bg=CARD, fg=ACENTO,
              font=(FONTE, 10, "bold")).pack(side="left")
    _tk.Frame(dentro, bg=BORDA, height=1).pack(fill="x", pady=(8, 8))
    for linha in linhas:
        if linha.startswith("EXPL:"):
            # explicacao de uma opcao: texto normal, indentado e mais claro,
            # para ensinar o que aquela escolha faz -- nao repetir o rotulo
            _tk.Label(dentro, text=linha[5:], bg=CARD, fg=TXT2,
                      font=(FONTE, 9), justify="left", anchor="w",
                      wraplength=330).pack(anchor="w", fill="x", padx=(18, 0),
                                           pady=(0, 4))
            continue
        mono = linha.startswith("   ") or linha.startswith("Formato:")             or linha.startswith("Exemplo:") or linha.startswith("Tipo:")
        _tk.Label(dentro, text=linha or " ", bg=CARD,
                  fg=ACENTO if linha.startswith("   ") else (
                      TXT2 if linha.startswith(("Obs:", "So leitura:")) else TXT),
                  font=(MONO, 8) if mono else (FONTE, 9),
                  justify="left", anchor="w", wraplength=340).pack(
                      anchor="w", fill="x")

    win.update_idletasks()
    larg, alt = win.winfo_width(), win.winfo_height()
    tela_w = win.winfo_screenwidth()
    tela_h = win.winfo_screenheight()
    x = min(x, tela_w - larg - 8)
    if y + alt > tela_h - 8:        # sem espaco embaixo -> abre para cima
        y = max(8, y - alt - 24)
    win.geometry(f"+{max(x, 8)}+{max(y, 8)}")
    win.bind("<Escape>", lambda _e: fechar_popover())
    # clicar em qualquer lugar fora fecha
    win.after(50, lambda: win.bind_all("<Button-1>", _clique_fora, add="+"))
    return win


def _clique_fora(evento):
    win = _popover_aberto[0]
    if win is None:
        return
    w = evento.widget
    while w is not None:
        if w is win:
            return                  # clique dentro do proprio balao: mantem
        w = getattr(w, "master", None)
    fechar_popover()


def fechar_popover():
    win = _popover_aberto[0]
    if win is not None:
        try:
            win.unbind_all("<Button-1>")
            win.destroy()
        except Exception:
            pass
        _popover_aberto[0] = None


def icone_info(pai, on_click, fundo=None):
    """O '(i)' clicavel. Um Label, para caber em qualquer canto de layout."""
    import tkinter as _tk
    lbl = _tk.Label(pai, text="ⓘ", bg=fundo or CARD, fg=TXT2,
                    font=(FONTE, 10), cursor="hand2")
    lbl.bind("<Enter>", lambda _e: lbl.config(fg=ACENTO))
    lbl.bind("<Leave>", lambda _e: lbl.config(fg=TXT2))
    lbl.bind("<Button-1>", on_click)
    return lbl


def selftest():
    # as duas paletas tem exatamente as mesmas chaves, senao trocar deixa
    # widget com cor de modo que nao existe mais
    assert set(PALETAS["escuro"]) == set(PALETAS["claro"])
    for nome, pal in PALETAS.items():
        for chave, cor in pal.items():
            assert len(cor) == 7 and cor[0] == "#", (nome, chave, cor)
            int(cor[1:], 16)
        # cores repetidas quebram o de_para da troca ao vivo
        assert len(set(pal.values())) == len(pal), (nome, "cor repetida")
    cores = (BG, CARD, INPUT, TXT, TXT2, ACENTO, OK, ERRO, ALERTA, TERM,
             LOG_TX, LOG_RX, LOG_ERR)
    for c in cores:
        assert len(c) == 7 and c[0] == "#", c
        int(c[1:], 16)
    r = tk.Tk()
    r.withdraw()
    aplicar(r)
    assert mistura("#FFFFFF", "#000000", 0.5) == "#7f7f7f"
    assert mistura(OK, BG, 0.0) == BG.lower()
    b = Badge(r, "CONECTADO", OK)
    assert b._mistura("#FFFFFF", "#000000", 0.5) == "#7f7f7f"
    assert b._mistura(OK, BG, 0.0) == BG.lower()
    moldura, corpo = card(r, "Teste")
    assert corpo.cget("bg") == CARD
    # troca ao vivo: o card tem de sair com a cor do outro modo
    escuro_card = CARD
    trocar(r, "claro")
    assert MODO == "claro" and CARD != escuro_card
    assert corpo.cget("bg") == CARD, (corpo.cget("bg"), CARD)
    trocar(r, "escuro")
    assert corpo.cget("bg") == escuro_card
    r.destroy()
    print("tema selftest ok -", len(cores), "cores,", len(PALETAS), "paletas")


if __name__ == "__main__":
    selftest()
