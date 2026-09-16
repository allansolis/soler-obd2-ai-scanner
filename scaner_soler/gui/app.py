"""
Scaner Soler Pro — GUI principal (Tkinter + ttk).
Lanza con:  python -m scaner_soler.main gui
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .diagnostics_tab  import DiagnosticsTab
from .live_data_tab     import LiveDataTab
from .map_editor_tab    import MapEditorTab
from .optimizer_tab     import OptimizerTab
from .telemetry_tab     import TelemetryTab
from .knowledge_tab     import KnowledgeTab
from .ai_copilot_tab    import AICopilotTab
from .sandbox_tab       import SandboxTab

try:
    from ..integration.backend_client import BackendClient
except Exception:
    BackendClient = None  # type: ignore

APP_TITLE   = "Scaner Soler Pro"
WIN_SIZE    = "1200x780"
DARK_BG     = "#1e1e2e"
ACCENT      = "#89b4fa"
TAB_BG      = "#181825"
FG          = "#cdd6f4"
ENTRY_BG    = "#313244"


def apply_theme(root: tk.Tk):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=DARK_BG, foreground=FG, font=("Consolas", 10))
    style.configure("TNotebook",         background=TAB_BG, tabmargins=[2, 4, 0, 0])
    style.configure("TNotebook.Tab",     background=ENTRY_BG, foreground=FG,
                    padding=[14, 6], font=("Consolas", 10, "bold"))
    style.map("TNotebook.Tab",
              background=[("selected", DARK_BG)],
              foreground=[("selected", ACCENT)])
    style.configure("TFrame",            background=DARK_BG)
    style.configure("TLabel",            background=DARK_BG, foreground=FG)
    style.configure("TButton",           background=ENTRY_BG, foreground=FG,
                    font=("Consolas", 10), relief="flat", padding=[8, 4])
    style.map("TButton",
              background=[("active", ACCENT), ("pressed", "#1e66f5")],
              foreground=[("active", "#1e1e2e")])
    style.configure("Accent.TButton",    background=ACCENT, foreground="#1e1e2e",
                    font=("Consolas", 10, "bold"))
    style.configure("TEntry",            fieldbackground=ENTRY_BG, foreground=FG,
                    insertcolor=FG, relief="flat")
    style.configure("TCombobox",         fieldbackground=ENTRY_BG, foreground=FG,
                    selectbackground=ACCENT, selectforeground="#1e1e2e")
    style.configure("Treeview",          background=ENTRY_BG, foreground=FG,
                    fieldbackground=ENTRY_BG, rowheight=22)
    style.configure("Treeview.Heading",  background=TAB_BG, foreground=ACCENT,
                    font=("Consolas", 9, "bold"))
    style.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "#1e1e2e")])
    style.configure("TLabelframe",       background=DARK_BG, foreground=ACCENT,
                    relief="groove")
    style.configure("TLabelframe.Label", background=DARK_BG, foreground=ACCENT,
                    font=("Consolas", 10, "bold"))
    style.configure("TScrollbar",        background=ENTRY_BG, troughcolor=TAB_BG,
                    arrowcolor=FG)
    style.configure("TScale",            background=DARK_BG, troughcolor=ENTRY_BG,
                    sliderrelief="flat")
    root.configure(bg=DARK_BG)


class ScanerSolerApp(tk.Tk):

    def __init__(self, demo: bool = True):
        super().__init__()
        self.demo = demo
        self.title(APP_TITLE)
        self.geometry(WIN_SIZE)
        self.minsize(900, 600)
        apply_theme(self)

        # Backend client (None si el módulo no está disponible)
        self.backend: "BackendClient | None" = BackendClient() if BackendClient else None

        self._build_header()
        self._build_notebook()
        self._build_statusbar()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_backend_check()

    def _build_header(self):
        hdr = tk.Frame(self, bg=TAB_BG, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚡  SCANER SOLER PRO",
                 bg=TAB_BG, fg=ACCENT,
                 font=("Consolas", 14, "bold")).pack(side="left", padx=16)
        mode_txt = "MODO DEMO" if self.demo else "CONECTADO"
        mode_color = "#f9e2af" if self.demo else "#a6e3a1"
        tk.Label(hdr, text=f"● {mode_txt}",
                 bg=TAB_BG, fg=mode_color,
                 font=("Consolas", 10)).pack(side="right", padx=16)

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        tabs = [
            ("🔍  Diagnósticos",    DiagnosticsTab),
            ("📊  Datos en Vivo",   LiveDataTab),
            ("🗺️  Editor de Mapas", MapEditorTab),
            ("🚀  Optimizador",     OptimizerTab),
            ("🏁  Telemetría",      TelemetryTab),
            ("📚  Conocimiento",    KnowledgeTab),
        ]
        self.tab_objects = {}
        for label, cls in tabs:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text=label)
            obj = cls(frame, app=self)
            obj.pack(fill="both", expand=True)
            self.tab_objects[label] = obj

        # 7ª pestaña: AI Copilot
        ai_frame = ttk.Frame(self.nb)
        self.nb.add(ai_frame, text="🤖  AI Copilot")
        self.ai_copilot = AICopilotTab(ai_frame, backend_client=self.backend)
        self.ai_copilot.pack(fill="both", expand=True)
        self.tab_objects["🤖  AI Copilot"] = self.ai_copilot

        # 8ª pestaña: ECU Sandbox (MiroFish)
        sb_frame = ttk.Frame(self.nb)
        self.nb.add(sb_frame, text="🧪  ECU Sandbox")
        self.sandbox_tab = SandboxTab(sb_frame, backend_client=self.backend)
        self.sandbox_tab.pack(fill="both", expand=True)
        self.tab_objects["🧪  ECU Sandbox"] = self.sandbox_tab

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Listo.")
        self.backend_status_var = tk.StringVar(value="Backend: verificando…")

        bar_frame = tk.Frame(self, bg=TAB_BG)
        bar_frame.pack(fill="x", side="bottom")

        tk.Label(bar_frame, textvariable=self.status_var,
                 bg=TAB_BG, fg="#585b70",
                 font=("Consolas", 9), anchor="w", padx=12).pack(side="left")

        tk.Label(bar_frame, textvariable=self.backend_status_var,
                 bg=TAB_BG, fg="#585b70",
                 font=("Consolas", 9), anchor="e", padx=12).pack(side="right")

    def set_status(self, msg: str, color: str = "#585b70"):
        self.status_var.set(msg)

    def _schedule_backend_check(self):
        """Actualiza el indicador de backend en la barra de estado cada 5 s."""
        def _check():
            online = bool(self.backend and self.backend.is_online())
            if online:
                self.backend_status_var.set("Backend: online ●")
            else:
                self.backend_status_var.set("Backend: offline ○")

        def _worker():
            _check()

        threading.Thread(target=_worker, daemon=True).start()
        self.after(5000, self._schedule_backend_check)

    def _on_close(self):
        for obj in self.tab_objects.values():
            if hasattr(obj, "on_close"):
                obj.on_close()
        self.destroy()


def run_gui(demo: bool = True):
    app = ScanerSolerApp(demo=demo)
    app.mainloop()
