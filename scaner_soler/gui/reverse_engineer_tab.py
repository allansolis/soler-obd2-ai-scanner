"""
reverse_engineer_tab.py — Pestaña GUI para Ingeniería Inversa de ECU.
Estilo 2026: paleta abismal + tarjetas KPI + barra de progreso animada.
4 sub-tabs: Perfil ECU | CAN Scanner | Mapa UDS | Control Map
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional

try:
    from ..comm.reverse_engineer import (
        ReverseEngineerSession, RESessionResult,
        PatternAnalyzer, run_demo,
        CANBusScanner, CANScanResult,
        UDSServiceMap, UDSServiceResult,
        SignalChangeMonitor,
        ECUControlMap,
    )
    _RE_AVAILABLE = True
    _RE_IMPORT_ERROR = ""
except ImportError as e:
    _RE_AVAILABLE = False
    _RE_IMPORT_ERROR = str(e)
    # Stubs for type hints only
    RESessionResult = None
    CANScanResult   = None
    UDSServiceResult = None

# ── Paleta (igual que app.py) ──────────────────────────────────────────────────
DARK_BG   = "#080812"
SURFACE   = "#0e0e1c"
CARD      = "#141428"
BORDER    = "#1e1e38"
ACCENT    = "#7c3aed"
ACCENT_LT = "#a855f7"
CYAN      = "#06b6d4"
GREEN     = "#10b981"
RED       = "#f43f5e"
YELLOW    = "#f59e0b"
FG        = "#e2e8f0"
SUBTEXT   = "#64748b"
ENTRY_BG  = "#1a1a32"
ORANGE    = "#f97316"

# ── Mini widgets ──────────────────────────────────────────────────────────────

class _StatCard(tk.Canvas):
    """Tarjeta KPI reutilizable."""
    W, H = 140, 80

    def __init__(self, parent, label: str, value: str = "—",
                 color: str = CYAN, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=CARD, highlightthickness=0, **kw)
        self._color = color
        self._label = label
        self._value = value
        self._draw()

    def _draw(self):
        self.delete("all")
        # barra superior
        self.create_rectangle(0, 0, self.W, 3, fill=self._color, outline="")
        # fondo card
        self.create_rectangle(0, 3, self.W, self.H, fill=CARD, outline="")
        # label
        self.create_text(12, 20, text=self._label.upper(), anchor="w",
                         fill=SUBTEXT, font=("Consolas", 7, "bold"))
        # valor
        self.create_text(12, 52, text=self._value, anchor="w",
                         fill=self._color, font=("Consolas", 20, "bold"))

    def update_value(self, value: str, color: Optional[str] = None):
        self._value = value
        if color:
            self._color = color
        self._draw()


class _ActionBtn(tk.Canvas):
    """Botón redondeado con hover."""
    def __init__(self, parent, text: str, command=None,
                 color: str = ACCENT, w: int = 160, h: int = 36, **kw):
        super().__init__(parent, width=w, height=h,
                         bg=SURFACE, highlightthickness=0, cursor="hand2", **kw)
        self._bw, self._bh = w, h
        self._color = color
        self._hover_color = ACCENT_LT if color == ACCENT else color
        self._text = text
        self._cmd  = command
        self._draw(color)
        self.bind("<Enter>",  lambda e: self._draw(self._hover_color))
        self.bind("<Leave>",  lambda e: self._draw(self._color))
        self.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)

    def _draw(self, bg: str):
        self.delete("all")
        r = 6
        x0, y0, x1, y1 = 1, 1, self._bw - 1, self._bh - 1
        self.create_arc(x0, y0, x0 + 2*r, y0 + 2*r, start=90,  extent=90,  fill=bg, outline="")
        self.create_arc(x1 - 2*r, y0, x1, y0 + 2*r, start=0,   extent=90,  fill=bg, outline="")
        self.create_arc(x0, y1 - 2*r, x0 + 2*r, y1, start=180, extent=90,  fill=bg, outline="")
        self.create_arc(x1 - 2*r, y1 - 2*r, x1, y1, start=270, extent=90,  fill=bg, outline="")
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=bg, outline="")
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=bg, outline="")
        self.create_text(self._bw // 2, self._bh // 2,
                         text=self._text, fill="#ffffff",
                         font=("Consolas", 9, "bold"))

    def configure_state(self, enabled: bool):
        self._cmd = self._cmd if enabled else None
        self.configure(cursor="hand2" if enabled else "arrow")


class _ProgressBar(tk.Canvas):
    """Barra de progreso animada con shimmer."""
    def __init__(self, parent, **kw):
        super().__init__(parent, height=6, bg=SURFACE,
                         highlightthickness=0, **kw)
        self._running   = False
        self._progress  = 0.0
        self._shimmer_x = 0

    def set_progress(self, pct: float):
        self._progress = max(0.0, min(1.0, pct))
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        self.create_rectangle(0, 0, w, 6, fill=ENTRY_BG, outline="")
        if self._progress > 0:
            fill_w = int(w * self._progress)
            self.create_rectangle(0, 0, fill_w, 6, fill=ACCENT, outline="")
            # shimmer
            sx = self._shimmer_x % (fill_w + 40) - 20
            self.create_rectangle(sx, 0, sx + 20, 6,
                                   fill=ACCENT_LT, outline="")

    def start(self):
        self._running = True
        self._animate()

    def stop(self):
        self._running = False

    def _animate(self):
        if not self._running:
            return
        self._shimmer_x += 8
        self._redraw()
        self.after(30, self._animate)


# ── Notebook style helper ─────────────────────────────────────────────────────

def _apply_notebook_style():
    """Aplica estilo oscuro al ttk.Notebook."""
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Dark.TNotebook",
                    background=DARK_BG, borderwidth=0,
                    tabmargins=[0, 0, 0, 0])
    style.configure("Dark.TNotebook.Tab",
                    background=SURFACE, foreground=SUBTEXT,
                    font=("Consolas", 9, "bold"),
                    padding=[12, 6], borderwidth=0)
    style.map("Dark.TNotebook.Tab",
              background=[("selected", CARD), ("active", BORDER)],
              foreground=[("selected", ACCENT_LT), ("active", FG)])
    style.configure("Dark.TFrame", background=DARK_BG)


# ── ReverseEngineerTab ────────────────────────────────────────────────────────

class ReverseEngineerTab(tk.Frame):
    """Pestaña completa de Ingeniería Inversa de ECU — 4 sub-tabs."""

    def __init__(self, parent, app=None, **kw):
        super().__init__(parent, bg=DARK_BG, **kw)
        self._app    = app
        # ── Estado sub-tab 1: Perfil ECU ──────────────────────────────────
        self._result: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # ── Estado sub-tab 2: CAN Scanner ────────────────────────────────
        self._can_thread: Optional[threading.Thread] = None
        self._can_running = False
        self._can_results: list = []
        # ── Estado sub-tab 3: Mapa UDS ───────────────────────────────────
        self._uds_thread: Optional[threading.Thread] = None
        self._uds_running = False
        self._uds_results: list = []
        # ── Estado sub-tab 4: Control Map ────────────────────────────────
        self._ctrl_thread: Optional[threading.Thread] = None
        self._ctrl_running = False
        self._ctrl_map: Optional[dict] = None

        _apply_notebook_style()
        self._build()

    # ── Layout principal ──────────────────────────────────────────────────────

    def _build(self):
        # Header strip
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, height=3).pack(fill="x")
        inner = tk.Frame(hdr, bg=SURFACE)
        inner.pack(fill="x", padx=16, pady=6)
        tk.Label(inner, text="INGENIERÍA INVERSA  ",
                 bg=SURFACE, fg=FG, font=("Consolas", 12, "bold")).pack(side="left")
        tk.Label(inner, text="ECU",
                 bg=SURFACE, fg=ACCENT_LT, font=("Consolas", 12, "bold")).pack(side="left")
        tk.Label(inner, text=" · Detección automática de protocolo + fuzzing de PIDs/DIDs",
                 bg=SURFACE, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Notebook interno con 4 sub-tabs
        self._nb = ttk.Notebook(self, style="Dark.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=0, pady=0)

        # Frames de cada sub-tab
        self._tab_profile = tk.Frame(self._nb, bg=DARK_BG)
        self._tab_can     = tk.Frame(self._nb, bg=DARK_BG)
        self._tab_uds     = tk.Frame(self._nb, bg=DARK_BG)
        self._tab_ctrl    = tk.Frame(self._nb, bg=DARK_BG)

        self._nb.add(self._tab_profile, text="🔬 Perfil ECU")
        self._nb.add(self._tab_can,     text="📡 CAN Scanner")
        self._nb.add(self._tab_uds,     text="🗺️ Mapa UDS")
        self._nb.add(self._tab_ctrl,    text="💻 Control Map")

        self._build_profile_tab()
        self._build_can_tab()
        self._build_uds_tab()
        self._build_ctrl_tab()

    # ═══════════════════════════════════════════════════════════════════════════
    # SUB-TAB 1 — Perfil ECU
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_profile_tab(self):
        p = self._tab_profile

        # Controls
        ctrl = tk.Frame(p, bg=SURFACE, pady=8)
        ctrl.pack(fill="x", padx=12)

        tk.Label(ctrl, text="MODO FUZZ:", bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 8, "bold")).pack(side="left", padx=(0, 6))
        self._fuzz_mode = tk.StringVar(value="smart")
        for val, lbl in [("smart", "Auto"), ("obd", "OBD Only"),
                          ("uds", "UDS Only"), ("both", "OBD + UDS")]:
            tk.Radiobutton(
                ctrl, text=lbl, variable=self._fuzz_mode, value=val,
                bg=SURFACE, fg=FG, selectcolor=ACCENT,
                activebackground=SURFACE, activeforeground=FG,
                font=("Consolas", 9), cursor="hand2"
            ).pack(side="left", padx=4)

        tk.Frame(ctrl, bg=BORDER, width=1, height=24).pack(side="left", padx=12)

        self._only_profile = tk.BooleanVar(value=False)
        tk.Checkbutton(
            ctrl, text="Solo perfilar (sin fuzzing)", variable=self._only_profile,
            bg=SURFACE, fg=FG, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=4)

        tk.Frame(ctrl, bg=BORDER, width=1, height=24).pack(side="left", padx=12)

        self._demo_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            ctrl, text="Modo DEMO (sin hardware)", variable=self._demo_var,
            bg=SURFACE, fg=YELLOW, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=4)

        # Buttons
        btn_row = tk.Frame(p, bg=DARK_BG, pady=6)
        btn_row.pack(fill="x", padx=12)

        self._btn_run = _ActionBtn(btn_row, "▶  INICIAR SESIÓN RE",
                                   command=self._start_session,
                                   color=ACCENT, w=200)
        self._btn_run.pack(side="left", padx=(0, 8))

        self._btn_stop = _ActionBtn(btn_row, "■  DETENER",
                                    command=self._stop_session,
                                    color=RED, w=120)
        self._btn_stop.pack(side="left", padx=(0, 8))

        self._btn_export = _ActionBtn(btn_row, "⬇  EXPORTAR JSON",
                                      command=self._export,
                                      color=CYAN, w=160)
        self._btn_export.pack(side="left", padx=(0, 8))

        # Progress
        prog_row = tk.Frame(p, bg=DARK_BG, pady=2)
        prog_row.pack(fill="x", padx=12)
        self._prog_bar = _ProgressBar(prog_row)
        self._prog_bar.pack(fill="x")
        self._prog_label = tk.Label(prog_row, text="Esperando inicio…",
                                    bg=DARK_BG, fg=SUBTEXT,
                                    font=("Consolas", 8))
        self._prog_label.pack(anchor="w", pady=2)

        # KPI cards
        kpi_row = tk.Frame(p, bg=DARK_BG, pady=6)
        kpi_row.pack(fill="x", padx=12)
        self._card_proto    = _StatCard(kpi_row, "Protocolo",   "—",  ACCENT_LT)
        self._card_vin      = _StatCard(kpi_row, "VIN",         "—",  CYAN)
        self._card_pids     = _StatCard(kpi_row, "PIDs/DIDs OK","0",  GREEN)
        self._card_ecus     = _StatCard(kpi_row, "ECUs",        "0",  YELLOW)
        self._card_entropy  = _StatCard(kpi_row, "Entropía avg","— b", ORANGE)
        self._card_duration = _StatCard(kpi_row, "Duración",    "—s", SUBTEXT)
        for card in (self._card_proto, self._card_vin, self._card_pids,
                     self._card_ecus, self._card_entropy, self._card_duration):
            card.pack(side="left", padx=4)

        # Main content split
        split = tk.Frame(p, bg=DARK_BG)
        split.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Left: fuzz catalog treeview
        left = tk.Frame(split, bg=DARK_BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="CATÁLOGO DE PIDs/DIDs RESPONDIDOS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w")

        tree_frame = tk.Frame(left, bg=CARD)
        tree_frame.pack(fill="both", expand=True)
        cols = ("pid_did", "service", "response", "bytes", "entropy")
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                  show="headings", selectmode="browse")
        for col, lbl, w in [
            ("pid_did",  "PID/DID",    80),
            ("service",  "Servicio",   70),
            ("response", "Respuesta", 200),
            ("bytes",    "Bytes",      60),
            ("entropy",  "Entropía",   70),
        ]:
            self.tree.heading(col, text=lbl)
            self.tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                             command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right: detail panel
        right = tk.Frame(split, bg=DARK_BG, width=320)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)
        tk.Label(right, text="DETALLE / ANÁLISIS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w")

        self._det_border = tk.Frame(right, bg=BORDER, padx=3, pady=3)
        self._det_border.pack(fill="both", expand=True)
        self._detail = tk.Text(self._det_border, bg=CARD, fg=FG,
                                font=("Consolas", 9), wrap="word",
                                relief="flat", state="disabled")
        sb2 = ttk.Scrollbar(self._det_border, orient="vertical",
                              command=self._detail.yview)
        self._detail.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self._detail.pack(fill="both", expand=True)
        self._detail.tag_configure("heading",  foreground=ACCENT_LT,
                                    font=("Consolas", 9, "bold"))
        self._detail.tag_configure("key",      foreground=CYAN)
        self._detail.tag_configure("value",    foreground=FG)
        self._detail.tag_configure("positive", foreground=GREEN)
        self._detail.tag_configure("negative", foreground=RED)
        self._detail.tag_configure("warn",     foreground=YELLOW)
        self._detail.tag_configure("subtext",  foreground=SUBTEXT,
                                    font=("Consolas", 8))

        self._show_detail_idle()

    # ═══════════════════════════════════════════════════════════════════════════
    # SUB-TAB 2 — CAN Scanner
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_can_tab(self):
        p = self._tab_can

        # Header
        hdr = tk.Frame(p, bg=DARK_BG, pady=8)
        hdr.pack(fill="x", padx=12)
        tk.Label(hdr, text="CAN Bus Scanner — Detección de IDs activos",
                 bg=DARK_BG, fg=CYAN, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", padx=12)

        # Controls row
        ctrl = tk.Frame(p, bg=SURFACE, pady=8)
        ctrl.pack(fill="x", padx=12, pady=(4, 0))

        tk.Label(ctrl, text="Duración (s):", bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 9)).pack(side="left", padx=(0, 4))
        self._can_dur_var = tk.IntVar(value=10)
        self._can_dur_spin = tk.Spinbox(
            ctrl, values=(5, 10, 30, 60), textvariable=self._can_dur_var,
            width=5, bg=ENTRY_BG, fg=FG, insertbackground=FG,
            buttonbackground=BORDER, relief="flat", font=("Consolas", 9)
        )
        self._can_dur_spin.pack(side="left", padx=(0, 12))

        self._can_btn_start = _ActionBtn(ctrl, "▶ Iniciar Scan",
                                         command=self._can_start,
                                         color=ACCENT, w=140, h=30)
        self._can_btn_start.pack(side="left", padx=(0, 6))

        self._can_btn_stop = _ActionBtn(ctrl, "⏹ Detener",
                                        command=self._can_stop,
                                        color=RED, w=110, h=30)
        self._can_btn_stop.pack(side="left", padx=(0, 12))

        self._can_status_var = tk.StringVar(value="● Listo")
        tk.Label(ctrl, textvariable=self._can_status_var,
                 bg=SURFACE, fg=GREEN, font=("Consolas", 9, "bold")).pack(side="left")

        # Progress bar CAN
        can_prog_row = tk.Frame(p, bg=DARK_BG)
        can_prog_row.pack(fill="x", padx=12, pady=(2, 4))
        self._can_prog = _ProgressBar(can_prog_row)
        self._can_prog.pack(fill="x")

        # Treeview CAN
        tree_frame = tk.Frame(p, bg=CARD)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        can_cols = ("can_id", "dlc", "frames", "pattern", "entropy", "sample")
        self._can_tree = ttk.Treeview(tree_frame, columns=can_cols,
                                       show="headings", selectmode="browse")
        for col, lbl, w in [
            ("can_id",  "ID (hex)",   80),
            ("dlc",     "DLC",        50),
            ("frames",  "Frames",     70),
            ("pattern", "Patrón",     90),
            ("entropy", "Entropía",   80),
            ("sample",  "Muestra",   200),
        ]:
            self._can_tree.heading(col, text=lbl)
            self._can_tree.column(col, width=w, anchor="w")

        can_vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                                 command=self._can_tree.yview)
        self._can_tree.configure(yscrollcommand=can_vsb.set)
        can_vsb.pack(side="right", fill="y")
        self._can_tree.pack(fill="both", expand=True)
        self._can_tree.bind("<<TreeviewSelect>>", self._on_can_select)

        self._can_tree.tag_configure("dynamic",
                                      background="#061a1a", foreground=CYAN)
        self._can_tree.tag_configure("static",
                                      background=SURFACE, foreground=SUBTEXT)
        self._can_tree.tag_configure("counter",
                                      background="#061a0a", foreground=GREEN)

        # Detail panel CAN
        det_lbl = tk.Label(p, text="FRAMES DE MUESTRA (ID seleccionado)",
                           bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold"))
        det_lbl.pack(anchor="w", padx=12)
        can_det_frame = tk.Frame(p, bg=BORDER, height=90)
        can_det_frame.pack(fill="x", padx=12, pady=(0, 4))
        can_det_frame.pack_propagate(False)
        self._can_detail = tk.Text(can_det_frame, bg=CARD, fg=FG,
                                    font=("Consolas", 9), wrap="none",
                                    relief="flat", state="disabled", height=5)
        self._can_detail.pack(fill="both", expand=True, padx=2, pady=2)

        # Footer row
        can_footer = tk.Frame(p, bg=DARK_BG, pady=4)
        can_footer.pack(fill="x", padx=12)
        _ActionBtn(can_footer, "⬇ Exportar CSV",
                   command=self._can_export_csv,
                   color=CYAN, w=150, h=30).pack(side="right")

    def _can_start(self):
        if self._can_running:
            return
        if not _RE_AVAILABLE:
            self._can_status_var.set(f"● Módulo en actualización ({_RE_IMPORT_ERROR[:40]})")
            return
        self._can_running = True
        self._can_status_var.set("● Escaneando...")
        self._can_prog.set_progress(0.05)
        self._can_prog.start()
        duration = self._can_dur_var.get()

        def _run():
            try:
                def _demo_send(cmd):
                    return "41 00 BE 3F A8 13"
                send_fn = _demo_send
                if self._app is not None:
                    vc = getattr(self._app, "vehicle_conn", None)
                    if vc is not None:
                        proto = getattr(vc, "_proto", None)
                        if proto is not None and hasattr(proto, "send_raw"):
                            send_fn = proto.send_raw

                scanner = CANBusScanner(send_fn)
                results = scanner.scan_traffic(
                    duration,
                    callback=lambda msg, pct: self.after(
                        0, lambda m=msg, p=pct: self._can_progress(m, p)
                    )
                )
                self.after(0, lambda r=results: self._can_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._can_error(str(e)))

        self._can_thread = threading.Thread(target=_run, daemon=True)
        self._can_thread.start()

    def _can_stop(self):
        self._can_running = False
        self._can_prog.stop()
        self._can_status_var.set("● Detenido")

    def _can_progress(self, msg: str, pct: float):
        self._can_prog.set_progress(pct)
        self._can_status_var.set(f"● {msg}")

    def _can_done(self, results):
        self._can_running = False
        self._can_results = results if results else []
        self._can_prog.stop()
        self._can_prog.set_progress(1.0)
        self._can_status_var.set(f"● Completado — {len(self._can_results)} IDs encontrados")
        self._can_populate_tree(self._can_results)

    def _can_error(self, msg: str):
        self._can_running = False
        self._can_prog.stop()
        self._can_status_var.set(f"● Error: {msg[:60]}")

    def _can_populate_tree(self, results):
        for item in self._can_tree.get_children():
            self._can_tree.delete(item)
        for entry in results:
            can_id  = entry.get("id", "—")
            dlc     = str(entry.get("dlc", "—"))
            frames  = str(entry.get("frames", 0))
            pattern = entry.get("pattern", "unknown")
            entropy = f"{entry.get('entropy', 0.0):.2f}"
            sample  = entry.get("sample", "")
            iid = self._can_tree.insert("", "end",
                                         values=(can_id, dlc, frames, pattern,
                                                 entropy, sample))
            if pattern == "dynamic":
                self._can_tree.item(iid, tags=("dynamic",))
            elif pattern == "counter":
                self._can_tree.item(iid, tags=("counter",))
            else:
                self._can_tree.item(iid, tags=("static",))

    def _on_can_select(self, _event=None):
        sel = self._can_tree.selection()
        if not sel:
            return
        vals = self._can_tree.item(sel[0], "values")
        can_id = vals[0] if vals else "—"
        # Buscar frames de muestra en los resultados
        entry = next((e for e in self._can_results
                      if str(e.get("id", "")) == str(can_id)), None)
        self._can_detail.configure(state="normal")
        self._can_detail.delete("1.0", "end")
        if entry:
            frames_list = entry.get("samples", [entry.get("sample", "")])
            if isinstance(frames_list, str):
                frames_list = [frames_list]
            for i, fr in enumerate(frames_list[:5]):
                self._can_detail.insert("end", f"  [{i+1}] {fr}\n")
        else:
            self._can_detail.insert("end", "  (sin datos de muestra)\n")
        self._can_detail.configure(state="disabled")

    def _can_export_csv(self):
        if not self._can_results:
            messagebox.showinfo("Sin datos", "Ejecuta un scan primero.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            title="Guardar CAN Scan CSV",
        )
        if not path:
            return
        lines = ["ID,DLC,Frames,Patron,Entropia,Muestra"]
        for e in self._can_results:
            lines.append(
                f"{e.get('id','')},{e.get('dlc','')},{e.get('frames',0)},"
                f"{e.get('pattern','')},{e.get('entropy',0.0):.2f},"
                f"\"{e.get('sample','')}\"")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Exportado", f"CSV guardado en:\n{path}")

    # ═══════════════════════════════════════════════════════════════════════════
    # SUB-TAB 3 — Mapa UDS
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_uds_tab(self):
        p = self._tab_uds

        # Header
        hdr = tk.Frame(p, bg=DARK_BG, pady=8)
        hdr.pack(fill="x", padx=12)
        tk.Label(hdr, text="UDS Service Discovery — ISO 14229-1",
                 bg=DARK_BG, fg=CYAN, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", padx=12)

        # Controls
        ctrl = tk.Frame(p, bg=SURFACE, pady=8)
        ctrl.pack(fill="x", padx=12, pady=(4, 0))

        self._uds_skip_danger = tk.BooleanVar(value=True)
        tk.Checkbutton(
            ctrl, text="Omitir servicios peligrosos (recomendado)",
            variable=self._uds_skip_danger,
            bg=SURFACE, fg=YELLOW, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=(0, 12))

        self._uds_scan_dids = tk.BooleanVar(value=False)
        tk.Checkbutton(
            ctrl, text="Escanear DIDs F100-F1FF",
            variable=self._uds_scan_dids,
            bg=SURFACE, fg=FG, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=(0, 16))

        self._uds_btn_svc = _ActionBtn(ctrl, "▶ Escanear Servicios",
                                       command=self._uds_scan_services,
                                       color=ACCENT, w=180, h=30)
        self._uds_btn_svc.pack(side="left", padx=(0, 8))

        self._uds_btn_did = _ActionBtn(ctrl, "▶ Escanear DIDs",
                                       command=self._uds_scan_dids_fn,
                                       color=SURFACE, w=150, h=30)
        self._uds_btn_did.pack(side="left", padx=(0, 8))

        self._uds_status_var = tk.StringVar(value="● Listo")
        tk.Label(ctrl, textvariable=self._uds_status_var,
                 bg=SURFACE, fg=GREEN, font=("Consolas", 9, "bold")).pack(side="left")

        # Progress UDS
        uds_prog_row = tk.Frame(p, bg=DARK_BG)
        uds_prog_row.pack(fill="x", padx=12, pady=(2, 4))
        self._uds_prog = _ProgressBar(uds_prog_row)
        self._uds_prog.pack(fill="x")

        # Treeview servicios UDS
        tk.Label(p, text="SERVICIOS UDS DETECTADOS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w", padx=12)

        svc_frame = tk.Frame(p, bg=CARD)
        svc_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        uds_cols = ("svc_id", "servicio", "estado", "nrc", "riesgo")
        self._uds_tree = ttk.Treeview(svc_frame, columns=uds_cols,
                                       show="headings", selectmode="browse",
                                       height=8)
        for col, lbl, w in [
            ("svc_id",   "ID (hex)",    70),
            ("servicio", "Servicio",   160),
            ("estado",   "Estado",      90),
            ("nrc",      "NRC",         70),
            ("riesgo",   "Riesgo",      80),
        ]:
            self._uds_tree.heading(col, text=lbl)
            self._uds_tree.column(col, width=w, anchor="w")

        uds_vsb = ttk.Scrollbar(svc_frame, orient="vertical",
                                 command=self._uds_tree.yview)
        self._uds_tree.configure(yscrollcommand=uds_vsb.set)
        uds_vsb.pack(side="right", fill="y")
        self._uds_tree.pack(fill="both", expand=True)

        self._uds_tree.tag_configure("safe",
                                      background="#061a0a", foreground=GREEN)
        self._uds_tree.tag_configure("caution",
                                      background="#1a1400", foreground=YELLOW)
        self._uds_tree.tag_configure("danger",
                                      background="#1a0608", foreground=RED)
        self._uds_tree.tag_configure("unsupported",
                                      background=SURFACE, foreground=SUBTEXT)

        # Panel DIDs legibles
        tk.Label(p, text="DIDs LEGIBLES",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w", padx=12)

        did_frame = tk.Frame(p, bg=CARD)
        did_frame.pack(fill="x", padx=12, pady=(0, 4))

        did_cols = ("did_id", "descripcion", "datos")
        self._did_tree = ttk.Treeview(did_frame, columns=did_cols,
                                       show="headings", selectmode="browse",
                                       height=4)
        for col, lbl, w in [
            ("did_id",      "ID",          70),
            ("descripcion", "Descripción", 200),
            ("datos",       "Datos (hex)", 200),
        ]:
            self._did_tree.heading(col, text=lbl)
            self._did_tree.column(col, width=w, anchor="w")
        self._did_tree.pack(fill="x", expand=False)

        # Footer
        uds_footer = tk.Frame(p, bg=DARK_BG, pady=4)
        uds_footer.pack(fill="x", padx=12)
        _ActionBtn(uds_footer, "⬇ Exportar Mapa JSON",
                   command=self._uds_export_json,
                   color=CYAN, w=170, h=30).pack(side="right")

    def _uds_scan_services(self):
        if self._uds_running:
            return
        if not _RE_AVAILABLE:
            self._uds_status_var.set(f"● Módulo en actualización")
            return
        self._uds_running = True
        self._uds_status_var.set("● Escaneando servicios...")
        self._uds_prog.set_progress(0.05)
        self._uds_prog.start()
        skip_danger = self._uds_skip_danger.get()

        def _run():
            try:
                send_fn = self._get_send_fn_or_demo()
                uds_map = UDSServiceMap(send_fn, skip_dangerous=skip_danger)
                results = uds_map.scan_services(
                    callback=lambda msg, pct: self.after(
                        0, lambda m=msg, p=pct: self._uds_progress(m, p)
                    )
                )
                self.after(0, lambda r=results: self._uds_svc_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._uds_error(str(e)))

        self._uds_thread = threading.Thread(target=_run, daemon=True)
        self._uds_thread.start()

    def _uds_scan_dids_fn(self):
        if self._uds_running:
            return
        if not _RE_AVAILABLE:
            self._uds_status_var.set("● Módulo en actualización")
            return
        self._uds_running = True
        self._uds_status_var.set("● Escaneando DIDs F100-F1FF...")
        self._uds_prog.set_progress(0.05)
        self._uds_prog.start()

        def _run():
            try:
                send_fn = self._get_send_fn_or_demo()
                uds_map = UDSServiceMap(send_fn)
                did_results = uds_map.scan_dids(
                    start=0xF100, end=0xF1FF,
                    callback=lambda msg, pct: self.after(
                        0, lambda m=msg, p=pct: self._uds_progress(m, p)
                    )
                )
                self.after(0, lambda r=did_results: self._uds_did_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._uds_error(str(e)))

        self._uds_thread = threading.Thread(target=_run, daemon=True)
        self._uds_thread.start()

    def _uds_progress(self, msg: str, pct: float):
        self._uds_prog.set_progress(pct)
        self._uds_status_var.set(f"● {msg}")

    def _uds_svc_done(self, results):
        self._uds_running = False
        self._uds_results = results if results else []
        self._uds_prog.stop()
        self._uds_prog.set_progress(1.0)
        supported = sum(1 for r in self._uds_results if r.get("supported"))
        self._uds_status_var.set(f"● Completado — {supported} servicios soportados")
        self._uds_populate_tree(self._uds_results)

    def _uds_did_done(self, results):
        self._uds_running = False
        self._uds_prog.stop()
        self._uds_prog.set_progress(1.0)
        readable = len(results) if results else 0
        self._uds_status_var.set(f"● DIDs: {readable} legibles")
        self._uds_populate_dids(results or [])

    def _uds_error(self, msg: str):
        self._uds_running = False
        self._uds_prog.stop()
        self._uds_status_var.set(f"● Error: {msg[:60]}")

    def _uds_populate_tree(self, results):
        for item in self._uds_tree.get_children():
            self._uds_tree.delete(item)
        for entry in results:
            svc_id    = entry.get("id", "—")
            servicio  = entry.get("name", "—")
            estado    = "Soportado" if entry.get("supported") else "No soportado"
            nrc       = entry.get("nrc", "—")
            riesgo    = entry.get("risk", "unknown")
            iid = self._uds_tree.insert("", "end",
                                         values=(svc_id, servicio, estado,
                                                 nrc, riesgo))
            if not entry.get("supported"):
                self._uds_tree.item(iid, tags=("unsupported",))
            elif riesgo == "safe":
                self._uds_tree.item(iid, tags=("safe",))
            elif riesgo == "caution":
                self._uds_tree.item(iid, tags=("caution",))
            else:
                self._uds_tree.item(iid, tags=("danger",))

    def _uds_populate_dids(self, results):
        for item in self._did_tree.get_children():
            self._did_tree.delete(item)
        for entry in results:
            did_id = entry.get("id", "—")
            desc   = entry.get("description", "—")
            datos  = entry.get("data", "")
            self._did_tree.insert("", "end", values=(did_id, desc, datos))

    def _uds_export_json(self):
        if not self._uds_results:
            messagebox.showinfo("Sin datos", "Ejecuta un scan UDS primero.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            title="Guardar Mapa UDS",
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(self._uds_results, indent=2), encoding="utf-8"
        )
        messagebox.showinfo("Exportado", f"Mapa UDS guardado en:\n{path}")

    # ═══════════════════════════════════════════════════════════════════════════
    # SUB-TAB 4 — Control Map
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_ctrl_tab(self):
        p = self._tab_ctrl

        # Header
        hdr = tk.Frame(p, bg=DARK_BG, pady=8)
        hdr.pack(fill="x", padx=12)
        tk.Label(hdr, text="ECU Control Map — Mapa de Control Generado",
                 bg=DARK_BG, fg=CYAN, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", padx=12)

        # Botón grande generar
        gen_row = tk.Frame(p, bg=DARK_BG, pady=10)
        gen_row.pack(fill="x", padx=12)
        self._ctrl_btn_gen = _ActionBtn(
            gen_row, "⚡ Generar Mapa Completo",
            command=self._ctrl_generate,
            color=ACCENT, w=240, h=44
        )
        self._ctrl_btn_gen.pack(side="left", padx=(0, 16))
        self._ctrl_phase_var = tk.StringVar(value="")
        tk.Label(gen_row, textvariable=self._ctrl_phase_var,
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")

        # Progress Control Map
        ctrl_prog_row = tk.Frame(p, bg=DARK_BG)
        ctrl_prog_row.pack(fill="x", padx=12, pady=(0, 8))
        self._ctrl_prog = _ProgressBar(ctrl_prog_row)
        self._ctrl_prog.pack(fill="x")

        # KPI resumen
        kpi_frame = tk.Frame(p, bg=DARK_BG)
        kpi_frame.pack(fill="x", padx=12, pady=(0, 8))
        self._ctrl_card_proto = _StatCard(kpi_frame, "Protocolo",  "—", ACCENT_LT)
        self._ctrl_card_can   = _StatCard(kpi_frame, "IDs CAN",    "0", CYAN)
        self._ctrl_card_uds   = _StatCard(kpi_frame, "Servicios",  "0", YELLOW)
        self._ctrl_card_pids  = _StatCard(kpi_frame, "PIDs",       "0", GREEN)
        self._ctrl_card_dids  = _StatCard(kpi_frame, "DIDs",       "0", ORANGE)
        for card in (self._ctrl_card_proto, self._ctrl_card_can,
                     self._ctrl_card_uds, self._ctrl_card_pids,
                     self._ctrl_card_dids):
            card.pack(side="left", padx=4)

        # Actuadores candidatos
        tk.Label(p, text="ACTUADORES CANDIDATOS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w", padx=12)

        act_frame = tk.Frame(p, bg=CARD)
        act_frame.pack(fill="x", padx=12, pady=(0, 6))

        act_cols = ("parametro", "tipo", "did_pid", "acceso")
        self._ctrl_act_tree = ttk.Treeview(act_frame, columns=act_cols,
                                            show="headings", selectmode="browse",
                                            height=5)
        for col, lbl, w in [
            ("parametro", "Parámetro",   160),
            ("tipo",      "Tipo",         80),
            ("did_pid",   "DID/PID",      80),
            ("acceso",    "Acceso",        90),
        ]:
            self._ctrl_act_tree.heading(col, text=lbl)
            self._ctrl_act_tree.column(col, width=w, anchor="w")
        self._ctrl_act_tree.pack(fill="x")

        # Snippet Python generado
        snip_hdr = tk.Frame(p, bg=DARK_BG)
        snip_hdr.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(snip_hdr, text="SNIPPET PYTHON GENERADO",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(side="left")
        _ActionBtn(snip_hdr, "📋 Copiar código",
                   command=self._ctrl_copy_code,
                   color=BORDER, w=130, h=24).pack(side="right", padx=(4, 0))
        _ActionBtn(snip_hdr, "📄 Exportar .md",
                   command=self._ctrl_export_md,
                   color=BORDER, w=130, h=24).pack(side="right", padx=(4, 0))
        _ActionBtn(snip_hdr, "💾 Exportar .json",
                   command=self._ctrl_export_json,
                   color=BORDER, w=140, h=24).pack(side="right", padx=(4, 0))

        snip_border = tk.Frame(p, bg=BORDER, padx=2, pady=2)
        snip_border.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._ctrl_snippet = tk.Text(snip_border, bg=ENTRY_BG, fg=FG,
                                      font=("Consolas", 9), wrap="none",
                                      relief="flat", state="disabled")
        snip_sb = ttk.Scrollbar(snip_border, orient="vertical",
                                 command=self._ctrl_snippet.yview)
        self._ctrl_snippet.configure(yscrollcommand=snip_sb.set)
        snip_sb.pack(side="right", fill="y")
        self._ctrl_snippet.pack(fill="both", expand=True)

        self._ctrl_snippet_set("# Ejecuta '⚡ Generar Mapa Completo' para generar el snippet.\n")

    def _ctrl_snippet_set(self, text: str):
        self._ctrl_snippet.configure(state="normal")
        self._ctrl_snippet.delete("1.0", "end")
        self._ctrl_snippet.insert("end", text)
        self._ctrl_snippet.configure(state="disabled")

    def _ctrl_generate(self):
        if self._ctrl_running:
            return
        if not _RE_AVAILABLE:
            self._ctrl_phase_var.set("Módulo en actualización")
            return
        self._ctrl_running = True
        self._ctrl_phase_var.set("Iniciando...")
        self._ctrl_prog.set_progress(0.02)
        self._ctrl_prog.start()

        phases = [
            (0.10, "Perfilando ECU..."),
            (0.35, "CAN scan..."),
            (0.65, "UDS map..."),
            (0.90, "Generando mapa de control..."),
        ]

        def _run():
            try:
                send_fn = self._get_send_fn_or_demo()
                ctrl_map = ECUControlMap(send_fn)
                for pct, msg in phases:
                    self.after(0, lambda p=pct, m=msg: (
                        self._ctrl_prog.set_progress(p),
                        self._ctrl_phase_var.set(m)
                    ))
                result = ctrl_map.full_scan(
                    callback=lambda msg, pct: self.after(
                        0, lambda m=msg, p=pct: (
                            self._ctrl_prog.set_progress(p),
                            self._ctrl_phase_var.set(m)
                        )
                    )
                )
                self.after(0, lambda r=result: self._ctrl_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._ctrl_error(str(e)))

        self._ctrl_thread = threading.Thread(target=_run, daemon=True)
        self._ctrl_thread.start()

    def _ctrl_done(self, result):
        self._ctrl_running = False
        self._ctrl_map = result
        self._ctrl_prog.stop()
        self._ctrl_prog.set_progress(1.0)
        self._ctrl_phase_var.set("Completado.")

        # Actualizar KPI cards
        summary = result.get("summary", {})
        self._ctrl_card_proto.update_value(summary.get("protocol", "—"), ACCENT_LT)
        self._ctrl_card_can.update_value(str(summary.get("can_ids", 0)), CYAN)
        self._ctrl_card_uds.update_value(str(summary.get("uds_services", 0)), YELLOW)
        self._ctrl_card_pids.update_value(str(summary.get("pids", 0)), GREEN)
        self._ctrl_card_dids.update_value(str(summary.get("dids", 0)), ORANGE)

        # Poblar actuadores
        for item in self._ctrl_act_tree.get_children():
            self._ctrl_act_tree.delete(item)
        for act in result.get("actuators", []):
            self._ctrl_act_tree.insert("", "end", values=(
                act.get("parameter", "—"),
                act.get("type", "—"),
                act.get("did_pid", "—"),
                act.get("access", "—"),
            ))

        # Mostrar snippet
        snippet = result.get("snippet", "# (sin snippet generado)")
        self._ctrl_snippet_set(snippet)

    def _ctrl_error(self, msg: str):
        self._ctrl_running = False
        self._ctrl_prog.stop()
        self._ctrl_phase_var.set(f"Error: {msg[:80]}")

    def _ctrl_copy_code(self):
        self._ctrl_snippet.configure(state="normal")
        code = self._ctrl_snippet.get("1.0", "end")
        self._ctrl_snippet.configure(state="disabled")
        self.clipboard_clear()
        self.clipboard_append(code)
        messagebox.showinfo("Copiado", "Snippet copiado al portapapeles.")

    def _ctrl_export_json(self):
        if not self._ctrl_map:
            messagebox.showinfo("Sin datos", "Genera el mapa primero.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            title="Guardar Control Map JSON",
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(self._ctrl_map, indent=2), encoding="utf-8"
        )
        messagebox.showinfo("Exportado", f"JSON guardado en:\n{path}")

    def _ctrl_export_md(self):
        if not self._ctrl_map:
            messagebox.showinfo("Sin datos", "Genera el mapa primero.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Todos", "*.*")],
            title="Guardar Informe Markdown",
        )
        if not path:
            return
        s = self._ctrl_map.get("summary", {})
        lines = [
            "# ECU Control Map\n",
            f"**Protocolo:** {s.get('protocol', '—')}  ",
            f"**IDs CAN:** {s.get('can_ids', 0)}  ",
            f"**Servicios UDS:** {s.get('uds_services', 0)}  ",
            f"**PIDs:** {s.get('pids', 0)}  ",
            f"**DIDs:** {s.get('dids', 0)}\n",
            "\n## Actuadores Candidatos\n",
            "| Parámetro | Tipo | DID/PID | Acceso |",
            "|-----------|------|---------|--------|",
        ]
        for act in self._ctrl_map.get("actuators", []):
            lines.append(
                f"| {act.get('parameter','—')} | {act.get('type','—')} "
                f"| {act.get('did_pid','—')} | {act.get('access','—')} |"
            )
        lines += ["\n## Snippet Python\n", "```python",
                  self._ctrl_map.get("snippet", ""), "```"]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Exportado", f"Informe Markdown guardado en:\n{path}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Helpers compartidos
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_send_fn_or_demo(self):
        """Devuelve la función de envío real o una demo."""
        if self._app is not None:
            vc = getattr(self._app, "vehicle_conn", None)
            if vc is not None:
                proto = getattr(vc, "_proto", None)
                if proto is not None and hasattr(proto, "send_raw"):
                    return proto.send_raw
            backend = getattr(self._app, "backend", None)
            if backend is not None and hasattr(backend, "send_command"):
                return backend.send_command
        # Función demo que simula respuestas básicas
        def _demo_send(cmd):
            return "41 00 BE 3F A8 13"
        return _demo_send

    # ═══════════════════════════════════════════════════════════════════════════
    # Perfil ECU — Session control (sub-tab 1)
    # ═══════════════════════════════════════════════════════════════════════════

    def _start_session(self):
        if self._running:
            return
        if not _RE_AVAILABLE:
            messagebox.showwarning(
                "Módulo no disponible",
                f"El módulo reverse_engineer no está disponible.\n{_RE_IMPORT_ERROR}"
            )
            return
        self._running = True
        self._clear_results()
        self._prog_bar.set_progress(0.0)
        self._prog_bar.start()

        if self._demo_var.get():
            send_fn = self._get_demo_fn()
        else:
            send_fn = self._get_live_fn()
            if send_fn is None:
                self._running = False
                return

        fuzz    = not self._only_profile.get()
        mode    = self._fuzz_mode.get()
        session = ReverseEngineerSession(
            send_fn=send_fn,
            on_progress=self._on_progress,
        )

        def _run():
            try:
                result = session.run(fuzz=fuzz, fuzz_mode=mode)
                self.after(0, lambda: self._on_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _stop_session(self):
        self._running = False
        self._prog_bar.stop()
        self._set_progress("Sesión detenida por el usuario.", 0.0)

    def _get_demo_fn(self):
        from ..comm.reverse_engineer import _demo_send_fn
        return _demo_send_fn

    def _get_live_fn(self):
        try:
            backend = getattr(self._app, "backend", None)
            if backend and hasattr(backend, "send_command"):
                return backend.send_command
            proto = getattr(self._app, "_protocol", None)
            if proto and hasattr(proto, "send_command"):
                return proto.send_command
        except Exception:
            pass
        messagebox.showwarning(
            "Sin conexión",
            "No hay backend ELM327 conectado.\n"
            "Activa el modo DEMO o conecta el adaptador primero."
        )
        return None

    # ── Callbacks perfil ECU ──────────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: float):
        self.after(0, lambda: self._set_progress(msg, pct))

    def _set_progress(self, msg: str, pct: float):
        self._prog_bar.set_progress(pct)
        self._prog_label.configure(text=msg)

    def _on_done(self, result):
        self._running = False
        self._result  = result
        self._prog_bar.stop()
        self._prog_bar.set_progress(1.0)
        self._set_progress(
            f"Completado en {result.duration_s}s — "
            f"{len(result.fuzz_catalog)} PIDs/DIDs encontrados.", 1.0
        )
        self._update_kpis(result)
        self._populate_tree(result)
        self._show_profile_detail(result)

    def _on_error(self, msg: str):
        self._running = False
        self._prog_bar.stop()
        self._set_progress(f"Error: {msg}", 0.0)
        messagebox.showerror("Error RE", msg)

    # ── UI updates perfil ECU ─────────────────────────────────────────────────

    def _update_kpis(self, result):
        p  = result.profile
        ps = result.pattern_stats
        self._card_proto.update_value(p.best_protocol, ACCENT_LT)
        vin_short = (p.vin[:11] + "…") if (p.vin and len(p.vin) > 11) else (p.vin or "—")
        self._card_vin.update_value(vin_short, CYAN)
        self._card_pids.update_value(str(len(result.fuzz_catalog)),
                                      GREEN if result.fuzz_catalog else SUBTEXT)
        self._card_ecus.update_value(str(len(p.ecu_addresses)),
                                      YELLOW if p.ecu_addresses else SUBTEXT)
        self._card_entropy.update_value(f"{ps['avg_entropy']}b", ORANGE)
        self._card_duration.update_value(f"{result.duration_s}s", SUBTEXT)

    def _populate_tree(self, result):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in result.fuzz_catalog:
            pid  = entry.get("pid_did", "—")
            svc  = entry.get("service", "—")
            resp = entry.get("response", "")[:40]
            nb   = str(len(entry.get("bytes", [])))
            ent  = str(entry.get("entropy", 0.0))
            iid  = self.tree.insert("", "end",
                                     values=(pid, svc, resp, nb, ent))
            e_val = float(entry.get("entropy", 0.0))
            if e_val > 3.5:
                self.tree.item(iid, tags=("high_entropy",))
            elif e_val > 1.5:
                self.tree.item(iid, tags=("mid_entropy",))

        self.tree.tag_configure("high_entropy",
                                 background="#0a1a0a", foreground=GREEN)
        self.tree.tag_configure("mid_entropy",
                                 background="#0e0e1c", foreground=CYAN)

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel or not self._result:
            return
        vals = self.tree.item(sel[0], "values")
        pid, svc, resp, nb, ent = vals

        entry = next(
            (e for e in self._result.fuzz_catalog
             if e.get("pid_did") == pid),
            None
        )
        if not entry:
            return

        d = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "PID / DID SELECCIONADO\n", "heading")
        d.insert("end", f"  Identificador : ", "key")
        d.insert("end", f"{pid}\n", "value")
        d.insert("end", f"  Servicio      : ", "key")
        d.insert("end", f"{svc}\n", "value")
        d.insert("end", f"  Entropía      : ", "key")
        e_val = float(ent)
        color = "positive" if e_val > 3.5 else "warn" if e_val > 1.5 else "negative"
        d.insert("end", f"{ent} bits\n", color)

        d.insert("end", "\nRESPUESTA CRUDA\n", "heading")
        d.insert("end", f"  {entry.get('response', '')}\n", "value")

        d.insert("end", "\nBYTES DECODIFICADOS\n", "heading")
        raw_bytes = entry.get("bytes", [])
        hex_str = " ".join(f"{b:02X}" for b in raw_bytes)
        d.insert("end", f"  HEX : {hex_str}\n", "value")
        ascii_str = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in raw_bytes)
        d.insert("end", f"  ASCII: {ascii_str}\n", "value")

        d.insert("end", "\nANÁLISIS DE PATRÓN\n", "heading")
        stats = PatternAnalyzer.analyze_frame(entry.get("response", ""))
        d.insert("end", f"  Bytes totales  : {stats.length}\n", "value")
        d.insert("end", f"  Checksum OK    : ", "key")
        ck = stats.checksum_ok
        d.insert("end", f"{'Sí' if ck else 'No' if ck is False else '—'}\n",
                 "positive" if ck else "negative")
        d.insert("end", f"  Bytes más comunes:\n", "key")
        for byte_val, cnt in stats.top_bytes[:4]:
            d.insert("end", f"    0x{byte_val:02X} = {cnt}×\n", "subtext")

        d.configure(state="disabled")

    def _show_profile_detail(self, result):
        p  = result.profile
        ps = result.pattern_stats
        d  = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "PERFIL DE ECU DETECTADO\n", "heading")
        d.insert("end", f"  Protocolo     : ", "key")
        d.insert("end", f"{p.best_protocol}\n", "positive")
        d.insert("end", f"  VIN           : ", "key")
        d.insert("end", f"{p.vin or '—'}\n", "value")
        d.insert("end", f"  ECUs en red   : ", "key")
        d.insert("end", f"{', '.join(p.ecu_addresses) or '—'}\n", "value")
        d.insert("end", f"  Servicios OK  : ", "key")
        d.insert("end", f"{', '.join(hex(s) for s in p.supported_services) or '—'}\n",
                 "value")

        d.insert("end", "\nCONFIANZA POR PROTOCOLO\n", "heading")
        for g in p.protocol_guesses[:4]:
            bar = "█" * int(g.confidence * 10) + "░" * (10 - int(g.confidence * 10))
            color = "positive" if g.confidence > 0.6 else "warn" if g.confidence > 0.3 else "subtext"
            d.insert("end", f"  {g.protocol:12s} {bar} {g.confidence*100:.0f}%\n", color)

        d.insert("end", "\nESTADÍSTICAS DE SESIÓN\n", "heading")
        d.insert("end", f"  Frames totales : {ps['total_frames']}\n", "value")
        d.insert("end", f"  Frames únicos  : {ps['unique_frames']}\n", "value")
        d.insert("end", f"  Entropía media : {ps['avg_entropy']} bits\n", "value")
        d.insert("end", f"  Duración       : {result.duration_s}s\n", "value")

        if p.protocol_guesses:
            best = p.protocol_guesses[0]
            d.insert("end", "\nCOMENDOS AT RECOMENDADOS\n", "heading")
            for cmd in best.recommended_init:
                d.insert("end", f"  {cmd}\n", "key")

        d.configure(state="disabled")

    def _show_detail_idle(self):
        d = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "MÓDULO DE INGENIERÍA INVERSA\n\n", "heading")
        d.insert("end", "Técnicas implementadas:\n", "key")
        for line in [
            "• Agent-loop (observar → hipótesis → refinar)",
            "• Firma de protocolos (UDS/KWP2000/OBD2/ISO9141)",
            "• Fuzzing de PIDs OBD (Mode 01–0A)",
            "• Fuzzing de DIDs UDS 0x22 (0xF100–0xF1FF)",
            "• Análisis de entropía de Shannon",
            "• Histograma de bytes",
            "• Verificación de checksums (XOR / suma)",
            "• Field Journal (log completo request→response)",
        ]:
            d.insert("end", f"  {line}\n", "subtext")
        d.insert("end", "\nInicia una sesión con ▶ INICIAR SESIÓN RE\n", "warn")
        d.configure(state="disabled")

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for card in (self._card_proto, self._card_vin, self._card_pids,
                     self._card_ecus, self._card_entropy, self._card_duration):
            card.update_value("—")
        self._show_detail_idle()

    # ── Export perfil ECU ─────────────────────────────────────────────────────

    def _export(self):
        if not self._result:
            messagebox.showinfo("Sin datos", "Primero ejecuta una sesión RE.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            title="Guardar catálogo RE",
        )
        if not path:
            return
        data = {
            "profile":         self._result.profile.to_dict(),
            "fuzz_catalog":    self._result.fuzz_catalog,
            "pattern_stats":   self._result.pattern_stats,
            "journal_summary": self._result.journal_summary,
            "duration_s":      self._result.duration_s,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Exportado", f"Datos guardados en:\n{path}")
