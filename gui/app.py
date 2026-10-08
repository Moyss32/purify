from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from core.manager import PurifyManager
from core.operations import Operation, OperationResult, OperationState, ReversibilityLevel, RiskLevel


PALETTE = {
    "canvas": "#F3F0E7",       # papel quente, sem branco clínico
    "panel": "#FBFAF5",
    "panel_alt": "#F6F3EB",
    "ink": "#262833",
    "muted": "#535760",
    "line": "#D2CFC4",
    "blue": "#31385D",
    "blue_hover": "#29314D",
    "blue_soft": "#E6E8EE",
    "rust": "#9C4A35",
    "rust_hover": "#813D2D",
    "rust_soft": "#F6E9E4",
    "amber": "#805A1E",
    "amber_soft": "#F3ECD9",
    "dblue": "#345C72",
    "dblue_soft": "#E8E8F1",
    "white": "#FFFFFF",
    "disabled": "#E6E3DA",
}

_STATE_TAGS = {
    OperationState.SUCCESS: "success",
    OperationState.ALREADY_APPLIED: "already",
    OperationState.FAILED: "failed",
    OperationState.UNCERTAIN: "uncertain",
    OperationState.NOT_APPLICABLE: "muted",
    OperationState.CANCELLED: "muted",
}


def _format_value(value: Any) -> str:
    if value is None:
        return "Ainda não verificado"
    if isinstance(value, dict):
        if value.get("known") is False:
            return f"Não foi possível verificar — {value.get('error', 'erro de consulta')}"
        if value.get("found") is False:
            return "Não encontrado nesta instalação"
        if "installed" in value:
            return "Instalado" if value["installed"] else "Não instalado"
        if "unit_file_state" in value:
            return (
                f"Inicialização: {value.get('unit_file_state', 'desconhecida')}; "
                f"atividade: {value.get('active_state', 'desconhecida')}"
            )
        if "start_mode" in value:
            return f"Inicialização: {value.get('start_mode')}; estado: {value.get('status')}"
        if "deb_count" in value:
            return f"{value['deb_count']} arquivo(s) .deb; {value.get('size_bytes', '?')} bytes"
        return "; ".join(f"{key}: {val}" for key, val in value.items() if key != "packages")
    return str(value)


def _list_name(op: Operation) -> str:
    """Na tabela, prioriza o nome do item; o verbo aparece no painel de detalhes."""
    for prefix in ("Remover ", "Desativar "):
        if op.name.startswith(prefix):
            return op.name[len(prefix):]
    return op.name


def _compact_state(value: Any) -> str:
    text = _format_value(value)
    text = text.replace("Não encontrado nesta instalação", "Não encontrado")
    text = text.replace("Ainda não verificado", "Não verificado")
    text = text.replace("Inicialização: ", "")
    return text.replace("; estado: ", " · ")


class PurifyApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Purify — manutenção do sistema")
        self.root.geometry("1360x830")
        self.root.minsize(1100, 700)
        self.manager = PurifyManager()

        self.category_trees: dict[str, ttk.Treeview] = {}
        self.item_to_op: dict[str, Operation] = {}
        self.current_selected_op: Operation | None = None
        self.current_category: str | None = None
        self._visible_operations: list[Operation] = []
        self._category_names: list[str] = []
        self._events: queue.Queue[tuple] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._closing = False
        self._busy = False
        self.current_states: dict[str, Any] = {}
        self.search_var = tk.StringVar(value="")

        self._configure_theme()
        self._build_ui()
        self._populate_operations()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind_all("<Control-f>", self._focus_search)
        self.root.bind_all("<Escape>", self._clear_search_on_escape)
        self.root.after(100, self._poll_events)
        self.root.after(250, self._start_initial_scan)

    def _configure_theme(self) -> None:
        self.root.configure(bg=PALETTE["canvas"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        available = set(self.root.tk.call("font", "families"))
        self.font_family = next(
            (name for name in ("Segoe UI", "Noto Sans", "Inter", "DejaVu Sans") if name in available),
            "TkDefaultFont",
        )
        for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10), ("TkHeadingFont", 11)):
            try:
                tkfont.nametofont(name).configure(family=self.font_family, size=size)
            except tk.TclError:
                pass

        style.configure("TFrame", background=PALETTE["canvas"])
        style.configure("Panel.TFrame", background=PALETTE["panel"])
        style.configure("TLabel", background=PALETTE["canvas"], foreground=PALETTE["ink"], font=(self.font_family, 10))
        style.configure("Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["ink"], font=(self.font_family, 10))
        style.configure("Muted.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["muted"], font=(self.font_family, 9))
        style.configure("Section.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["muted"], font=(self.font_family, 9, "bold"))
        style.configure("Title.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["ink"], font=(self.font_family, 14, "bold"))
        style.configure("Metric.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["blue"], font=(self.font_family, 9, "bold"))
        style.configure("Critical.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["rust"], font=(self.font_family, 10, "bold"))
        style.configure("Warning.Panel.TLabel", background=PALETTE["panel"], foreground=PALETTE["amber"], font=(self.font_family, 10, "bold"))

        style.configure("TButton", font=(self.font_family, 10), padding=(11, 8), borderwidth=1)
        style.configure("Primary.TButton", background=PALETTE["blue"], foreground=PALETTE["white"], bordercolor=PALETTE["blue"], font=(self.font_family, 10, "bold"), padding=(13, 9))
        style.map("Primary.TButton", background=[("disabled", PALETTE["disabled"]), ("pressed", PALETTE["blue_hover"]), ("active", PALETTE["blue_hover"])], foreground=[("disabled", PALETTE["muted"])])
        style.configure("Danger.TButton", background=PALETTE["rust"], foreground=PALETTE["white"], bordercolor=PALETTE["rust"], font=(self.font_family, 10, "bold"), padding=(13, 9))
        style.map("Danger.TButton", background=[("disabled", PALETTE["disabled"]), ("pressed", PALETTE["rust_hover"]), ("active", PALETTE["rust_hover"])], foreground=[("disabled", PALETTE["muted"])])
        style.configure("Secondary.TButton", background=PALETTE["panel"], foreground=PALETTE["ink"], bordercolor=PALETTE["line"], padding=(10, 7))
        style.map("Secondary.TButton", background=[("pressed", PALETTE["blue_soft"]), ("active", PALETTE["blue_soft"])])
        style.configure("TProgressbar", background=PALETTE["blue"], troughcolor=PALETTE["line"], bordercolor=PALETTE["line"], lightcolor=PALETTE["blue"], darkcolor=PALETTE["blue"])
        style.configure("Vertical.TScrollbar", background=PALETTE["panel_alt"], troughcolor=PALETTE["panel"], bordercolor=PALETTE["panel"], arrowcolor=PALETTE["muted"])
        style.configure("Horizontal.TScrollbar", background=PALETTE["panel_alt"], troughcolor=PALETTE["panel"], bordercolor=PALETTE["panel"], arrowcolor=PALETTE["muted"])

        style.configure(
            "Purify.Treeview",
            background=PALETTE["panel"],
            fieldbackground=PALETTE["panel"],
            foreground=PALETTE["ink"],
            rowheight=38,
            font=(self.font_family, 10),
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Purify.Treeview.Heading",
            background="#E8E4D9",
            foreground=PALETTE["ink"],
            font=(self.font_family, 9, "bold"),
            relief="flat",
            padding=(9, 10),
        )
        style.map("Purify.Treeview", background=[("selected", PALETTE["blue_soft"])], foreground=[("selected", PALETTE["ink"])])
        style.map("Purify.Treeview.Heading", background=[("active", "#DDD9CE")])

    @staticmethod
    def _panel(parent: tk.Widget) -> tuple[tk.Frame, tk.Frame]:
        """Painel com filete de separação, sem sombra ou cantos arredondados."""
        border = tk.Frame(parent, bg=PALETTE["line"], bd=0, highlightthickness=0)
        body = tk.Frame(border, bg=PALETTE["panel"], bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        return border, body

    def _button(self, parent: tk.Widget, text: str, command, kind: str = "secondary") -> tk.Button:
        palettes = {
            "primary": (PALETTE["blue"], PALETTE["blue_hover"], PALETTE["white"]),
            "danger": (PALETTE["rust"], PALETTE["rust_hover"], PALETTE["white"]),
            "header": ("#E7EEE6", "#D4E0D4", PALETTE["ink"]),
            "secondary": (PALETTE["panel_alt"], PALETTE["blue_soft"], PALETTE["ink"]),
        }
        background, hover, foreground = palettes[kind]
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=hover,
            activeforeground=foreground,
            disabledforeground=PALETTE["muted"],
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=8,
            highlightthickness=1,
            highlightbackground=PALETTE["line"],
            highlightcolor=PALETTE["blue"],
            takefocus=True,
            cursor="hand2",
            font=(self.font_family, 10, "bold" if kind == "primary" else "normal"),
        )
        button._purify_colors = (background, hover, foreground)
        button._purify_enabled = True
        button.bind("<Enter>", self._on_button_enter, add="+")
        button.bind("<Leave>", self._on_button_leave, add="+")
        return button

    @staticmethod
    def _on_button_enter(event: tk.Event) -> None:
        button = event.widget
        if getattr(button, "_purify_enabled", False):
            _normal, hover, _foreground = button._purify_colors
            button.configure(bg=hover)

    @staticmethod
    def _on_button_leave(event: tk.Event) -> None:
        button = event.widget
        if getattr(button, "_purify_enabled", False):
            normal, _hover, _foreground = button._purify_colors
            button.configure(bg=normal)

    @staticmethod
    def _set_button_enabled(button: tk.Button, enabled: bool) -> None:
        normal, _hover, foreground = button._purify_colors
        button._purify_enabled = enabled
        button.configure(
            state=tk.NORMAL if enabled else tk.DISABLED,
            bg=normal if enabled else PALETTE["disabled"],
            fg=foreground if enabled else PALETTE["muted"],
            cursor="hand2" if enabled else "arrow",
        )

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=PALETTE["canvas"], padx=16, pady=14)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        self._build_header(shell)
        self._build_notice(shell)
        self._build_workspace(shell)
        self._build_footer(shell)

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=PALETTE["ink"], height=82)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_propagate(False)
        accent = tk.Frame(header, bg="#B66A43", width=6)
        accent.pack(side=tk.LEFT, fill=tk.Y)
        content = tk.Frame(header, bg=PALETTE["ink"], padx=18, pady=12)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        brand = tk.Frame(content, bg=PALETTE["ink"])
        brand.pack(side=tk.LEFT, anchor=tk.W, fill=tk.Y)
        tk.Label(brand, text="PURIFY", bg=PALETTE["ink"], fg="#F5F1E8", font=(self.font_family, 21, "bold")).pack(anchor=tk.W)
        tk.Label(brand, text="MANUTENÇÃO DO SISTEMA, SEM SURPRESAS", bg=PALETTE["ink"], fg="#D1D7D1", font=(self.font_family, 9, "bold")).pack(anchor=tk.W, pady=(1, 0))

        right = tk.Frame(content, bg=PALETTE["ink"])
        right.pack(side=tk.RIGHT, anchor=tk.E, fill=tk.Y)
        platform = self.manager.os_info.get("distribution_name") or self.manager.os_info.get("platform", "Sistema não identificado")
        version = self.manager.os_info.get("distribution_version") or self.manager.os_info.get("release", "")
        self.system_label = tk.Label(
            right,
            text=f"{platform} {version}".strip(),
            bg="#3D4C43",
            fg="#F5F1E8",
            font=(self.font_family, 10, "bold"),
            padx=12,
            pady=7,
        )
        self.system_label.pack(side=tk.RIGHT, anchor=tk.E, padx=(10, 0), pady=(7, 0))
        elevated = "Administrador / root" if self.manager.os_info.get("is_admin") else "Conta padrão"
        tk.Label(right, text=elevated, bg=PALETTE["ink"], fg="#D1D7D1", font=(self.font_family, 9)).pack(side=tk.RIGHT, anchor=tk.E, pady=(12, 0))
        self.btn_scan = self._button(right, text="Atualizar estados", command=self._on_scan_states, kind="header")
        self.btn_scan.pack(side=tk.RIGHT, anchor=tk.E, padx=(0, 14), pady=(6, 0))

    def _build_notice(self, parent: tk.Widget) -> None:
        notice = tk.Frame(parent, bg=PALETTE["blue_soft"])
        notice.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        tk.Frame(notice, bg=PALETTE["blue"], width=4).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(
            notice,
            text="Os estados são consultados automaticamente. Essa leitura não altera o computador; nenhuma ação ocorre sem sua seleção e confirmação.",
            bg=PALETTE["blue_soft"],
            fg=PALETTE["ink"],
            font=(self.font_family, 10),
            anchor=tk.W,
            padx=12,
            pady=10,
        ).pack(fill=tk.X, expand=True)

    def _build_workspace(self, parent: tk.Widget) -> None:
        workspace = tk.Frame(parent, bg=PALETTE["canvas"])
        workspace.grid(row=2, column=0, sticky="nsew")
        workspace.columnconfigure(0, minsize=184, weight=0)
        workspace.columnconfigure(1, minsize=440, weight=3)
        workspace.columnconfigure(2, minsize=340, weight=2)
        workspace.rowconfigure(0, weight=1)

        nav_shell, nav = self._panel(workspace)
        nav_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._build_navigation(nav)

        list_shell, listing = self._panel(workspace)
        list_shell.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self._build_operation_list(listing)

        details_shell, details = self._panel(workspace)
        details_shell.grid(row=0, column=2, sticky="nsew")
        self._build_details(details)

    def _build_navigation(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        tk.Label(parent, text="NAVEGAR", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 9, "bold"), anchor=tk.W).grid(row=0, column=0, sticky="ew", padx=14, pady=(17, 7))
        self.category_list = tk.Listbox(
            parent,
            bg=PALETTE["panel"],
            fg=PALETTE["ink"],
            selectbackground=PALETTE["blue"],
            selectforeground=PALETTE["white"],
            activestyle="none",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=PALETTE["panel"],
            highlightcolor=PALETTE["blue"],
            font=(self.font_family, 10),
            selectborderwidth=0,
            exportselection=False,
        )
        self.category_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.category_list.bind("<<ListboxSelect>>", self._on_category_select)

        bottom = tk.Frame(parent, bg=PALETTE["panel_alt"], padx=12, pady=12)
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 12))
        tk.Label(bottom, text="ANTES DE AGIR", bg=PALETTE["panel_alt"], fg=PALETTE["rust"], font=(self.font_family, 9, "bold"), anchor=tk.W).pack(fill=tk.X)
        tk.Label(
            bottom,
            text="Confira risco e reversibilidade. Itens críticos pedem uma confirmação extra.",
            bg=PALETTE["panel_alt"],
            fg=PALETTE["ink"],
            font=(self.font_family, 9),
            justify=tk.LEFT,
            wraplength=150,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(5, 0))

    def _build_operation_list(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)
        head = tk.Frame(parent, bg=PALETTE["panel"], padx=15, pady=14)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.lbl_category_title = ttk.Label(head, text="Operações", style="Title.Panel.TLabel")
        self.lbl_category_title.grid(row=0, column=0, sticky="w")
        self.lbl_catalog_summary = ttk.Label(head, text="", style="Muted.Panel.TLabel")
        self.lbl_catalog_summary.grid(row=1, column=0, sticky="w", pady=(4, 0))

        searchrow = tk.Frame(parent, bg=PALETTE["panel"], padx=15)
        searchrow.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        searchrow.columnconfigure(0, weight=1)
        tk.Label(searchrow, text="BUSCAR POR NOME OU FINALIDADE", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 9, "bold"), anchor=tk.W).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.search_entry = tk.Entry(
            searchrow,
            textvariable=self.search_var,
            bg=PALETTE["white"],
            fg=PALETTE["ink"],
            insertbackground=PALETTE["ink"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=PALETTE["line"],
            highlightcolor=PALETTE["blue"],
            font=(self.font_family, 10),
        )
        self.search_entry.grid(row=1, column=0, sticky="ew", ipady=8)
        self.btn_clear_search = self._button(searchrow, text="Limpar", command=lambda: self.search_var.set(""))
        self.btn_clear_search.grid(row=1, column=1, sticky="e", padx=(8, 0))
        self.search_var.trace_add("write", self._on_search_changed)

        table_frame = tk.Frame(parent, bg=PALETTE["panel"], padx=10, pady=0)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.operations_tree = ttk.Treeview(
            table_frame,
            columns=("check", "name", "risk", "state"),
            show="headings",
            selectmode="browse",
            style="Purify.Treeview",
        )
        for column, title in (("check", "Usar"), ("name", "Operação"), ("risk", "Risco"), ("state", "Situação")):
            self.operations_tree.heading(column, text=title)
        self.operations_tree.column("check", width=44, anchor=tk.CENTER, stretch=False)
        self.operations_tree.column("name", width=180, anchor=tk.W, stretch=True)
        self.operations_tree.column("risk", width=88, anchor=tk.CENTER, stretch=False)
        self.operations_tree.column("state", width=125, anchor=tk.W, stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.operations_tree.yview)
        self.operations_tree.configure(yscrollcommand=scrollbar.set)
        self.operations_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.operations_tree.tag_configure("success", foreground=PALETTE["blue"])
        self.operations_tree.tag_configure("failed", foreground=PALETTE["rust"])
        self.operations_tree.tag_configure("uncertain", foreground=PALETTE["amber"])
        self.operations_tree.tag_configure("already", foreground=PALETTE["dblue"])
        self.operations_tree.tag_configure("muted", foreground=PALETTE["muted"])
        self.operations_tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.operations_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.lbl_empty = tk.Label(parent, text="Nenhuma operação corresponde à busca.", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 10), anchor=tk.W)
        self.lbl_empty.grid(row=4, column=0, sticky="ew", padx=15, pady=(8, 14))
        self.lbl_empty.grid_remove()
        hint = tk.Label(parent, text="Marque “Usar” para incluir. A prévia ajuda a entender cada mudança antes de executá-la.", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 9), anchor=tk.W, padx=15)
        hint.grid(row=5, column=0, sticky="ew", pady=(0, 13))

    def _build_details(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(7, weight=1)
        tk.Label(parent, text="DETALHES DA AÇÃO", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 9, "bold"), anchor=tk.W).grid(row=0, column=0, sticky="ew", padx=15, pady=(16, 6))
        self.lbl_op_name = ttk.Label(parent, text="Escolha uma operação", style="Title.Panel.TLabel", wraplength=315)
        self.lbl_op_name.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 7))
        self.txt_op_desc = tk.Text(
            parent,
            height=4,
            wrap=tk.WORD,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=PALETTE["line"],
            bg=PALETTE["panel_alt"],
            fg=PALETTE["ink"],
            font=(self.font_family, 10),
            padx=9,
            pady=8,
            spacing1=1,
            spacing3=2,
            state=tk.DISABLED,
        )
        self.txt_op_desc.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 10))

        facts = tk.Frame(parent, bg=PALETTE["panel"], padx=15)
        facts.grid(row=3, column=0, sticky="ew")
        facts.columnconfigure(0, weight=1)
        facts.columnconfigure(1, weight=1)
        self.lbl_op_risk = ttk.Label(facts, text="Risco: —", style="Panel.TLabel", wraplength=145)
        self.lbl_op_rev = ttk.Label(facts, text="Reversibilidade: —", style="Panel.TLabel", wraplength=205)
        self.lbl_op_admin = ttk.Label(facts, text="Privilégios: —", style="Panel.TLabel", wraplength=145)
        self.lbl_op_risk.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.lbl_op_rev.grid(row=0, column=1, sticky="w", padx=(4, 0), pady=4)
        self.lbl_op_admin.grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        self.lbl_op_state = ttk.Label(parent, text="Situação: aguardando verificação", style="Muted.Panel.TLabel", wraplength=315)
        self.lbl_op_state.grid(row=4, column=0, sticky="ew", padx=15, pady=(5, 7))

        tools = tk.Frame(parent, bg=PALETTE["panel"], padx=15)
        tools.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.btn_check = self._button(tools, text="Verificar agora", command=self._on_check_state)
        self.btn_check.pack(side=tk.LEFT)
        self.btn_rollback = self._button(tools, text="Reverter", command=self._on_rollback)
        self.btn_rollback.pack(side=tk.RIGHT)

        actions = tk.Frame(parent, bg=PALETTE["panel_alt"], padx=13, pady=12)
        actions.grid(row=6, column=0, sticky="ew", padx=12, pady=(3, 10))
        actions.columnconfigure(0, weight=1)
        self.lbl_selection = tk.Label(actions, text="Nenhuma ação selecionada", bg=PALETTE["panel_alt"], fg=PALETTE["muted"], font=(self.font_family, 9), anchor=tk.W)
        self.lbl_selection.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.btn_dry_run = self._button(actions, text="Pré-visualizar", command=self._on_dry_run)
        self.btn_dry_run.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.btn_execute = self._button(actions, text="Executar selecionadas", command=self._on_execute, kind="primary")
        self.btn_execute.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        self.btn_cancel = self._button(actions, text="Solicitar cancelamento", command=self._on_cancel, kind="danger")
        self.btn_cancel.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.btn_cancel.grid_remove()
        self._set_button_enabled(self.btn_check, False)
        self._set_button_enabled(self.btn_rollback, False)
        self._set_button_enabled(self.btn_dry_run, False)
        self._set_button_enabled(self.btn_execute, False)
        self._set_button_enabled(self.btn_cancel, False)

        activity = tk.Frame(parent, bg=PALETTE["panel"], padx=15, pady=0)
        activity.grid(row=7, column=0, sticky="nsew")
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(1, weight=1)
        tk.Label(activity, text="ATIVIDADE RECENTE", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 9, "bold"), anchor=tk.W).grid(row=0, column=0, sticky="ew", pady=(2, 6))
        self.txt_log = scrolledtext.ScrolledText(
            activity,
            state=tk.DISABLED,
            wrap=tk.WORD,
            height=7,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=PALETTE["line"],
            bg=PALETTE["panel_alt"],
            fg=PALETTE["ink"],
            font=(self.font_family, 9),
            padx=8,
            pady=7,
        )
        self.txt_log.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        self.txt_log.tag_configure("success", foreground=PALETTE["blue"])
        self.txt_log.tag_configure("failed", foreground=PALETTE["rust"])
        self.txt_log.tag_configure("uncertain", foreground=PALETTE["amber"])
        self.txt_log.tag_configure("already", foreground=PALETTE["dblue"])
        self.txt_log.tag_configure("muted", foreground=PALETTE["muted"])

    def _build_footer(self, parent: tk.Widget) -> None:
        footer = tk.Frame(parent, bg=PALETTE["canvas"])
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Pronto. Nada será alterado sem sua confirmação.")
        self.lbl_status = tk.Label(footer, textvariable=self.status, bg=PALETTE["canvas"], fg=PALETTE["muted"], font=(self.font_family, 9), anchor=tk.W)
        self.lbl_status.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.progress.grid_remove()

    def _populate_operations(self) -> None:
        self._category_names = self.manager.get_all_categories()
        if not self._category_names:
            self.category_list.insert(tk.END, "Nenhuma categoria")
            self.category_list.config(state=tk.DISABLED)
            self.lbl_category_title.config(text="Sem operações disponíveis")
            self.lbl_catalog_summary.config(text="Esta plataforma não possui um catálogo reconhecido.")
            self.lbl_empty.config(text="Nenhuma operação está disponível para a plataforma detectada.")
            self.lbl_empty.grid()
            self._set_button_enabled(self.btn_scan, False)
            self._update_selection_summary()
            return

        for category in self._category_names:
            count = len(self.manager.get_operations_by_category(category))
            self.category_list.insert(tk.END, f"{category}   {count}")
        self.category_list.selection_set(0)
        self._show_category(self._category_names[0])

    def _show_category(self, category: str) -> None:
        self.current_category = category
        self.current_selected_op = None
        self._clear_details()
        self.lbl_category_title.config(text=category)
        self._render_operations()

    def _on_category_select(self, _event: tk.Event | None = None) -> None:
        selected = self.category_list.curselection()
        if not selected or selected[0] >= len(self._category_names):
            return
        category = self._category_names[selected[0]]
        if category != self.current_category:
            self._show_category(category)

    def _on_search_changed(self, *_args: Any) -> None:
        if self.current_category is not None:
            self._render_operations()

    def _focus_search(self, _event: tk.Event | None = None) -> str:
        self.search_entry.focus_set()
        return "break"

    def _clear_search_on_escape(self, _event: tk.Event | None = None) -> str | None:
        if self.search_var.get():
            self.search_var.set("")
            return "break"
        return None

    def _render_operations(self) -> None:
        if not self.current_category:
            return
        tree = self.operations_tree
        children = tree.get_children()
        if children:
            tree.delete(*children)
        self.item_to_op.clear()

        query = self.search_var.get().strip().casefold()
        operations = self.manager.get_operations_by_category(self.current_category)
        visible: list[Operation] = []
        for op in operations:
            searchable = " ".join((op.name, op.description, op.category, op.risk.value)).casefold()
            if query and query not in searchable:
                continue
            state = self.current_states.get(op.id)
            state_text = "Consultando…" if self._busy and state is None else _compact_state(state)
            checkmark = "✓" if op.is_selected else "—"
            iid = tree.insert("", tk.END, values=(checkmark, _list_name(op), op.risk.value, state_text))
            self.item_to_op[iid] = op
            visible.append(op)
        self._visible_operations = visible
        self.lbl_empty.grid() if not visible else self.lbl_empty.grid_remove()
        if not visible:
            self.lbl_empty.config(text="Nenhuma operação corresponde à busca. Apague o filtro para ver a categoria inteira.")
        total = len(operations)
        self.lbl_catalog_summary.config(text=f"{len(visible)} de {total} operações nesta categoria")
        if self.current_selected_op and self.current_selected_op in visible:
            selected_iid = self._item_id_for_op(self.current_selected_op)
            if selected_iid:
                tree.selection_set(selected_iid)
                tree.focus(selected_iid)
        elif self.current_selected_op:
            self.current_selected_op = None
            self._clear_details()
        self._update_selection_summary()

    def _clear_details(self) -> None:
        self.lbl_op_name.config(text="Escolha uma operação")
        self.txt_op_desc.config(state=tk.NORMAL)
        self.txt_op_desc.delete("1.0", tk.END)
        self.txt_op_desc.insert(tk.END, "Selecione um item da lista para entender o que ele faz, o risco envolvido e se é possível reverter a mudança.")
        self.txt_op_desc.config(state=tk.DISABLED)
        self.lbl_op_risk.config(text="Risco: —", style="Panel.TLabel")
        self.lbl_op_rev.config(text="Reversibilidade: —")
        self.lbl_op_admin.config(text="Privilégios: —")
        self.lbl_op_state.config(text="Situação: aguardando verificação")
        self._set_button_enabled(self.btn_check, False)
        self._set_button_enabled(self.btn_rollback, False)

    def _get_op_from_tree(self, _tree: ttk.Treeview, item_id: str) -> Operation | None:
        return self.item_to_op.get(item_id)

    def _item_id_for_op(self, op: Operation) -> str | None:
        return next((iid for iid, item_op in self.item_to_op.items() if item_op is op), None)

    def _on_tree_click(self, event: tk.Event) -> None:
        tree = event.widget
        if tree.identify("region", event.x, event.y) != "cell" or tree.identify_column(event.x) != "#1":
            return
        iid = tree.identify_row(event.y)
        op = self._get_op_from_tree(tree, iid) if iid else None
        if not op:
            return
        if op.risk is RiskLevel.CRITICAL and not op.is_selected:
            confirm = messagebox.askyesno(
                "Ação crítica",
                f"{op.name}\n\nRisco: {op.risk.value}\n{op.description}\n\nDeseja incluir esta ação na seleção?",
                parent=self.root,
            )
            if not confirm:
                return
        op.is_selected = not op.is_selected
        values = list(tree.item(iid, "values"))
        values[0] = "✓" if op.is_selected else "—"
        tree.item(iid, values=values)
        self._update_selection_summary()
        self.status.set(f"Seleção atualizada: {len(self.manager.get_selected_operations())} ação(ões) marcada(s).")

    def _on_tree_select(self, _event: tk.Event | None = None) -> None:
        selection = self.operations_tree.selection()
        if not selection:
            return
        op = self._get_op_from_tree(self.operations_tree, selection[0])
        if op:
            self.current_selected_op = op
            self._update_details(op)

    def _update_details(self, op: Operation) -> None:
        self.lbl_op_name.config(text=op.name)
        self.txt_op_desc.config(state=tk.NORMAL)
        self.txt_op_desc.delete("1.0", tk.END)
        self.txt_op_desc.insert(tk.END, op.description)
        self.txt_op_desc.config(state=tk.DISABLED)
        if op.risk is RiskLevel.CRITICAL or op.risk is RiskLevel.HIGH:
            self.lbl_op_risk.config(text=f"Risco: {op.risk.value} — leia antes de continuar", style="Critical.Panel.TLabel")
        elif op.risk is RiskLevel.MEDIUM:
            self.lbl_op_risk.config(text=f"Risco: {op.risk.value}", style="Warning.Panel.TLabel")
        else:
            self.lbl_op_risk.config(text=f"Risco: {op.risk.value}", style="Panel.TLabel")
        self.lbl_op_rev.config(text=f"Reversibilidade: {op.reversibility.value}")
        self.lbl_op_admin.config(text=f"Privilégios: {'Administrador/root' if op.requires_admin else 'Não requer'}")
        known_state = self.current_states.get(op.id)
        self.lbl_op_state.config(text=f"Situação atual: {_format_value(known_state)}")
        self._set_button_enabled(self.btn_check, not self._busy)
        self._set_button_enabled(self.btn_rollback, not self._busy and op.reversibility is ReversibilityLevel.FULL)

    def _update_selection_summary(self) -> None:
        selected = self.manager.get_selected_operations()
        count = len(selected)
        if count == 0:
            text = "Nenhuma ação selecionada"
        elif count == 1:
            text = "1 ação selecionada"
        else:
            text = f"{count} ações selecionadas"
        self.lbl_selection.config(text=text)
        enabled = bool(count) and not self._busy
        self._set_button_enabled(self.btn_dry_run, enabled)
        self._set_button_enabled(self.btn_execute, enabled)

    def _tree_for_op(self, op: Operation) -> ttk.Treeview | None:
        return self.operations_tree if op.category == self.current_category and op in self._visible_operations else None

    def _set_op_state(self, op: Operation, state: Any) -> None:
        self.current_states[op.id] = state
        iid = self._item_id_for_op(op)
        tree = self._tree_for_op(op)
        if iid and tree:
            values = list(tree.item(iid, "values"))
            values[3] = _compact_state(state)
            tree.item(iid, values=values)
        if self.current_selected_op is op:
            self.lbl_op_state.config(text=f"Situação atual: {_format_value(state)}")

    def _on_check_state(self) -> None:
        op = self.current_selected_op
        if not op:
            return
        self._run_background("check", lambda: op.check_state(), op=op)

    def _start_initial_scan(self) -> None:
        if self.manager.operations:
            self._on_scan_states()

    def _on_scan_states(self) -> None:
        if not self.manager.operations:
            return
        if self._worker and self._worker.is_alive():
            return
        self.current_states.clear()
        if self.current_selected_op:
            self.lbl_op_state.config(text="Situação: consultando o catálogo…")
        self._render_operations()
        self._run_background(
            "scan",
            lambda: self.manager.inspect_all_states(self._queue_scan_progress, max_workers=4),
        )

    def _queue_scan_progress(self, op: Operation, state: Any, done: int, total: int) -> None:
        self._events.put(("scan_progress", op, state, done, total))

    def _on_rollback(self) -> None:
        op = self.current_selected_op
        if not op:
            return
        if op.reversibility is not ReversibilityLevel.FULL:
            messagebox.showwarning("Reversão indisponível", "Esta ação não tem reversão automática completa.", parent=self.root)
            return
        if not messagebox.askyesno("Confirmar reversão", f"Restaurar o estado salvo para “{op.name}”?", parent=self.root):
            return
        self._run_background("rollback", lambda: self.manager.rollback_operation(op, self._queue_log), op=op)

    def _on_dry_run(self) -> None:
        selected = self.manager.get_selected_operations()
        if not selected:
            messagebox.showinfo("Pré-visualização", "Marque pelo menos uma ação na lista.", parent=self.root)
            return
        self._run_background("dry_run", lambda: [op.get_dry_run_description() for op in selected], ops=selected)

    def _show_dry_run(self, descriptions: list[dict[str, Any]]) -> None:
        window = tk.Toplevel(self.root)
        window.title("Pré-visualização — nenhuma mudança será feita")
        window.geometry("780x580")
        window.minsize(650, 450)
        window.configure(bg=PALETTE["canvas"])
        frame = tk.Frame(window, bg=PALETTE["panel"], padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        tk.Label(frame, text="Revise as mudanças planejadas", bg=PALETTE["panel"], fg=PALETTE["ink"], font=(self.font_family, 15, "bold"), anchor=tk.W).pack(fill=tk.X)
        tk.Label(frame, text="Esta tela é somente informativa. Nenhum comando que altera o sistema foi executado.", bg=PALETTE["panel"], fg=PALETTE["muted"], font=(self.font_family, 10), anchor=tk.W, wraplength=700).pack(fill=tk.X, pady=(5, 10))
        text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, padx=10, pady=10, bg=PALETTE["panel_alt"], fg=PALETTE["ink"], font=(self.font_family, 10), relief=tk.FLAT, highlightthickness=1, highlightbackground=PALETTE["line"])
        text.pack(fill=tk.BOTH, expand=True)
        if any(item.get("requires_admin") for item in descriptions) and not self.manager.os_info.get("is_admin"):
            text.insert(tk.END, "Atenção: uma ou mais ações exigem privilégios de administrador/root.\n\n", "warning")
        for item in descriptions:
            text.insert(tk.END, f"{item.get('name', 'Operação')}\n", "heading")
            if not item.get("available"):
                text.insert(tk.END, f"Não disponível: {item.get('error', 'estado desconhecido')}\n\n")
                continue
            text.insert(tk.END, f"Estado atual: {_format_value(item.get('current_state'))}\n")
            text.insert(tk.END, f"O que será feito: {item.get('planned_action')}\n")
            text.insert(tk.END, f"Impacto estimado: {item.get('estimated_impact')}\n")
            text.insert(tk.END, f"Risco: {item.get('risk')} | Reversibilidade: {item.get('reversibility')}\n")
            text.insert(tk.END, f"Exige administrador/root: {'Sim' if item.get('requires_admin') else 'Não'}\n")
            text.insert(tk.END, f"Reversão: {item.get('rollback_plan')}\n\n")
        text.tag_configure("heading", font=(self.font_family, 11, "bold"), foreground=PALETTE["blue"])
        text.tag_configure("warning", font=(self.font_family, 10, "bold"), foreground=PALETTE["rust"])
        text.config(state=tk.DISABLED)
        self._button(frame, text="Fechar", command=window.destroy).pack(anchor=tk.E, pady=(10, 0))

    def _on_execute(self) -> None:
        selected = self.manager.get_selected_operations()
        if not selected:
            messagebox.showinfo("Execução", "Marque pelo menos uma ação na lista.", parent=self.root)
            return
        lines = [f"• {op.name} — risco {op.risk.value}; {op.reversibility.value}" for op in selected]
        prompt = "O Purify executará somente estas ações marcadas:\n\n" + "\n".join(lines) + "\n\nDeseja continuar?"
        if not messagebox.askyesno("Confirmar ações", prompt, parent=self.root):
            return
        critical = [op for op in selected if op.risk is RiskLevel.CRITICAL]
        if critical and not messagebox.askyesno(
            "Confirmação adicional — risco crítico",
            "Estas ações podem comprometer funções importantes do sistema:\n\n"
            + "\n".join(f"• {op.name}: {op.description}" for op in critical)
            + "\n\nConfirmar uma segunda vez?",
            parent=self.root,
        ):
            return
        self._cancel_event = threading.Event()
        self._run_background("execute", lambda: self.manager.execute_selected(self._queue_log, self._cancel_event), ops=selected)

    def _run_background(self, kind: str, action, **metadata) -> None:
        if self._worker and self._worker.is_alive():
            return
        if kind != "execute":
            self._cancel_event = None
        self._set_busy(True)
        self.status.set("Verificando os itens do catálogo…" if kind == "scan" else "Processando. A janela continuará responsiva…")

        def worker() -> None:
            try:
                value = action()
                self._events.put(("done", kind, value, metadata))
            except Exception as exc:
                self._events.put(("error", kind, str(exc), metadata))

        self._worker = threading.Thread(target=worker, name="purify-worker", daemon=True)
        self._worker.start()

    def _queue_log(self, message: str) -> None:
        self._events.put(("log", message))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "log":
                    self._log(event[1])
                elif event[0] == "scan_progress":
                    _, op, state, done, total = event
                    self._set_op_state(op, state)
                    self.status.set(f"Verificando catálogo: {done} de {total} — {op.name}")
                elif event[0] == "error":
                    _, _kind, error, _metadata = event
                    self._set_busy(False)
                    self.status.set("O processo não pôde ser concluído.")
                    self._log(f"Falhou: {error}")
                    messagebox.showerror("Falha", error, parent=self.root)
                    self._finish_close_if_requested()
                elif event[0] == "done":
                    _, kind, value, metadata = event
                    self._handle_done(kind, value, metadata)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _handle_done(self, kind: str, value: Any, metadata: dict) -> None:
        self._set_busy(False)
        if kind == "check":
            op = metadata.get("op")
            if op:
                self._set_op_state(op, value)
            self.status.set("Verificação concluída.")
        elif kind == "dry_run":
            self._show_dry_run(value)
            self.status.set("Pré-visualização concluída; nenhuma mudança foi feita.")
        elif kind == "scan":
            unknown = sum(not isinstance(state, dict) or not state.get("known", False) for _, state in value)
            known = len(value) - unknown
            self.status.set(f"Leitura concluída: {known} de {len(value)} estados identificados.")
            self._log(f"Leitura do catálogo: {known} estado(s) conhecido(s); {unknown} desconhecido(s). Nenhuma mudança foi feita.")
        elif kind == "rollback":
            op = metadata.get("op")
            if op:
                tree = self._tree_for_op(op)
                iid = self._item_id_for_op(op)
                if tree and iid:
                    tree.item(iid, tags=(_STATE_TAGS.get(value.state, ""),))
                if value.after is not None:
                    self._set_op_state(op, value.after)
            self.status.set("Reversão confirmada." if value.state is OperationState.SUCCESS else f"Reversão: {value.state.value}.")
            messagebox.showinfo("Resultado da reversão", f"{value.state.value}: {value.message}", parent=self.root)
        elif kind == "execute":
            self._show_execution_summary(value)
        self._finish_close_if_requested()

    def _show_execution_summary(self, results: list[tuple[Operation, OperationResult]]) -> None:
        counts = {state: 0 for state in OperationState}
        for op, result in results:
            counts[result.state] = counts.get(result.state, 0) + 1
            self._set_op_state(op, result.after if result.after is not None else result.before)
            tree = self._tree_for_op(op)
            iid = self._item_id_for_op(op)
            tag = _STATE_TAGS.get(result.state)
            if tree and iid and tag:
                tree.item(iid, tags=(tag,))
        lines = [
            f"Sucesso verificado: {counts[OperationState.SUCCESS]}",
            f"Já estava aplicado: {counts[OperationState.ALREADY_APPLIED]}",
            f"Não aplicável: {counts[OperationState.NOT_APPLICABLE]}",
            f"Incerto: {counts[OperationState.UNCERTAIN]}",
            f"Falhou: {counts[OperationState.FAILED]}",
            f"Cancelado: {counts[OperationState.CANCELLED]}",
        ]
        has_failures = counts[OperationState.FAILED] > 0
        has_uncertain = counts[OperationState.UNCERTAIN] > 0
        has_cancelled = counts[OperationState.CANCELLED] > 0
        title = (
            "Concluído com falhas" if has_failures
            else "Concluído com resultado incerto" if has_uncertain
            else "Lote cancelado" if has_cancelled
            else "Lote concluído"
        )
        self.status.set(title + ".")
        self._log("Resumo do lote — " + "; ".join(lines))
        summary = "\n".join(lines)
        if has_failures or has_uncertain or has_cancelled:
            messagebox.showwarning(title, summary, parent=self.root)
        else:
            messagebox.showinfo(title, summary, parent=self.root)

    def _log(self, message: str) -> None:
        tag = ""
        low = message.lower()
        if low.startswith("concluído") or low.startswith("sucesso"):
            tag = "success"
        elif low.startswith("falhou") or low.startswith("erro"):
            tag = "failed"
        elif low.startswith("incerto"):
            tag = "uncertain"
        elif low.startswith("já estava aplicado"):
            tag = "already"
        elif low.startswith("cancelado") or low.startswith("não aplicável"):
            tag = "muted"
        self.txt_log.config(state=tk.NORMAL)
        if tag:
            self.txt_log.insert(tk.END, message + "\n", tag)
        else:
            self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._set_button_enabled(self.btn_scan, not busy and bool(self.manager.operations))
        self._set_button_enabled(self.btn_check, not busy and self.current_selected_op is not None)
        self._set_button_enabled(
            self.btn_rollback,
            not busy and self.current_selected_op is not None and self.current_selected_op.reversibility is ReversibilityLevel.FULL,
        )
        cancel_available = busy and self._cancel_event is not None
        self._set_button_enabled(self.btn_cancel, cancel_available)
        if busy and self._cancel_event is not None:
            self.btn_cancel.grid()
        else:
            self.btn_cancel.grid_remove()
        if busy:
            self.progress.grid()
            self.progress.start(10)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self._update_selection_summary()

    def _on_cancel(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
            self._set_button_enabled(self.btn_cancel, False)
            self.status.set("Cancelamento solicitado. A ação atual terminará antes de interromper o lote.")

    def _on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            prompt = (
                "Solicitar cancelamento e fechar após a ação atual terminar?"
                if self._cancel_event is not None
                else "A leitura de estados é somente informativa e não pode ser interrompida agora. Fechar quando terminar?"
            )
            if not messagebox.askyesno("Processo em andamento", prompt, parent=self.root):
                return
            if self._cancel_event:
                self._cancel_event.set()
            self._closing = True
            self.status.set("Aguardando o término seguro do processo…")
            return
        self.root.destroy()

    def _finish_close_if_requested(self) -> None:
        if self._closing and (not self._worker or not self._worker.is_alive()):
            self.root.destroy()


def run_gui() -> None:
    root = tk.Tk()
    PurifyApp(root)
    root.mainloop()
