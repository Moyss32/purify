"""
Purify GUI — Interface moderna com cards por operação.

Layout:
  • Barra de cabeçalho com info do sistema
  • Painel lateral esquerdo: categorias, contadores, presets
  • Área central: grade de cards 3 colunas, buscável
  • Rodapé: botões de ação, ponto de restauração, barra de progresso
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

from core.manager import PurifyManager
from core.operations import Operation, OperationResult, OperationState, ReversibilityLevel, RiskLevel

# ---------------------------------------------------------------------------
# Paleta de cores
# ---------------------------------------------------------------------------
C = {
    "bg":          "#0F0F13",   # fundo escuro profundo
    "surface":     "#1A1A23",   # superfície dos cards
    "surface2":    "#20202C",   # hover dos cards / sidebar
    "border":      "#2E2E3E",   # bordas suaves
    "border_sel":  "#5B7BFF",   # borda quando selecionado
    "accent":      "#5B7BFF",   # azul principal
    "accent_dim":  "#1E2540",   # azul muito escuro (bg badge)
    "text":        "#E8E8F0",   # texto principal
    "text2":       "#9090A8",   # texto secundário
    "text3":       "#606075",   # texto terciário / desabilitado
    "ok":          "#3FB950",   # verde sucesso
    "ok_dim":      "#0D2B14",
    "warn":        "#E3A94C",   # amarelo aviso
    "warn_dim":    "#2B1F08",
    "danger":      "#F85149",   # vermelho erro/crítico
    "danger_dim":  "#2B0C0C",
    "info":        "#58A6FF",   # azul informação
    "info_dim":    "#0D1B2B",
    "muted":       "#3D3D52",   # badge neutro
    "sel_bg":      "#1A2040",   # fundo do card selecionado
    "header_bg":   "#13131A",
    "sidebar_bg":  "#13131A",
    "btn_primary": "#5B7BFF",
    "btn_primary_h":"#7090FF",
    "btn_danger":  "#F85149",
    "btn_danger_h":"#FF7070",
    "btn_neutral": "#2A2A38",
    "btn_neutral_h":"#38384E",
    "progress_bg": "#1A1A23",
    "scrollbar":   "#2A2A3A",
    "white":       "#FFFFFF",
}

RISK_COLOR = {
    RiskLevel.VERY_LOW: ("#3FB950", "#0D2B14"),
    RiskLevel.LOW:      ("#58A6FF", "#0D1B2B"),
    RiskLevel.MEDIUM:   ("#E3A94C", "#2B1F08"),
    RiskLevel.HIGH:     ("#F0973A", "#2B1508"),
    RiskLevel.CRITICAL: ("#F85149", "#2B0C0C"),
}

RISK_LABEL = {
    RiskLevel.VERY_LOW: "Muito baixo",
    RiskLevel.LOW:      "Baixo",
    RiskLevel.MEDIUM:   "Médio",
    RiskLevel.HIGH:     "Alto",
    RiskLevel.CRITICAL: "Crítico",
}

REV_LABEL = {
    ReversibilityLevel.FULL:    ("🔄", "Reversível"),
    ReversibilityLevel.PARTIAL: ("⚠", "Parcial"),
    ReversibilityLevel.NONE:    ("✕", "Irreversível"),
}

STATE_TAGS = {
    OperationState.SUCCESS:        ("ok",     "Concluído"),
    OperationState.ALREADY_APPLIED:("info",   "Já aplicado"),
    OperationState.FAILED:         ("danger", "Falhou"),
    OperationState.UNCERTAIN:      ("warn",   "Incerto"),
    OperationState.NOT_APPLICABLE: ("muted",  "N/A"),
    OperationState.CANCELLED:      ("muted",  "Cancelado"),
    OperationState.RUNNING:        ("info",   "Executando"),
    OperationState.PENDING:        ("muted",  "Pendente"),
}

CARDS_PER_ROW = 3


# ---------------------------------------------------------------------------
# Helpers de widget
# ---------------------------------------------------------------------------

def _hex(color: str) -> str:
    return color


class _RoundedCanvas(tk.Canvas):
    """Canvas com fundo arredondado desenhado via polígono."""

    def __init__(self, parent, width, height, radius=10, bg=C["surface"], border=C["border"],
                 border_width=1, **kw):
        super().__init__(parent, width=width, height=height, highlightthickness=0,
                         bg=parent.cget("bg") if hasattr(parent, "cget") else C["bg"], **kw)
        self._r = radius
        self._bg = bg
        self._border = border
        self._bw = border_width
        self._w = width
        self._h = height
        self._rect_id = None
        self._draw()
        self.bind("<Configure>", self._on_resize)

    def _draw(self):
        self.delete("rounded")
        w, h, r = self._w, self._h, self._r
        # Outer (border)
        self.create_polygon(
            r, 0,  w - r, 0,  w, r,  w, h - r,  w - r, h,
            r, h,  0, h - r,  0, r,
            smooth=True, fill=self._border, outline="", tags="rounded"
        )
        # Inner (fill)
        bw = self._bw
        self.create_polygon(
            r + bw, bw,  w - r - bw, bw,  w - bw, r + bw,
            w - bw, h - r - bw,  w - r - bw, h - bw,
            r + bw, h - bw,  bw, h - r - bw,  bw, r + bw,
            smooth=True, fill=self._bg, outline="", tags="rounded"
        )

    def _on_resize(self, event):
        self._w = event.width
        self._h = event.height
        self._draw()

    def set_border(self, color: str):
        self._border = color
        self._draw()

    def set_bg(self, color: str):
        self._bg = color
        self._draw()


def _label(parent, text="", fg=C["text"], bg=None, font=None, anchor="w", **kw):
    return tk.Label(parent, text=text, fg=fg, bg=bg or parent.cget("bg"),
                    font=font, anchor=anchor, **kw)


def _badge(parent, text, fg, bg, font=None):
    """Badge colorido compacto."""
    f = tk.Frame(parent, bg=bg, padx=6, pady=2)
    tk.Label(f, text=text, fg=fg, bg=bg,
             font=font or ("Segoe UI", 8, "bold")).pack()
    return f


def _btn(parent, text, command, bg=C["btn_neutral"], fg=C["text"],
         hbg=C["btn_neutral_h"], font=None, padx=16, pady=8, radius=6, **kw):
    """Botão flat com hover."""
    btn = tk.Label(
        parent, text=text, fg=fg, bg=bg,
        font=font or ("Segoe UI", 10, "bold"),
        padx=padx, pady=pady, cursor="hand2", **kw
    )
    btn.bind("<Enter>", lambda e: btn.configure(bg=hbg))
    btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
    btn.bind("<Button-1>", lambda e: command() if btn.cget("state") != "disabled" else None)
    btn._base_bg = bg
    btn._hover_bg = hbg
    return btn


def _set_btn_enabled(btn: tk.Label, enabled: bool):
    if enabled:
        btn.configure(state="normal", fg=btn.cget("fg").replace(C["text3"], C["text"]) if C["text3"] in btn.cget("fg") else btn.cget("fg"),
                      bg=btn._base_bg, cursor="hand2")
    else:
        btn.configure(state="disabled", cursor="arrow", bg=C["muted"])


# ---------------------------------------------------------------------------
# Utilitário de ícone de Appx
# ---------------------------------------------------------------------------

_icon_cache: dict[str, tk.PhotoImage | None] = {}


def _get_appx_icon(package_name: str, size: int = 48) -> tk.PhotoImage | None:
    """Tenta extrair o ícone do pacote Appx em cache. Retorna None se não encontrar."""
    cache_key = f"{package_name}_{size}"
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]
    result = None
    try:
        import subprocess
        import os
        import glob

        ps = (
            f"$pkg = Get-AppxPackage -AllUsers -Name '{package_name}' -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; "
            "if ($pkg) { $pkg.InstallLocation } else { '' }"
        )
        proc = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        location = proc.stdout.strip()
        if location and os.path.isdir(location):
            # Procura assets de logo
            patterns = [
                os.path.join(location, "**", f"*Logo*.scale-{size}*.png"),
                os.path.join(location, "**", "*Square44x44*.png"),
                os.path.join(location, "**", "*AppList*.png"),
                os.path.join(location, "**", "*.png"),
            ]
            found = None
            for pattern in patterns:
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    # Prefere arquivos menores/thumbnails
                    matches.sort(key=os.path.getsize)
                    found = matches[0]
                    break
            if found:
                img = tk.PhotoImage(file=found)
                # Resize para o tamanho desejado
                iw, ih = img.width(), img.height()
                if iw > 0 and ih > 0:
                    scale = max(1, min(iw // size, ih // size))
                    if scale > 1:
                        img = img.subsample(scale, scale)
                result = img
    except Exception:
        pass
    _icon_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# OperationCard
# ---------------------------------------------------------------------------

class OperationCard:
    """Card visual de uma operação. Gerenciado externamente por CardGrid."""

    HEIGHT = 190
    WIDTH = 310

    def __init__(self, parent: tk.Widget, op: Operation, on_select, on_details,
                 font_family: str = "Segoe UI"):
        self.op = op
        self._on_select = on_select
        self._on_details = on_details
        self._font = font_family
        self._selected = op.is_selected
        self._state_text = "Consultando…"
        self._state_kind = "muted"
        self._photo: tk.PhotoImage | None = None

        # Frame externo — simula borda arredondada com bg de borda
        self.frame = tk.Frame(parent, bg=C["border"], padx=1, pady=1)

        # Frame interno — conteúdo
        self.body = tk.Frame(self.frame, bg=C["surface"])
        self.body.pack(fill=tk.BOTH, expand=True)

        self._build()
        self._apply_selected(self._selected)

        # Bind de hover em todos os filhos
        for widget in (self.frame, self.body):
            widget.bind("<Enter>", self._on_hover, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")

    def _build(self):
        op = self.op
        body = self.body
        ff = self._font

        # Linha superior: ícone + nome
        top = tk.Frame(body, bg=C["surface"], padx=12, pady=10)
        top.pack(fill=tk.X)

        # Ícone (carregado em background para não bloquear)
        self._icon_label = tk.Label(top, bg=C["surface"], width=0)
        self._icon_label.pack(side=tk.LEFT, padx=(0, 8))
        self._load_icon_async()

        # Nome
        name_frame = tk.Frame(top, bg=C["surface"])
        name_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_name = tk.Label(
            name_frame, text=op.name, fg=C["text"], bg=C["surface"],
            font=(ff, 11, "bold"), anchor="w", wraplength=210, justify="left"
        )
        self.lbl_name.pack(fill=tk.X)
        self.lbl_type = tk.Label(
            name_frame, text=op.category, fg=C["text2"], bg=C["surface"],
            font=(ff, 8), anchor="w"
        )
        self.lbl_type.pack(fill=tk.X)

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(fill=tk.X, padx=12)

        # Descrição
        self.lbl_desc = tk.Label(
            body, text=op.description, fg=C["text2"], bg=C["surface"],
            font=(ff, 9), anchor="nw", justify="left",
            wraplength=270, padx=12, pady=8
        )
        self.lbl_desc.pack(fill=tk.X)

        # Badges: risco + reversibilidade
        badges = tk.Frame(body, bg=C["surface"], padx=10)
        badges.pack(fill=tk.X, pady=(0, 6))

        risk_fg, risk_bg = RISK_COLOR.get(op.risk, (C["text"], C["muted"]))
        rb = tk.Frame(badges, bg=risk_bg, padx=6, pady=2)
        rb.pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(rb, text=RISK_LABEL.get(op.risk, op.risk.value),
                 fg=risk_fg, bg=risk_bg, font=(ff, 8, "bold")).pack()

        rev_icon, rev_text = REV_LABEL.get(op.reversibility, ("", "?"))
        rev_color = C["ok"] if op.reversibility is ReversibilityLevel.FULL else (
            C["warn"] if op.reversibility is ReversibilityLevel.PARTIAL else C["danger"]
        )
        rev_bg = C["ok_dim"] if op.reversibility is ReversibilityLevel.FULL else (
            C["warn_dim"] if op.reversibility is ReversibilityLevel.PARTIAL else C["danger_dim"]
        )
        vb = tk.Frame(badges, bg=rev_bg, padx=6, pady=2)
        vb.pack(side=tk.LEFT)
        tk.Label(vb, text=f"{rev_icon} {rev_text}", fg=rev_color, bg=rev_bg,
                 font=(ff, 8, "bold")).pack()

        # Estado atual
        state_row = tk.Frame(body, bg=C["surface"], padx=12)
        state_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(state_row, text="Estado:", fg=C["text3"], bg=C["surface"],
                 font=(ff, 8)).pack(side=tk.LEFT)
        self.lbl_state = tk.Label(state_row, text=self._state_text, fg=C["text2"],
                                  bg=C["surface"], font=(ff, 8, "bold"))
        self.lbl_state.pack(side=tk.LEFT, padx=(4, 0))

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(fill=tk.X, padx=12)

        # Botões
        btn_row = tk.Frame(body, bg=C["surface"], padx=10, pady=8)
        btn_row.pack(fill=tk.X)

        self.btn_select = tk.Label(
            btn_row,
            text="Selecionar",
            fg=C["text"],
            bg=C["btn_neutral"],
            font=(ff, 9, "bold"),
            padx=14, pady=5,
            cursor="hand2",
        )
        self.btn_select.pack(side=tk.LEFT)
        self.btn_select.bind("<Button-1>", lambda e: self._toggle_select())
        self.btn_select.bind("<Enter>", lambda e: self.btn_select.configure(bg=C["btn_neutral_h"]))
        self.btn_select.bind("<Leave>", lambda e: self.btn_select.configure(
            bg=C["accent_dim"] if self._selected else C["btn_neutral"]))

        self.btn_details = tk.Label(
            btn_row,
            text="Detalhes",
            fg=C["text2"],
            bg=C["surface"],
            font=(ff, 9),
            padx=10, pady=5,
            cursor="hand2",
        )
        self.btn_details.pack(side=tk.RIGHT)
        self.btn_details.bind("<Button-1>", lambda e: self._on_details(self.op))
        self.btn_details.bind("<Enter>", lambda e: self.btn_details.configure(fg=C["accent"]))
        self.btn_details.bind("<Leave>", lambda e: self.btn_details.configure(fg=C["text2"]))

        # Bind de hover em novos widgets
        for w in (self.lbl_name, self.lbl_type, self.lbl_desc, self.lbl_state,
                  badges, state_row, btn_row, top, name_frame):
            w.bind("<Enter>", self._on_hover, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

    def _load_icon_async(self):
        """Tenta carregar ícone real de forma assíncrona."""
        pkg = getattr(self.op, "package_name", None)
        if not pkg:
            return

        def worker():
            photo = _get_appx_icon(pkg, 32)
            if photo:
                self._icon_label.after(0, lambda: self._set_icon(photo))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _set_icon(self, photo: tk.PhotoImage):
        try:
            self._photo = photo
            self._icon_label.configure(image=photo)
        except tk.TclError:
            pass

    def _toggle_select(self):
        if self.op.risk is RiskLevel.CRITICAL and not self.op.is_selected:
            if not messagebox.askyesno(
                "Ação crítica",
                f"{self.op.name}\n\nRisco: {self.op.risk.value}\n{self.op.description}\n\nDeseja incluir esta ação?",
            ):
                return
        self.op.is_selected = not self.op.is_selected
        self._selected = self.op.is_selected
        self._apply_selected(self._selected)
        self._on_select(self.op)

    def _apply_selected(self, selected: bool):
        self._selected = selected
        border_color = C["border_sel"] if selected else C["border"]
        card_bg = C["sel_bg"] if selected else C["surface"]
        self.frame.configure(bg=border_color)
        self.body.configure(bg=card_bg)

        def _set_bg(w):
            try:
                if w.cget("bg") in (C["surface"], C["sel_bg"], card_bg):
                    w.configure(bg=card_bg)
            except Exception:
                pass
            for child in w.winfo_children():
                _set_bg(child)

        _set_bg(self.body)
        self.btn_select.configure(
            text="✓ Selecionado" if selected else "Selecionar",
            bg=C["accent_dim"] if selected else C["btn_neutral"],
            fg=C["accent"] if selected else C["text"],
        )

    def update_state(self, state_dict: Any):
        """Atualiza o label de estado do card."""
        text, color = self._format_state(state_dict)
        self._state_text = text
        self._state_kind = color
        try:
            self.lbl_state.configure(text=text, fg=color)
        except tk.TclError:
            pass

    def update_result(self, result: OperationResult):
        tag, label = STATE_TAGS.get(result.state, ("muted", result.state.value))
        colors = {"ok": C["ok"], "info": C["info"], "warn": C["warn"],
                  "danger": C["danger"], "muted": C["text3"]}
        try:
            self.lbl_state.configure(text=label, fg=colors.get(tag, C["text2"]))
        except tk.TclError:
            pass

    @staticmethod
    def _format_state(value: Any) -> tuple[str, str]:
        if value is None:
            return "Não verificado", C["text3"]
        if not isinstance(value, dict):
            return str(value), C["text2"]
        if not value.get("known", True) and "error" in value:
            return "Erro ao verificar", C["danger"]
        if value.get("found") is False or (
            "installed" in value and not value.get("installed")
        ):
            return "Não instalado / Inativo", C["text3"]
        if "installed" in value and value.get("installed"):
            return "Instalado", C["ok"]
        if "start_mode" in value:
            mode = value.get("start_mode", "")
            status = value.get("status", "")
            if mode.lower() == "disabled":
                return "Desativado", C["text3"]
            if status.lower() == "running":
                return "Em execução", C["ok"]
            return f"{mode} · {status}", C["text2"]
        return "Verificado", C["info"]

    def _on_hover(self, _e=None):
        if not self._selected:
            try:
                self.frame.configure(bg=C["accent"])
            except tk.TclError:
                pass

    def _on_leave(self, _e=None):
        if not self._selected:
            try:
                self.frame.configure(bg=C["border"])
            except tk.TclError:
                pass


# ---------------------------------------------------------------------------
# CardGrid — grade scrollável de cards
# ---------------------------------------------------------------------------

class CardGrid(tk.Frame):
    def __init__(self, parent, on_select, on_details, font_family, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._on_select = on_select
        self._on_details = on_details
        self._font = font_family
        self._cards: list[OperationCard] = []
        self._cols = CARDS_PER_ROW

        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(self, orient="vertical", command=canvas.yview,
                           bg=C["scrollbar"], troughcolor=C["bg"],
                           activebackground=C["accent"])
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = canvas
        self._scrollbar = vsb
        self._inner = tk.Frame(canvas, bg=C["bg"])
        self._inner_id = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_configure)
        canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_scroll_events(canvas)
        self._bind_scroll_events(self._inner)

    def _bind_scroll_events(self, widget: tk.Widget):
        """Liga a rolagem também aos filhos, pois eventos Tk não sobem aos pais."""
        if not getattr(widget, "_purify_scroll_bound", False):
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_linux_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_linux_mousewheel, add="+")
            widget._purify_scroll_bound = True
        for child in widget.winfo_children():
            self._bind_scroll_events(child)

    def _on_inner_configure(self, _e=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._inner_id, width=event.width)

    def _on_mousewheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            # Windows normalmente envia múltiplos de 120; macOS costuma enviar ±1.
            units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            if units:
                self._canvas.yview_scroll(units, "units")
        return "break"

    def _on_linux_mousewheel(self, event):
        self._canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        return "break"

    def populate(self, operations: list[Operation]):
        for card in self._cards:
            card.frame.destroy()
        self._cards.clear()

        for i, op in enumerate(operations):
            row, col = divmod(i, self._cols)
            card = OperationCard(
                self._inner, op,
                on_select=self._on_select,
                on_details=self._on_details,
                font_family=self._font,
            )
            card.frame.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            self._bind_scroll_events(card.frame)
            self._cards.append(card)

        for col in range(self._cols):
            self._inner.columnconfigure(col, weight=1)

        self._canvas.yview_moveto(0)

    def update_state(self, op: Operation, state: Any):
        for card in self._cards:
            if card.op is op:
                card.update_state(state)
                return

    def update_result(self, op: Operation, result: OperationResult):
        for card in self._cards:
            if card.op is op:
                card.update_result(result)
                return

    def refresh_selections(self):
        for card in self._cards:
            card._apply_selected(card.op.is_selected)


# ---------------------------------------------------------------------------
# Diálogo de Detalhes
# ---------------------------------------------------------------------------

class DetailsDialog(tk.Toplevel):
    def __init__(self, parent, op: Operation, state: Any, font_family: str,
                 on_rollback: Callable[[], bool] | None = None):
        super().__init__(parent)
        self._on_rollback = on_rollback
        self.title(f"Detalhes — {op.name}")
        self.geometry("640x520")
        self.minsize(560, 420)
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        ff = font_family

        # Cabeçalho
        hdr = tk.Frame(self, bg=C["surface"], padx=20, pady=16)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=op.name, fg=C["text"], bg=C["surface"],
                 font=(ff, 16, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(hdr, text=op.category, fg=C["text2"], bg=C["surface"],
                 font=(ff, 10), anchor="w").pack(fill=tk.X)

        # Corpo
        body = tk.Frame(self, bg=C["bg"], padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)

        def row(label, value, r, fg=C["text2"]):
            tk.Label(body, text=label, fg=C["text3"], bg=C["bg"],
                     font=(ff, 9, "bold"), anchor="w").grid(row=r, column=0, sticky="nw",
                                                             pady=4, padx=(0, 12))
            tk.Label(body, text=value, fg=fg, bg=C["bg"],
                     font=(ff, 9), anchor="nw", justify="left",
                     wraplength=460).grid(row=r, column=1, sticky="ew", pady=4)

        row("Descrição", op.description, 0)
        row("Risco", f"{op.risk.value}", 1, RISK_COLOR.get(op.risk, (C["text"], ""))[0])
        rev_icon, rev_text = REV_LABEL.get(op.reversibility, ("", op.reversibility.value))
        row("Reversibilidade", f"{rev_icon} {rev_text}", 2)
        row("Precisa de admin", "Sim" if op.requires_admin else "Não", 3)

        state_text = OperationCard._format_state(state)[0]
        row("Estado atual", state_text, 4)

        if hasattr(op, "_describe_action"):
            row("O que será feito", op._describe_action(), 5)
        if hasattr(op, "_describe_rollback"):
            row("Reversão", op._describe_rollback(), 6)

        # Botão fechar
        btn_frame = tk.Frame(self, bg=C["bg"], padx=20, pady=12)
        btn_frame.pack(fill=tk.X)
        if on_rollback:
            _btn(btn_frame, "↶ Reverter", self._request_rollback,
                 bg=C["btn_neutral"], hbg=C["btn_neutral_h"], fg=C["text"]).pack(side=tk.LEFT)
        close_btn = _btn(btn_frame, "Fechar", self.destroy,
                         bg=C["btn_neutral"], hbg=C["btn_neutral_h"], fg=C["text"])
        close_btn.pack(side=tk.RIGHT)

        self.grab_set()
        self.focus_set()

    def _request_rollback(self):
        if self._on_rollback and self._on_rollback():
            self.destroy()


# ---------------------------------------------------------------------------
# LogPanel — painel de log lateral/inferior
# ---------------------------------------------------------------------------

class LogPanel(tk.Toplevel):
    def __init__(self, parent, font_family):
        super().__init__(parent)
        self.title("Purify — Log de execução")
        self.geometry("820x480")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        ff = font_family

        tk.Label(self, text="Log de execução", fg=C["text"], bg=C["bg"],
                 font=(ff, 13, "bold"), anchor="w", padx=16, pady=12).pack(fill=tk.X)

        self.txt = scrolledtext.ScrolledText(
            self, bg=C["surface"], fg=C["text"], font=(ff, 9),
            padx=12, pady=10, relief=tk.FLAT,
            highlightthickness=1, highlightbackground=C["border"],
            state=tk.DISABLED,
        )
        self.txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        self.txt.tag_configure("ok",     foreground=C["ok"])
        self.txt.tag_configure("danger", foreground=C["danger"])
        self.txt.tag_configure("warn",   foreground=C["warn"])
        self.txt.tag_configure("info",   foreground=C["info"])
        self.txt.tag_configure("muted",  foreground=C["text3"])

        btn_row = tk.Frame(self, bg=C["bg"], padx=12, pady=8)
        btn_row.pack(fill=tk.X)
        _btn(btn_row, "Limpar", self._clear, bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
             fg=C["text"]).pack(side=tk.LEFT)
        _btn(btn_row, "Fechar", self.withdraw, bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
             fg=C["text"]).pack(side=tk.RIGHT)

    def append(self, message: str, tag: str = ""):
        self.txt.configure(state=tk.NORMAL)
        if tag:
            self.txt.insert(tk.END, message + "\n", tag)
        else:
            self.txt.insert(tk.END, message + "\n")
        self.txt.see(tk.END)
        self.txt.configure(state=tk.DISABLED)

    def _clear(self):
        self.txt.configure(state=tk.NORMAL)
        self.txt.delete("1.0", tk.END)
        self.txt.configure(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# PurifyApp — janela principal
# ---------------------------------------------------------------------------

class PurifyApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Purify — Manutenção do sistema")
        self.root.geometry("1380x860")
        self.root.minsize(1100, 720)
        self.root.configure(bg=C["bg"])

        self.manager = PurifyManager()
        self.current_category: str | None = None
        self.current_states: dict[str, Any] = {}
        self._visible_ops: list[Operation] = []
        self._events: queue.Queue[tuple] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._busy = False
        self._closing = False
        self.search_var = tk.StringVar(value="")
        self._log_panel: LogPanel | None = None

        self._detect_font()
        self._build_ui()
        self._populate_categories()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind_all("<Control-f>", self._focus_search)
        self.root.bind_all("<Escape>", self._on_escape)
        self.root.after(100, self._poll_events)
        self.root.after(300, self._start_initial_scan)

    # -----------------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------------

    def _detect_font(self):
        available = set(self.root.tk.call("font", "families"))
        self.ff = next(
            (n for n in ("Segoe UI", "Noto Sans", "Inter", "Helvetica Neue", "DejaVu Sans")
             if n in available),
            "TkDefaultFont",
        )
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family=self.ff, size=10)
            except tk.TclError:
                pass

    # -----------------------------------------------------------------------
    # Build UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        self._build_header()
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        self._build_sidebar(main)
        self._build_content(main)
        self._build_footer()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C["header_bg"], padx=20, pady=0, height=68)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        # Linha de acento colorida
        tk.Frame(hdr, bg=C["accent"], width=4, height=68).pack(side=tk.LEFT, fill=tk.Y)

        brand = tk.Frame(hdr, bg=C["header_bg"], padx=16, pady=12)
        brand.pack(side=tk.LEFT)
        tk.Label(brand, text="PURIFY", fg=C["text"], bg=C["header_bg"],
                 font=(self.ff, 20, "bold")).pack(anchor="w")
        tk.Label(brand, text="MANUTENÇÃO DO SISTEMA, SEM SURPRESAS", fg=C["text2"],
                 bg=C["header_bg"], font=(self.ff, 8, "bold")).pack(anchor="w")

        right = tk.Frame(hdr, bg=C["header_bg"], padx=12, pady=12)
        right.pack(side=tk.RIGHT)

        # Info do sistema
        platform = (self.manager.os_info.get("distribution_name")
                    or self.manager.os_info.get("platform", "Sistema"))
        version = (self.manager.os_info.get("distribution_version")
                   or self.manager.os_info.get("release", ""))
        sys_text = f"{platform} {version}".strip()

        sys_badge = tk.Frame(right, bg=C["accent_dim"], padx=10, pady=4)
        sys_badge.pack(side=tk.RIGHT, padx=(12, 0))
        tk.Label(sys_badge, text=sys_text, fg=C["accent"], bg=C["accent_dim"],
                 font=(self.ff, 9, "bold")).pack()

        is_admin = self.manager.os_info.get("is_admin", False)
        adm_text = "● Administrador" if is_admin else "● Conta padrão"
        adm_color = C["ok"] if is_admin else C["warn"]
        tk.Label(right, text=adm_text, fg=adm_color, bg=C["header_bg"],
                 font=(self.ff, 9, "bold")).pack(side=tk.RIGHT, padx=(12, 0))

        self.btn_log = _btn(right, "Ver log", self._toggle_log,
                            bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
                            fg=C["text2"], font=(self.ff, 9), padx=12, pady=6)
        self.btn_log.pack(side=tk.RIGHT, padx=(0, 8))

        self.btn_scan = _btn(right, "↺ Atualizar estados", self._on_scan_states,
                             bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
                             fg=C["text"], font=(self.ff, 9, "bold"), padx=12, pady=6)
        self.btn_scan.pack(side=tk.RIGHT, padx=(0, 8))

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=C["sidebar_bg"], width=220)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 0))
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(2, weight=1)

        # Título
        tk.Label(sidebar, text="CATEGORIAS", fg=C["text3"], bg=C["sidebar_bg"],
                 font=(self.ff, 8, "bold"), anchor="w",
                 padx=16, pady=14).grid(row=0, column=0, sticky="ew")

        # Lista de categorias
        self._cat_list = tk.Listbox(
            sidebar,
            bg=C["sidebar_bg"],
            fg=C["text"],
            selectbackground=C["accent_dim"],
            selectforeground=C["accent"],
            activestyle="none",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            font=(self.ff, 10),
            exportselection=False,
        )
        self._cat_list.grid(row=1, column=0, sticky="ew", padx=0)
        self._cat_list.bind("<<ListboxSelect>>", self._on_cat_select)

        # Espaçador
        tk.Frame(sidebar, bg=C["sidebar_bg"], height=1).grid(row=2, column=0, sticky="nsew")

        # Painel de seleção e presets
        sel_panel = tk.Frame(sidebar, bg=C["surface"], padx=14, pady=14)
        sel_panel.grid(row=3, column=0, sticky="ew", padx=0)
        sidebar.columnconfigure(0, weight=1)

        tk.Label(sel_panel, text="SELECIONADOS", fg=C["text3"], bg=C["surface"],
                 font=(self.ff, 8, "bold"), anchor="w").pack(fill=tk.X)
        self.lbl_sel_count = tk.Label(sel_panel, text="0 ações", fg=C["accent"],
                                       bg=C["surface"], font=(self.ff, 16, "bold"), anchor="w")
        self.lbl_sel_count.pack(fill=tk.X, pady=(4, 8))

        _btn(sel_panel, "⚡ Baixo risco", self._preset_low_risk,
             bg=C["btn_neutral"], hbg=C["btn_neutral_h"], fg=C["text"],
             font=(self.ff, 9), padx=10, pady=6).pack(fill=tk.X, pady=(0, 4))
        _btn(sel_panel, "✕ Limpar seleção", self._preset_clear,
             bg=C["btn_neutral"], hbg=C["btn_neutral_h"], fg=C["text2"],
             font=(self.ff, 9), padx=10, pady=6).pack(fill=tk.X)

    def _build_content(self, parent):
        content = tk.Frame(parent, bg=C["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)

        # Barra de busca
        search_bar = tk.Frame(content, bg=C["surface"], padx=16, pady=12)
        search_bar.grid(row=0, column=0, sticky="ew")
        search_bar.columnconfigure(0, weight=1)

        self.lbl_cat_title = tk.Label(search_bar, text="", fg=C["text"],
                                       bg=C["surface"], font=(self.ff, 14, "bold"),
                                       anchor="w")
        self.lbl_cat_title.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.lbl_cat_count = tk.Label(search_bar, text="", fg=C["text2"],
                                       bg=C["surface"], font=(self.ff, 9), anchor="w")
        self.lbl_cat_count.grid(row=0, column=1, sticky="e", pady=(0, 8))

        search_entry = tk.Entry(
            search_bar,
            textvariable=self.search_var,
            bg=C["bg"],
            fg=C["text"],
            insertbackground=C["text"],
            relief=tk.FLAT,
            font=(self.ff, 10),
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
        )
        search_entry.grid(row=1, column=0, sticky="ew", ipady=8, padx=(0, 8))
        search_entry.insert(0, "Buscar operações…")
        search_entry.bind("<FocusIn>", lambda e: (
            search_entry.delete(0, tk.END) if search_entry.get() == "Buscar operações…" else None
        ))
        search_entry.bind("<FocusOut>", lambda e: (
            search_entry.insert(0, "Buscar operações…") if not search_entry.get() else None
        ))
        self.search_var.trace_add("write", self._on_search)
        self._search_entry = search_entry

        _btn(search_bar, "Limpar", lambda: self.search_var.set(""),
             bg=C["btn_neutral"], hbg=C["btn_neutral_h"], fg=C["text2"],
             font=(self.ff, 9), padx=10, pady=6).grid(row=1, column=1, sticky="e")

        # Grade de cards
        self.card_grid = CardGrid(content, self._on_card_select, self._on_card_details,
                                  self.ff)
        self.card_grid.grid(row=1, column=0, sticky="nsew", pady=(0, 0))

        # Label "nenhum resultado"
        self.lbl_empty = tk.Label(content, text="Nenhuma operação encontrada.",
                                   fg=C["text3"], bg=C["bg"], font=(self.ff, 11))
        self.lbl_empty.grid(row=1, column=0)
        self.lbl_empty.grid_remove()

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=C["surface"], padx=20, pady=14)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.columnconfigure(0, weight=1)

        # Linha de status
        self.status = tk.StringVar(value="Pronto. Nada será alterado sem sua confirmação.")
        self.lbl_status = tk.Label(footer, textvariable=self.status, fg=C["text2"],
                                    bg=C["surface"], font=(self.ff, 9), anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Progress
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=200)
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0), pady=(0, 8))
        self.progress.grid_remove()

        # Botões de ação
        btns = tk.Frame(footer, bg=C["surface"])
        btns.grid(row=1, column=0, columnspan=2, sticky="ew")
        btns.columnconfigure(2, weight=1)

        self.btn_dry_run = _btn(btns, "👁 Pré-visualizar", self._on_dry_run,
                                 bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
                                 fg=C["text"], font=(self.ff, 10), padx=18, pady=10)
        self.btn_dry_run.grid(row=0, column=0, padx=(0, 8))

        # Restore point notice
        self.lbl_rp = tk.Label(btns,
                                text="🛡 Ponto de restauração será criado automaticamente",
                                fg=C["text3"], bg=C["surface"], font=(self.ff, 9), anchor="w")
        self.lbl_rp.grid(row=0, column=2, sticky="ew", padx=16)

        self.btn_execute = _btn(btns, "▶ Executar selecionadas", self._on_execute,
                                 bg=C["btn_primary"], hbg=C["btn_primary_h"],
                                 fg=C["white"], font=(self.ff, 11, "bold"), padx=22, pady=11)
        self.btn_execute.grid(row=0, column=3)

        self.btn_cancel = _btn(btns, "✕ Cancelar", self._on_cancel,
                                bg=C["btn_danger"], hbg=C["btn_danger_h"],
                                fg=C["white"], font=(self.ff, 10, "bold"), padx=16, pady=10)
        self.btn_cancel.grid(row=0, column=4, padx=(8, 0))
        self.btn_cancel.grid_remove()

        self._update_action_buttons()

    # -----------------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------------

    def _populate_categories(self):
        categories = self.manager.get_all_categories()
        self._cat_list.delete(0, tk.END)
        for cat in categories:
            count = len(self.manager.get_operations_by_category(cat))
            self._cat_list.insert(tk.END, f"  {cat}  ({count})")
        if categories:
            self._cat_list.selection_set(0)
            self._show_category(categories[0])

    def _on_cat_select(self, _event=None):
        idx = self._cat_list.curselection()
        if not idx:
            return
        cats = self.manager.get_all_categories()
        if idx[0] < len(cats):
            self._show_category(cats[idx[0]])

    def _show_category(self, category: str):
        self.current_category = category
        self.search_var.set("")
        self._render_cards()

    def _on_search(self, *_args):
        if self.current_category:
            self._render_cards()

    def _focus_search(self, _e=None):
        self._search_entry.focus_set()
        return "break"

    def _on_escape(self, _e=None):
        query = self.search_var.get()
        if query and query != "Buscar operações…":
            self.search_var.set("")
            return "break"
        return None

    def _render_cards(self):
        if not self.current_category:
            return
        query = self.search_var.get().strip().casefold()
        if query == "buscar operações…":
            query = ""
        all_ops = self.manager.get_operations_by_category(self.current_category)
        visible = [
            op for op in all_ops
            if not query or query in f"{op.name} {op.description} {op.risk.value}".casefold()
        ]
        self._visible_ops = visible
        total = len(all_ops)
        self.lbl_cat_title.configure(text=self.current_category)
        self.lbl_cat_count.configure(text=f"{len(visible)} de {total}")

        if visible:
            self.lbl_empty.grid_remove()
            self.card_grid.grid()
            self.card_grid.populate(visible)
            # Restaurar estados já conhecidos
            for op in visible:
                state = self.current_states.get(op.id)
                if state is not None:
                    self.card_grid.update_state(op, state)
        else:
            self.card_grid.grid_remove()
            self.lbl_empty.grid()

    # -----------------------------------------------------------------------
    # Cards callbacks
    # -----------------------------------------------------------------------

    def _on_card_select(self, op: Operation):
        self._update_sidebar_count()
        self._update_action_buttons()
        count = len(self.manager.get_selected_operations())
        self.status.set(f"Seleção atualizada: {count} ação(ões) marcada(s).")

    def _on_card_details(self, op: Operation):
        state = self.current_states.get(op.id)
        rollback_callback = (
            (lambda: self._on_rollback(op))
            if self.manager.has_rollback_snapshot(op) else None
        )
        DetailsDialog(self.root, op, state, self.ff, on_rollback=rollback_callback)

    def _on_rollback(self, op: Operation) -> bool:
        if self._busy or (self._worker and self._worker.is_alive()):
            messagebox.showinfo("Operação em andamento", "Aguarde a operação atual terminar.", parent=self.root)
            return False
        if not self.manager.has_rollback_snapshot(op):
            messagebox.showinfo(
                "Rollback indisponível",
                "Não há um pré-estado salvo para esta operação.",
                parent=self.root,
            )
            return False
        if not messagebox.askyesno(
            "Confirmar reversão",
            f"O Purify tentará restaurar o estado anterior de:\n\n{op.name}\n\n"
            "A restauração só será considerada concluída após verificar o estado.",
            parent=self.root,
        ):
            return False
        self._run_background(
            "rollback",
            lambda: self.manager.rollback_operation(op, self._queue_log),
            op=op,
        )
        return True

    def _update_sidebar_count(self):
        count = len(self.manager.get_selected_operations())
        plural = "ação" if count == 1 else "ações"
        self.lbl_sel_count.configure(text=f"{count} {plural}")

    def _update_action_buttons(self):
        count = len(self.manager.get_selected_operations())
        enabled = bool(count) and not self._busy
        if enabled:
            self.btn_dry_run.configure(bg=C["btn_neutral"], cursor="hand2", state="normal")
            self.btn_dry_run._base_bg = C["btn_neutral"]
            self.btn_execute.configure(bg=C["btn_primary"], cursor="hand2", state="normal")
            self.btn_execute._base_bg = C["btn_primary"]
            n = count
            self.btn_execute.configure(text=f"▶ Executar {n} ação{'ões' if n != 1 else ''}")
            # Mostrar aviso de restore point se há ops admin no Windows
            has_admin = any(op.requires_admin for op in self.manager.get_selected_operations())
            is_win = self.manager.os_info.get("platform") == "windows"
            if has_admin and is_win:
                self.lbl_rp.configure(fg=C["ok"])
            else:
                self.lbl_rp.configure(fg=C["text3"])
        else:
            self.btn_dry_run.configure(bg=C["muted"], cursor="arrow", state="disabled")
            self.btn_execute.configure(bg=C["muted"], cursor="arrow", state="disabled",
                                       text="▶ Executar selecionadas")
            self.lbl_rp.configure(fg=C["text3"])

    # -----------------------------------------------------------------------
    # Presets
    # -----------------------------------------------------------------------

    def _preset_low_risk(self):
        for op in self.manager.operations:
            op.is_selected = op.risk in (RiskLevel.VERY_LOW, RiskLevel.LOW)
        self.card_grid.refresh_selections()
        self._update_sidebar_count()
        self._update_action_buttons()
        self.status.set("Preset aplicado: ações de risco baixo/muito baixo selecionadas.")

    def _preset_clear(self):
        for op in self.manager.operations:
            op.is_selected = False
        self.card_grid.refresh_selections()
        self._update_sidebar_count()
        self._update_action_buttons()
        self.status.set("Seleção limpa.")

    # -----------------------------------------------------------------------
    # Background worker
    # -----------------------------------------------------------------------

    def _run_background(self, kind: str, action, **meta):
        if self._worker and self._worker.is_alive():
            return
        if kind != "execute":
            self._cancel_event = None
        self._set_busy(True)
        self.status.set(
            "Verificando estados do catálogo…" if kind == "scan"
            else "Processando. A janela continuará responsiva…"
        )

        def worker():
            try:
                value = action()
                self._events.put(("done", kind, value, meta))
            except Exception as exc:
                self._events.put(("error", kind, str(exc), meta))

        self._worker = threading.Thread(target=worker, name="purify-worker", daemon=True)
        self._worker.start()

    def _queue_log(self, message: str):
        self._events.put(("log", message))

    def _queue_scan_progress(self, op: Operation, state: Any, done: int, total: int):
        self._events.put(("scan_progress", op, state, done, total))

    def _poll_events(self):
        try:
            while True:
                event = self._events.get_nowait()
                tag = event[0]
                if tag == "log":
                    self._append_log(event[1])
                elif tag == "scan_progress":
                    _, op, state, done, total = event
                    self.current_states[op.id] = state
                    self.card_grid.update_state(op, state)
                    self.status.set(f"Verificando: {done}/{total} — {op.name}")
                elif tag == "error":
                    _, _kind, error, _meta = event
                    self._set_busy(False)
                    self.status.set("Falha no processo.")
                    self._append_log(f"Erro: {error}", "danger")
                    messagebox.showerror("Falha", error, parent=self.root)
                    self._finish_close()
                elif tag == "done":
                    _, kind, value, meta = event
                    self._handle_done(kind, value, meta)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _handle_done(self, kind: str, value: Any, meta: dict):
        self._set_busy(False)
        if kind == "scan":
            unknown = sum(
                not isinstance(s, dict) or not s.get("known", False)
                for _, s in value
            )
            known = len(value) - unknown
            self.status.set(f"Leitura concluída: {known}/{len(value)} estados identificados.")
            self._append_log(f"Catálogo verificado: {known} estados conhecidos, {unknown} desconhecidos.", "info")
        elif kind == "dry_run":
            self._show_dry_run(value)
            self.status.set("Pré-visualização concluída. Nenhuma mudança foi feita.")
        elif kind == "execute":
            self._show_execution_summary(value)
        elif kind == "rollback":
            op = meta["op"]
            result: OperationResult = value
            if result.after is not None:
                self.current_states[op.id] = result.after
            self.card_grid.update_result(op, result)
            if result.state is OperationState.SUCCESS:
                title = "Rollback concluído"
                self.status.set(f"Estado anterior restaurado: {op.name}.")
                messagebox.showinfo(title, result.message, parent=self.root)
            else:
                title = "Rollback não confirmado"
                self.status.set(f"A reversão de {op.name} não foi confirmada.")
                messagebox.showwarning(title, result.message, parent=self.root)
        self._finish_close()

    # -----------------------------------------------------------------------
    # Scan states
    # -----------------------------------------------------------------------

    def _start_initial_scan(self):
        if self.manager.operations:
            self._on_scan_states()

    def _on_scan_states(self):
        if not self.manager.operations or self._busy:
            return
        self.current_states.clear()
        self._run_background(
            "scan",
            lambda: self.manager.inspect_all_states(self._queue_scan_progress, max_workers=4),
        )

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------

    def _on_dry_run(self):
        selected = self.manager.get_selected_operations()
        if not selected:
            messagebox.showinfo("Pré-visualização", "Marque pelo menos uma ação.", parent=self.root)
            return
        self._run_background("dry_run", lambda: [op.get_dry_run_description() for op in selected],
                             ops=selected)

    def _show_dry_run(self, descriptions: list[dict]):
        win = tk.Toplevel(self.root)
        win.title("Pré-visualização — nenhuma mudança será feita")
        win.geometry("820x600")
        win.configure(bg=C["bg"])
        win.resizable(True, True)

        tk.Label(win, text="Pré-visualização de mudanças", fg=C["text"], bg=C["bg"],
                 font=(self.ff, 15, "bold"), anchor="w", padx=20, pady=14).pack(fill=tk.X)
        tk.Label(win, text="Nenhum comando foi executado. Esta tela é apenas informativa.",
                 fg=C["text2"], bg=C["bg"], font=(self.ff, 9), anchor="w",
                 padx=20, pady=0).pack(fill=tk.X)

        txt = scrolledtext.ScrolledText(win, bg=C["surface"], fg=C["text"],
                                         font=(self.ff, 9), padx=12, pady=10,
                                         relief=tk.FLAT, wrap=tk.WORD,
                                         highlightthickness=1, highlightbackground=C["border"])
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        txt.tag_configure("h", font=(self.ff, 11, "bold"), foreground=C["accent"])
        txt.tag_configure("warn", foreground=C["warn"])

        admin_needed = any(d.get("requires_admin") for d in descriptions)
        if admin_needed and not self.manager.os_info.get("is_admin"):
            txt.insert(tk.END, "⚠ Algumas ações requerem administrador e o Purify pode não estar elevado.\n\n", "warn")

        for d in descriptions:
            txt.insert(tk.END, f"{d.get('name', 'Operação')}\n", "h")
            if not d.get("available"):
                txt.insert(tk.END, f"  Não disponível: {d.get('error', 'estado desconhecido')}\n\n")
                continue
            txt.insert(tk.END, f"  Estado atual: {OperationCard._format_state(d.get('current_state'))[0]}\n")
            txt.insert(tk.END, f"  Ação: {d.get('planned_action', '—')}\n")
            txt.insert(tk.END, f"  Impacto: {d.get('estimated_impact', '—')}\n")
            txt.insert(tk.END, f"  Risco: {d.get('risk', '—')} | Reversão: {d.get('rollback_plan', '—')}\n\n")
        txt.configure(state=tk.DISABLED)

        _btn(win, "Fechar", win.destroy, bg=C["btn_neutral"], hbg=C["btn_neutral_h"],
             fg=C["text"]).pack(anchor="e", padx=16, pady=(0, 12))

    # -----------------------------------------------------------------------
    # Execute
    # -----------------------------------------------------------------------

    def _on_execute(self):
        selected = self.manager.get_selected_operations()
        if not selected:
            messagebox.showinfo("Execução", "Marque pelo menos uma ação.", parent=self.root)
            return

        lines = [f"• {op.name} — {op.risk.value} | {op.reversibility.value}" for op in selected]

        # Verifica se criará restore point
        has_admin = any(op.requires_admin for op in selected)
        is_win = self.manager.os_info.get("platform") == "windows"
        rp_note = (
            "\n\n🛡 O Purify tentará criar e confirmar um ponto de restauração por dois métodos. "
            "Se ambos falharem, nenhuma ação será executada."
            if (has_admin and is_win) else ""
        )

        prompt = ("O Purify executará estas ações:\n\n" + "\n".join(lines) + rp_note
                  + "\n\nDeseja continuar?")
        if not messagebox.askyesno("Confirmar ações", prompt, parent=self.root):
            return

        critical = [op for op in selected if op.risk is RiskLevel.CRITICAL]
        if critical and not messagebox.askyesno(
            "Confirmação extra — risco crítico",
            "ATENÇÃO: As seguintes ações são de risco crítico:\n\n"
            + "\n".join(f"• {op.name}: {op.description}" for op in critical)
            + "\n\nConfirmar uma segunda vez?",
            parent=self.root,
        ):
            return

        self._cancel_event = threading.Event()
        self._run_background(
            "execute",
            lambda: self.manager.execute_selected(self._queue_log, self._cancel_event),
            ops=selected,
        )

    def _show_execution_summary(self, results: list[tuple[Operation, OperationResult]]):
        from collections import Counter
        counts: Counter = Counter()
        for op, result in results:
            counts[result.state] += 1
            state = result.after if result.after is not None else result.before
            if state is not None:
                self.current_states[op.id] = state
            self.card_grid.update_result(op, result)

        lines = [
            f"Sucesso verificado:   {counts[OperationState.SUCCESS]}",
            f"Já estava aplicado:   {counts[OperationState.ALREADY_APPLIED]}",
            f"Não aplicável:        {counts[OperationState.NOT_APPLICABLE]}",
            f"Incerto:              {counts[OperationState.UNCERTAIN]}",
            f"Falhou:               {counts[OperationState.FAILED]}",
            f"Cancelado:            {counts[OperationState.CANCELLED]}",
        ]
        has_fail = counts[OperationState.FAILED] > 0
        has_unc = counts[OperationState.UNCERTAIN] > 0
        title = (
            "Concluído com falhas" if has_fail
            else "Concluído com resultado incerto" if has_unc
            else "Lote concluído com sucesso"
        )
        self.status.set(title + ".")
        self._append_log("Resumo: " + "; ".join(l.strip() for l in lines), "ok" if not has_fail else "danger")
        (messagebox.showwarning if (has_fail or has_unc) else messagebox.showinfo)(
            title, "\n".join(lines), parent=self.root
        )

    # -----------------------------------------------------------------------
    # Log
    # -----------------------------------------------------------------------

    def _toggle_log(self):
        if self._log_panel is None or not self._log_panel.winfo_exists():
            self._log_panel = LogPanel(self.root, self.ff)
        else:
            if self._log_panel.winfo_viewable():
                self._log_panel.withdraw()
            else:
                self._log_panel.deiconify()

    def _append_log(self, message: str, tag: str = ""):
        if self._log_panel and self._log_panel.winfo_exists():
            self._log_panel.append(message, tag)
        low = message.lower()
        if not tag:
            if "concluído" in low or "sucesso" in low:
                tag = "ok"
            elif "falhou" in low or "erro" in low:
                tag = "danger"
            elif "incerto" in low:
                tag = "warn"

    # -----------------------------------------------------------------------
    # State / busy
    # -----------------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self.progress.grid()
            self.progress.start(10)
            self.btn_scan.configure(state="disabled", cursor="arrow", bg=C["muted"])
            if self._cancel_event is not None:
                self.btn_cancel.grid()
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self.btn_scan.configure(state="normal", cursor="hand2", bg=C["btn_neutral"])
            self.btn_cancel.grid_remove()
        self._update_action_buttons()
        self._update_sidebar_count()

    def _on_cancel(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.btn_cancel.configure(state="disabled", cursor="arrow")
            self.status.set("Cancelamento solicitado. A ação atual terminará antes.")

    def _on_close(self):
        if self._worker and self._worker.is_alive():
            if not messagebox.askyesno(
                "Processo em andamento",
                "Fechar após a ação atual terminar?",
                parent=self.root,
            ):
                return
            if self._cancel_event:
                self._cancel_event.set()
            self._closing = True
            self.status.set("Aguardando término seguro…")
            return
        self.root.destroy()

    def _finish_close(self):
        if self._closing and (not self._worker or not self._worker.is_alive()):
            self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_gui() -> None:
    root = tk.Tk()
    PurifyApp(root)
    root.mainloop()
