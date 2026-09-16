"""
ECU Sandbox Tab — diseño moderno con Canvas widgets personalizados.
MiroFish Technology: Latin Hypercube Sampling + ThreadPoolExecutor.
"""
from __future__ import annotations

import math
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Optional

# ── Paleta ────────────────────────────────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
CARD     = "#21262d"
BORDER   = "#30363d"
ACCENT   = "#58a6ff"
ACCENT2  = "#3d8bcd"
GREEN    = "#3fb950"
GREEN2   = "#238636"
RED      = "#f85149"
YELLOW   = "#d29922"
PURPLE   = "#8b949e"
TEXT     = "#e6edf3"
SUBTEXT  = "#8b949e"
CYAN     = "#39d353"
ORANGE   = "#f0883e"

GOALS = [
    ("⚡  Máxima Potencia",   "power"),
    ("🌿  Mínimo Consumo",    "efficiency"),
    ("🏎  Máxima Velocidad",  "speed"),
]


# ── Widgets canvas personalizados ─────────────────────────────────────────────

class ArcGauge(tk.Canvas):
    """Gauge circular tipo speedometer con animación suave."""

    def __init__(self, parent, label="", unit="", color=ACCENT, size=130, **kw):
        super().__init__(parent, width=size, height=size + 20,
                         bg=BG, highlightthickness=0, **kw)
        self.label = label
        self.unit  = unit
        self.color = color
        self.size  = size
        self._target = 0.0
        self._current = 0.0
        self._display = "—"
        self._anim_id = None
        self._draw(0.0)

    def set_value(self, pct: float, display: str = ""):
        self._target = max(0.0, min(1.0, pct))
        self._display = display or f"{pct*100:.0f}"
        self._animate()

    def _animate(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
        diff = self._target - self._current
        if abs(diff) < 0.005:
            self._current = self._target
            self._redraw()
            return
        self._current += diff * 0.18
        self._redraw()
        self._anim_id = self.after(16, self._animate)

    def _redraw(self):
        self.delete("all")
        self._draw(self._current)

    def _draw(self, pct: float):
        s = self.size
        cx, cy = s // 2, s // 2
        r = s // 2 - 10
        start_angle = 210
        total_sweep  = 300

        # Track
        self._arc(cx, cy, r, start_angle, -total_sweep, "#21262d", 10)

        # Fill
        if pct > 0.001:
            clr = GREEN if pct < 0.6 else (YELLOW if pct < 0.85 else RED)
            self._arc(cx, cy, r, start_angle, -int(pct * total_sweep), clr, 10)

        # Ticks
        for i in range(11):
            ang = math.radians(start_angle - i * (total_sweep / 10))
            x1 = cx + (r - 12) * math.cos(ang)
            y1 = cy - (r - 12) * math.sin(ang)
            x2 = cx + (r - 5) * math.cos(ang)
            y2 = cy - (r - 5) * math.sin(ang)
            self.create_line(x1, y1, x2, y2, fill=BORDER, width=1)

        # Centro brillante
        self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=ACCENT, outline="")

        # Valor
        self.create_text(cx, cy - 6, text=self._display,
                         fill=TEXT, font=("Consolas", 15, "bold"))
        self.create_text(cx, cy + 12, text=self.unit,
                         fill=SUBTEXT, font=("Consolas", 7))
        self.create_text(cx, s + 10, text=self.label,
                         fill=ACCENT, font=("Consolas", 8, "bold"))

    def _arc(self, cx, cy, r, start, extent, color, width):
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                        start=start, extent=extent,
                        outline=color, width=width, style="arc")


class ScoreBar(tk.Canvas):
    """Barra de score horizontal animada."""

    def __init__(self, parent, label="", color=ACCENT, **kw):
        super().__init__(parent, height=28, bg=CARD, highlightthickness=0, **kw)
        self.label = label
        self.color = color
        self._pct   = 0.0
        self._target = 0.0
        self.bind("<Configure>", lambda e: self._redraw())
        self._animate()

    def set_value(self, pct: float):
        self._target = max(0.0, min(1.0, pct))

    def _animate(self):
        diff = self._target - self._pct
        if abs(diff) > 0.003:
            self._pct += diff * 0.15
            self._redraw()
        self.after(20, self._animate)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 200
        h = 28
        self.create_rectangle(0, 0, w, h, fill=SURFACE, outline="")
        bar_w = int(self._pct * (w - 90))
        if bar_w > 2:
            self.create_rectangle(70, 7, 70 + bar_w, h - 7,
                                  fill=self.color, outline="")
            # Brillo
            self.create_rectangle(70, 7, 70 + min(bar_w, 30), 12,
                                  fill="#ffffff30" if False else self.color, outline="")
        self.create_text(65, h // 2, text=self.label,
                         fill=SUBTEXT, font=("Consolas", 8), anchor="e")
        self.create_text(w - 4, h // 2, text=f"{self._pct*100:.0f}%",
                         fill=TEXT, font=("Consolas", 9, "bold"), anchor="e")


