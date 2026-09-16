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
from .programmer_tab    import ProgrammerTab

try:
    from ..integration.backend_client import BackendClient
except Exception:
    BackendClient = None  # type: ignore

APP_TITLE   = "Scaner Soler Pro"
WIN_SIZE    = "1440x880"
APP_VERSION = "v2.0 Pro"

# ── Paleta 2026 ────────────────────────────────────────────────────────────────
DARK_BG   = "#080812"   # fondo abismal
SURFACE   = "#0e0e1c"   # surface
CARD      = "#141428"   # tarjetas
BORDER    = "#1e1e38"   # bordes sutiles
ACCENT    = "#7c3aed"   # púrpura principal
ACCENT_LT = "#a855f7"   # púrpura hover
CYAN      = "#06b6d4"   # cian datos
GREEN     = "#10b981"   # verde OK
RED       = "#f43f5e"   # rojo crítico
YELLOW    = "#f59e0b"   # amarillo warning
FG        = "#e2e8f0"   # texto principal
SUBTEXT   = "#64748b"   # texto secundario
ENTRY_BG  = "#1a1a32"   # campos de entrada
TAB_BG    = SURFACE


def apply_theme(root: tk.Tk):
    style = ttk.Style(root)
    style.theme_use("clam")

    # Base
    style.configure(".",
        background=DARK_BG, foreground=FG,
        font=("Consolas", 10),
        borderwidth=0, relief="flat")

    # Notebook tabs — línea inferior como indicador activo
    style.configure("TNotebook",
        background=SURFACE, tabmargins=[0, 0, 0, 0], borderwidth=0)
    style.configure("TNotebook.Tab",
        background=SURFACE, foreground=SUBTEXT,
        padding=[16, 8], font=("Consolas", 9, "bold"),
        borderwidth=0)
    style.map("TNotebook.Tab",
        background=[("selected", DARK_BG), ("active", CARD)],
        foreground=[("selected", ACCENT_LT), ("active", FG)])

    # Frames
    style.configure("TFrame",      background=DARK_BG)
    style.configure("Card.TFrame", background=CARD, relief="flat")

    # Labels
    style.configure("TLabel",       background=DARK_BG, foreground=FG)
    style.configure("Card.TLabel",  background=CARD,    foreground=FG)
    style.configure("Sub.TLabel",   background=DARK_BG, foreground=SUBTEXT,
                    font=("Consolas", 8))

    # Buttons
    style.configure("TButton",
        background=BORDER, foreground=FG,
        font=("Consolas", 9, "bold"), relief="flat",
        padding=[10, 5], borderwidth=0)
    style.map("TButton",
        background=[("active", CARD), ("pressed", ACCENT)],
        foreground=[("active", FG)])
    style.configure("Accent.TButton",
        background=ACCENT, foreground="#ffffff",
        font=("Consolas", 9, "bold"), padding=[10, 5])
    style.map("Accent.TButton",
        background=[("active", ACCENT_LT), ("pressed", "#6d28d9")])
    style.configure("Danger.TButton",
        background="#7f1d1d", foreground="#fca5a5",
        font=("Consolas", 9, "bold"), padding=[10, 5])
    style.map("Danger.TButton",
        background=[("active", "#991b1b")])

    # Entry
    style.configure("TEntry",
        fieldbackground=ENTRY_BG, foreground=FG,
        insertcolor=ACCENT_LT, relief="flat",
        borderwidth=1, padding=[6, 4])

    # Combobox
    style.configure("TCombobox",
        fieldbackground=ENTRY_BG, foreground=FG,
        selectbackground=ACCENT, selectforeground="#fff")

    # Treeview — filas altas para legibilidad
    style.configure("Treeview",
        background=CARD, foreground=FG,
        fieldbackground=CARD, rowheight=28,
        font=("Consolas", 9), borderwidth=0)
    style.configure("Treeview.Heading",
        background=SURFACE, foreground=SUBTEXT,
        font=("Consolas", 8, "bold"), relief="flat",
        padding=[8, 6])
    style.map("Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")])

    # LabelFrame como separador sutil
    style.configure("TLabelframe",
        background=DARK_BG, foreground=BORDER,
        relief="flat", borderwidth=1)
    style.configure("TLabelframe.Label",
        background=DARK_BG, foreground=SUBTEXT,
        font=("Consolas", 8, "bold"))

    # Scrollbar mínima
    style.configure("TScrollbar",
        background=BORDER, troughcolor=DARK_BG,
        arrowcolor=BORDER, relief="flat", width=6)
    style.map("TScrollbar",
        background=[("active", ACCENT)])

    style.configure("TScale",
        background=DARK_BG, troughcolor=ENTRY_BG,
        sliderrelief="flat")

    style.configure("TProgressbar",
        troughcolor=ENTRY_BG, background=ACCENT,
        thickness=4)

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
        hdr = tk.Frame(self, bg=SURFACE, pady=0)
        hdr.pack(fill="x")

        # Línea de acento superior (3px púrpura)
        tk.Frame(hdr, bg=ACCENT, height=3).pack(fill="x", side="top")

        inner = tk.Frame(hdr, bg=SURFACE)
        inner.pack(fill="x", padx=16, pady=8)

        # Logo — "SCANER SOLER" blanco + "PRO" en púrpura
        logo_frame = tk.Frame(inner, bg=SURFACE)
        logo_frame.pack(side="left")
        tk.Label(logo_frame, text="SCANER SOLER ",
                 bg=SURFACE, fg=FG,
                 font=("Consolas", 13, "bold")).pack(side="left")
        tk.Label(logo_frame, text="PRO",
                 bg=SURFACE, fg=ACCENT_LT,
                 font=("Consolas", 13, "bold")).pack(side="left")
        tk.Label(inner, text=f" · {APP_VERSION}",
                 bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 9)).pack(side="left")

        # Indicadores de estado lado derecho
        right = tk.Frame(inner, bg=SURFACE)
        right.pack(side="right")

        mode_txt   = "MODO DEMO" if self.demo else "EN VIVO"
        mode_color = YELLOW if self.demo else GREEN
        mode_dot   = "●"
        tk.Label(right, text=f"{mode_dot} {mode_txt}",
                 bg=SURFACE, fg=mode_color,
                 font=("Consolas", 9, "bold")).pack(side="right", padx=(16, 0))

        # Separador debajo del header
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

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

        # 9ª pestaña: Programación ECU (borrar DTCs, resets, flash)
        prog_frame = ttk.Frame(self.nb)
        self.nb.add(prog_frame, text="⚡  Programación ECU")
        self.programmer_tab = ProgrammerTab(prog_frame, app=self)
        self.programmer_tab.pack(fill="both", expand=True)
        self.tab_objects["⚡  Programación ECU"] = self.programmer_tab

    def _build_statusbar(self):
        from .widgets import StatusBar
        self.statusbar = StatusBar(self)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.update_status(version=APP_VERSION)
        # Mantener status_var para compatibilidad con set_status()
        self.status_var = tk.StringVar(value="Listo.")
        # backend_status_var conservado para compatibilidad
        self.backend_status_var = tk.StringVar(value="Backend: verificando…")

    def set_status(self, msg: str, color: str = "#585b70"):
        self.status_var.set(msg)

    def _schedule_backend_check(self):
        """Actualiza el indicador de backend en la barra de estado cada 5 s."""
        def _check():
            online = bool(
                self.backend and
                getattr(self.backend, 'is_online', lambda: False)()
            )
            if online:
                self.backend_status_var.set("Backend: online ●")
                # Actualizar StatusBar moderno desde el hilo principal via after
                self.after(0, lambda: self.statusbar.update_status(
                    connected=True,
                    status="Online ●",
                    protocol="OBD-II / UDS",
                ))
            else:
                self.backend_status_var.set("Backend: offline ○")
                self.after(0, lambda: self.statusbar.update_status(
                    connected=False,
                    status="Desconectado",
                ))

        threading.Thread(target=_check, daemon=True).start()
        self.after(5000, self._schedule_backend_check)

    def _on_close(self):
        for obj in self.tab_objects.values():
            if hasattr(obj, "on_close"):
                obj.on_close()
        self.destroy()


def run_gui(demo: bool = True):
    app = ScanerSolerApp(demo=demo)
    app.mainloop()