class ModernButton(tk.Canvas):
    """Botón canvas con efecto hover."""

    def __init__(self, parent, text="", command=None,
                 color=ACCENT, text_color="#0d1117", width=140, height=36, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=BG, highlightthickness=0, cursor="hand2", **kw)
        self.text     = text
        self.command  = command
        self.color    = color
        self.text_color = text_color
        self._w = width
        self._h = height
        self._disabled = False
        self._draw(False)
        self.bind("<Enter>",           lambda e: self._draw(True))
        self.bind("<Leave>",           lambda e: self._draw(False))
        self.bind("<Button-1>",        lambda e: self._click())
        self.bind("<ButtonRelease-1>", lambda e: self._draw(True))

    def _click(self):
        if not self._disabled and self.command:
            self._draw(True)
            self.after(80, lambda: self._draw(False) or self.command())

    def _draw(self, hover=False):
        self.delete("all")
        r = 6
        w, h = self._w, self._h
        clr = ACCENT2 if hover else self.color
        if self._disabled:
            clr = BORDER
        self._rrect(0, 0, w, h, r, clr)
        fc = SUBTEXT if self._disabled else self.text_color
        self.create_text(w // 2, h // 2, text=self.text,
                         fill=fc, font=("Consolas", 9, "bold"))

    def _rrect(self, x1, y1, x2, y2, r, fill):
        self.create_oval(x1, y1, x1+2*r, y1+2*r, fill=fill, outline="")
        self.create_oval(x2-2*r, y1, x2, y1+2*r, fill=fill, outline="")
        self.create_oval(x1, y2-2*r, x1+2*r, y2, fill=fill, outline="")
        self.create_oval(x2-2*r, y2-2*r, x2, y2, fill=fill, outline="")
        self.create_rectangle(x1+r, y1, x2-r, y2, fill=fill, outline="")
        self.create_rectangle(x1, y1+r, x2, y2-r, fill=fill, outline="")

    def configure_state(self, state):
        self._disabled = (state == "disabled")
        self.configure(cursor="" if self._disabled else "hand2")
        self._draw(False)


class AnimatedProgressBar(tk.Canvas):
    """Barra de progreso con shimmer."""

    def __init__(self, parent, **kw):
        super().__init__(parent, height=6, bg=BG, highlightthickness=0, **kw)
        self._pct    = 0.0
        self._target = 0.0
        self._shimmer = 0
        self.bind("<Configure>", lambda e: self._redraw())
        self._tick()

    def set_value(self, pct: float):
        self._target = max(0.0, min(100.0, pct))

    def _tick(self):
        diff = self._target - self._pct
        if abs(diff) > 0.2:
            self._pct += diff * 0.12
        self._shimmer = (self._shimmer + 5) % 300
        self._redraw()
        self.after(16, self._tick)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        h = 6
        self.create_rectangle(0, 0, w, h, fill=SURFACE, outline="")
        fill_w = int(self._pct / 100 * w)
        if fill_w > 2:
            self.create_rectangle(0, 0, fill_w, h, fill=ACCENT, outline="")
            # Shimmer
            sx = int(self._shimmer * fill_w / 300) - 40
            if 0 < sx < fill_w:
                self.create_rectangle(sx, 0, min(sx + 60, fill_w), h,
                                      fill="#7ec8e3", outline="")


# ── Tab principal ─────────────────────────────────────────────────────────────

class SandboxTab(ttk.Frame):
    """ECU Sandbox — interfaz moderna con canvas widgets."""

    GOALS = [g[1] for g in GOALS]

    def __init__(self, parent, backend_client=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.backend = backend_client
        self._q: queue.Queue = queue.Queue()
        self._sandbox = None
        self._candidates = []
        self._run_thread: Optional[threading.Thread] = None
        self._goal = "power"
        self._build_ui()
        self.after(200, self._poll_queue)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(root, bg=SURFACE, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🧪  ECU SANDBOX",
                 bg=SURFACE, fg=TEXT,
                 font=("Consolas", 15, "bold")).pack(side="left", padx=20)
        tk.Label(hdr, text="MiroFish Technology  ·  Latin Hypercube Sampling  ·  ThreadPoolExecutor",
                 bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 8)).pack(side="left", padx=4)
        tk.Label(hdr, text=" ML OPTIMIZER ",
                 bg=GREEN2, fg="#e6edf3",
                 font=("Consolas", 8, "bold"), padx=6).pack(side="right", padx=20)

        # ── Configuración ─────────────────────────────────────────────────────
        ctrl_wrap = tk.Frame(root, bg=BG, padx=12, pady=8)
        ctrl_wrap.pack(fill="x")

        ctrl = tk.Frame(ctrl_wrap, bg=CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        ctrl.pack(fill="x")

        inner = tk.Frame(ctrl, bg=CARD, padx=16, pady=12)
        inner.pack(fill="x")

        # Objetivo
        col0 = tk.Frame(inner, bg=CARD)
        col0.pack(side="left", padx=(0, 20))
        tk.Label(col0, text="OBJETIVO", bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w")
        gf = tk.Frame(col0, bg=CARD)
        gf.pack(pady=(4, 0))
        self._goal_btns: dict = {}
        for label, key in GOALS:
            active = (key == self._goal)
            b = tk.Label(gf, text=label,
                         bg=ACCENT if active else SURFACE,
                         fg=BG if active else SUBTEXT,
                         font=("Consolas", 8, "bold"),
                         padx=8, pady=4, cursor="hand2")
            b.pack(side="left", padx=2)
            b.bind("<Button-1>", lambda e, k=key: self._select_goal(k))
            self._goal_btns[key] = b

        # Combinaciones
        col1 = tk.Frame(inner, bg=CARD)
        col1.pack(side="left", padx=(0, 20))
        tk.Label(col1, text="COMBINACIONES", bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w")
        self._n_var = tk.StringVar(value="1000")
        e = tk.Entry(col1, textvariable=self._n_var, width=8,
                     font=("Consolas", 14, "bold"),
                     bg=SURFACE, fg=ACCENT, relief="flat",
                     insertbackground=ACCENT, bd=6)
        e.pack(pady=(4, 0))

        # Perfil
        col2 = tk.Frame(inner, bg=CARD)
        col2.pack(side="left", padx=(0, 20))
        tk.Label(col2, text="PERFIL SEGURIDAD", bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w")
        self._profile_var = tk.StringVar(value="street")
        pf = tk.Frame(col2, bg=CARD)
        pf.pack(pady=(4, 0))
        self._profile_btns: dict = {}
        for p, lbl in [("street", "🏙 Street"), ("track", "🏁 Track"), ("economy", "🌿 Eco")]:
            active = (p == "street")
            b = tk.Label(pf, text=lbl,
                         bg=ACCENT if active else SURFACE,
                         fg=BG if active else SUBTEXT,
                         font=("Consolas", 8, "bold"),
                         padx=7, pady=3, cursor="hand2")
            b.pack(side="left", padx=2)
            b.bind("<Button-1>", lambda e, pv=p: self._select_profile(pv))
            self._profile_btns[p] = b

        # Botones
        btn_col = tk.Frame(inner, bg=CARD)
        btn_col.pack(side="right")
        self._run_btn = ModernButton(btn_col, "▶  SIMULAR",
                                     command=self._start_simulation,
                                     color=ACCENT, width=130, height=38)
        self._run_btn.pack(pady=(0, 6))
        self._save_btn = ModernButton(btn_col, "💾  GUARDAR",
                                      command=self._save_best,
                                      color=GREEN2, text_color=TEXT,
                                      width=130, height=32)
        self._save_btn.pack()
        self._save_btn.configure_state("disabled")

        # ── Progreso ──────────────────────────────────────────────────────────
        prog_wrap = tk.Frame(root, bg=BG, padx=12, pady=4)
        prog_wrap.pack(fill="x")
        row = tk.Frame(prog_wrap, bg=BG)
        row.pack(fill="x")
        self._prog_label_var = tk.StringVar(value="Listo para simular")
        tk.Label(row, textvariable=self._prog_label_var,
                 bg=BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")
        self._prog_pct_var = tk.StringVar(value="")
        tk.Label(row, textvariable=self._prog_pct_var,
                 bg=BG, fg=ACCENT, font=("Consolas", 9, "bold")).pack(side="right")
        self._progress = AnimatedProgressBar(prog_wrap)
        self._progress.pack(fill="x", pady=(3, 0))

        # ── Cuerpo principal ──────────────────────────────────────────────────
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # Columna izquierda
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # Gauges
        gc = tk.Frame(left, bg=CARD,
                      highlightbackground=BORDER, highlightthickness=1)
        gc.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(gc, text="  TOP CANDIDATO — MÉTRICAS",
                 bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
        gr = tk.Frame(gc, bg=CARD)
        gr.pack(fill="x", padx=8, pady=(0, 8))
        self._gauges: dict = {}
        for key, lbl, unit, color in [
            ("score",  "SCORE",    "",   ACCENT),
            ("power",  "POTENCIA", "%",  GREEN),
            ("eff",    "EFIC.",    "%",  CYAN),
            ("speed",  "VELOC.",   "%",  ORANGE),
            ("egt",    "EGT",      "°C", RED),
        ]:
            g = ArcGauge(gr, label=lbl, unit=unit, color=color, size=108)
            g.pack(side="left", expand=True)
            self._gauges[key] = g

        # Tabla
        tc = tk.Frame(left, bg=CARD,
                      highlightbackground=BORDER, highlightthickness=1)
        tc.grid(row=1, column=0, sticky="nsew")
        th = tk.Frame(tc, bg=CARD, pady=6)
        th.pack(fill="x", padx=8)
        tk.Label(th, text="🏆  RESULTADOS", bg=CARD, fg=TEXT,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self._count_var = tk.StringVar(value="")
        tk.Label(th, textvariable=self._count_var, bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 8)).pack(side="right")

        cols = ("rank", "score", "power", "eff", "speed", "egt", "safe")
        self._tree = ttk.Treeview(tc, columns=cols,
                                   show="headings", selectmode="browse")
        for c, w, txt in [("rank", 35, "#"), ("score", 70, "Score"),
                           ("power", 70, "Potencia"), ("eff", 70, "Eficiencia"),
                           ("speed", 70, "Velocidad"), ("egt", 68, "EGT °C"),
                           ("safe", 45, "Seg")]:
            self._tree.heading(c, text=txt)
            self._tree.column(c, width=w, anchor="center")
        vsb = ttk.Scrollbar(tc, orient="v", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True,
                        padx=(4, 0), pady=4)
        vsb.pack(side="right", fill="y", pady=4, padx=(0, 4))
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.tag_configure("top",    foreground=ACCENT)
        self._tree.tag_configure("safe",   foreground=GREEN)
        self._tree.tag_configure("unsafe", foreground=RED)

        # Columna derecha
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Score bars
        bc = tk.Frame(right, bg=CARD,
                      highlightbackground=BORDER, highlightthickness=1)
        bc.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(bc, text="  COMPARATIVA DE SCORES",
                 bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=8, pady=(6, 2))
        bi = tk.Frame(bc, bg=CARD, padx=8)
        bi.pack(fill="x", pady=(0, 8))
        self._bars: dict = {}
        for key, lbl, color in [("power", "Potencia", GREEN), ("eff", "Eficiencia", CYAN),
                                  ("speed", "Velocidad", ORANGE), ("egt", "EGT", RED)]:
            bar = ScoreBar(bi, label=lbl, color=color)
            bar.pack(fill="x", pady=2)
            self._bars[key] = bar

        # Detalle
        dc = tk.Frame(right, bg=CARD,
                      highlightbackground=BORDER, highlightthickness=1)
        dc.grid(row=1, column=0, sticky="nsew")
        tk.Label(dc, text="  📋 DETALLE DEL CANDIDATO",
                 bg=CARD, fg=TEXT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        self._detail_text = tk.Text(
            dc, wrap="word", font=("Consolas", 9),
            bg=SURFACE, fg=TEXT, relief="flat",
            insertbackground=ACCENT, state="disabled")
        vsb2 = ttk.Scrollbar(dc, orient="v", command=self._detail_text.yview)
        self._detail_text.configure(yscrollcommand=vsb2.set)
        self._detail_text.pack(side="left", fill="both", expand=True,
                                padx=(4, 0), pady=4)
        vsb2.pack(side="right", fill="y", pady=4, padx=(0, 4))
        self._detail_text.tag_configure("header", foreground=ACCENT,
                                         font=("Consolas", 10, "bold"))
        self._detail_text.tag_configure("good",   foreground=GREEN)
        self._detail_text.tag_configure("bad",    foreground=RED)
        self._detail_text.tag_configure("label",  foreground=SUBTEXT)

        # Status bar
        sb = tk.Frame(root, bg=SURFACE, height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self._status_var = tk.StringVar(
            value="Configura y presiona ▶ SIMULAR para comenzar.")
        tk.Label(sb, textvariable=self._status_var,
                 bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 8)).pack(side="left", padx=12)
        self._elapsed_var = tk.StringVar(value="")
        tk.Label(sb, textvariable=self._elapsed_var,
                 bg=SURFACE, fg=ACCENT,
                 font=("Consolas", 8, "bold")).pack(side="right", padx=12)

    # ── Selección ─────────────────────────────────────────────────────────────

    def _select_goal(self, key: str):
        self._goal = key
        for k, b in self._goal_btns.items():
            b.configure(bg=ACCENT if k == key else SURFACE,
                        fg=BG if k == key else SUBTEXT)

    def _select_profile(self, profile: str):
        self._profile_var.set(profile)
        for p, b in self._profile_btns.items():
            b.configure(bg=ACCENT if p == profile else SURFACE,
                        fg=BG if p == profile else SUBTEXT)

    # ── Simulación ────────────────────────────────────────────────────────────

    def _start_simulation(self):
        try:
            n = int(self._n_var.get())
            assert 10 <= n <= 50000
        except (ValueError, AssertionError):
            messagebox.showerror("Error", "Combinaciones: número entre 10 y 50 000.")
            return

        goal    = self._goal
        profile = self._profile_var.get()

        self._run_btn.configure_state("disabled")
        self._save_btn.configure_state("disabled")
        self._progress.set_value(0)
        self._prog_label_var.set(f"Simulando {n:,} combinaciones  [{goal.upper()}]…")
        self._prog_pct_var.set("0%")
        self._tree.delete(*self._tree.get_children())
        self._status_var.set(f"▶ Simulación iniciada — objetivo: {goal}")
        self._start_ts = time.time()
        self._candidates = []
        for g in self._gauges.values():
            g.set_value(0.0, "—")

        self._run_thread = threading.Thread(
            target=self._run_sandbox, args=(n, goal, profile), daemon=True)
        self._run_thread.start()

    def _run_sandbox(self, n: int, goal: str, profile: str):
        try:
            from ..optimizer.ecu_sandbox import ECUSandbox
            from ..ecu.ecu_reader import ECUReader

            class _FakeConn:
                def read_full_flash(self): return b"\x00" * 1024
                def write_full_flash(self, data): return True

            reader = ECUReader(conn=_FakeConn(), vin="DEMO")
            live_params, dtcs = {}, []
            is_online = getattr(self.backend, "is_online", lambda: False)
            if self.backend and is_online():
                try:
                    sensors = self.backend.get_live_sensors()
                    if isinstance(sensors, dict) and "error" not in sensors:
                        live_params = sensors
                    dtc_data = self.backend.get_dtc_info("active")
                    if isinstance(dtc_data, list):
                        dtcs = dtc_data
                except Exception:
                    pass

            sandbox = ECUSandbox(safety_profile=profile)
            sandbox.clone_from_vehicle(reader, live_params=live_params, dtcs=dtcs)
            self._sandbox = sandbox

            def _cb(done, total):
                pct = done * 100 / total
                self._q.put(("progress", pct, done, total))

            sandbox.simulate_combinations(n=n, workers=6, progress_callback=_cb)
            best, top = sandbox.get_best_config(goal=goal, top_n=20)
            self._q.put(("done", top, best, goal, sandbox.run_state))

        except Exception as exc:
            self._q.put(("error", str(exc)))

    # ── Polling ───────────────────────────────────────────────────────────────

    def _poll_queue(self):
        while not self._q.empty():
            msg = self._q.get_nowait()
            match msg[0]:
                case "progress":
                    _, pct, done, total = msg
                    self._progress.set_value(pct)
                    self._prog_pct_var.set(f"{pct:.0f}%")
                    elapsed = time.time() - getattr(self, "_start_ts", time.time())
                    eta = (elapsed / pct * (100 - pct)) if pct > 1 else 0
                    self._elapsed_var.set(f"⏱ {elapsed:.0f}s  ETA {eta:.0f}s")
                case "done":
                    _, top, best, goal, run_state = msg
                    self._on_done(top, best, goal, run_state)
                case "error":
                    _, err = msg
                    self._run_btn.configure_state("normal")
                    self._prog_label_var.set("✗ Error en simulación")
                    self._status_var.set(f"Error: {err}")
                    messagebox.showerror("Error en simulación", err)
        self.after(200, self._poll_queue)

    def _on_done(self, top, best, goal, run_state):
        self._candidates = top
        self._run_btn.configure_state("normal")
        self._save_btn.configure_state("normal")
        self._progress.set_value(100)
        elapsed = time.time() - getattr(self, "_start_ts", time.time())
        self._elapsed_var.set(f"✓ {elapsed:.1f}s")
        self._prog_label_var.set(
            f"Completado — {run_state.total:,} candidatos | {run_state.safe_count} seguros")
        self._prog_pct_var.set("100%")
        self._count_var.set(f"{len(top)} resultados")
        self._status_var.set(
            f"✓ {run_state.total:,} simuladas | {run_state.safe_count} seguras | "
            f"mejor: {best.candidate_id if best else '—'}")

        weights = {
            "power":      {"power": 1.0, "efficiency": 0.1, "speed": 0.3},
            "efficiency": {"power": 0.1, "efficiency": 1.0, "speed": 0.1},
            "speed":      {"power": 0.4, "efficiency": 0.1, "speed": 1.0},
        }.get(goal, {})

        self._tree.delete(*self._tree.get_children())
        for rank, c in enumerate(top, 1):
            cs = sum(c.scores.get(k, 0) * w for k, w in weights.items())
            tag = "top" if rank == 1 else ("safe" if c.is_safe else "unsafe")
            self._tree.insert("", "end", iid=str(c.candidate_id), tags=(tag,),
                              values=(rank, f"{cs:.1f}",
                                      f"{c.scores.get('power', 0):.1f}",
                                      f"{c.scores.get('efficiency', 0):.1f}",
                                      f"{c.scores.get('speed', 0):.1f}",
                                      f"{c.egt_celsius:.0f}",
                                      "✓" if c.is_safe else "✗"))

        if top:
            self._tree.selection_set(str(top[0].candidate_id))
            self._show_candidate(top[0])

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        cid = int(sel[0])
        for c in self._candidates:
            if c.candidate_id == cid:
                self._show_candidate(c)
                return

    def _show_candidate(self, c):
        s = c.scores
        max_s = max(max(s.values()) if s else 1, 1)
        composite = sum(s.values()) / max(len(s), 1)
        self._gauges["score"].set_value(composite / 100, f"{composite:.1f}")
        for key, sk in [("power", "power"), ("eff", "efficiency"), ("speed", "speed")]:
            val = s.get(sk, 0)
            self._gauges[key].set_value(val / 100, f"{val:.1f}")
        egt_pct = min(1.0, c.egt_celsius / 1000)
        self._gauges["egt"].set_value(egt_pct, f"{c.egt_celsius:.0f}")

        for key, sk in [("power", "power"), ("eff", "efficiency"), ("speed", "speed")]:
            self._bars[key].set_value(s.get(sk, 0) / 100)
        self._bars["egt"].set_value(egt_pct)

        self._detail_text.configure(state="normal")
        self._detail_text.delete("1.0", "end")

        def ins(text, tag=""):
            self._detail_text.insert("end", text, tag)

        ins(f"Candidato #{c.candidate_id}\n", "header")
        ins("─" * 34 + "\n", "label")
        ins("Seguro: ", "label")
        ins("✓ SÍ\n" if c.is_safe else "✗ NO\n",
            "good" if c.is_safe else "bad")
        ins(f"EGT: ", "label")
        ins(f"{c.egt_celsius:.0f} °C\n",
            "bad" if c.egt_celsius > 800 else "good")
        ins("\nScores:\n", "header")
        for k, v in s.items():
            filled = int(v / 5)
            bar = "█" * filled + "░" * (20 - filled)
            ins(f"  {k:12s} {bar} {v:.1f}\n")

        if hasattr(c, "delta_pct") and c.delta_pct:
            ins("\nVariaciones aplicadas:\n", "header")
            for k, v in c.delta_pct.items():
                sign = "+" if v >= 0 else ""
                ins(f"  {k:20s} {sign}{v:.2f}%\n",
                    "good" if v > 0 else "bad")

        self._detail_text.configure(state="disabled")

    def _save_best(self):
        if not self._sandbox:
            return
        try:
            path = self._sandbox.save_best_to_ssmap(goal=self._goal)
            messagebox.showinfo("Guardado", f"Mejor config guardada:\n{path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
