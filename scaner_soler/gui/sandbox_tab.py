"""
Tab "ECU Sandbox" en la GUI Tkinter.

Permite:
1. Clonar el estado de la ECU (demo o real via BackendClient)
2. Configurar n combinaciones y objetivo
3. Ejecutar la simulación en hilo de fondo
4. Ver ranking en tiempo real con barra de progreso
5. Guardar mejor config como .ssmap
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import ttk, messagebox
import tkinter as tk
from typing import Optional

DARK_BG  = "#1e1e2e"
SURFACE  = "#313244"
ACCENT   = "#89b4fa"
TEXT     = "#cdd6f4"
SUBTEXT  = "#a6adc8"
GREEN    = "#a6e3a1"
YELLOW   = "#f9e2af"
RED      = "#f38ba8"


class SandboxTab(ttk.Frame):
    """Tab de ECU Sandbox — simula miles de combinaciones de parámetros ECU."""

    GOALS = ["power", "efficiency", "speed"]

    def __init__(self, parent, backend_client=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.configure(style="Dark.TFrame")
        self.backend = backend_client
        self._q: queue.Queue = queue.Queue()
        self._sandbox = None
        self._run_thread: Optional[threading.Thread] = None
        self._build_ui()
        self.after(200, self._poll_queue)

    def _build_ui(self):
        self.configure(padding=10)

        # ── Fila superior: controles ─────────────────────────────────────────
        ctrl = ttk.LabelFrame(self, text=" ⚙  Configuración de Simulación ",
                              padding=8)
        ctrl.pack(fill="x", pady=(0, 8))

        ttk.Label(ctrl, text="Objetivo:").grid(row=0, column=0, sticky="w", padx=4)
        self._goal_var = tk.StringVar(value="power")
        ttk.Combobox(ctrl, textvariable=self._goal_var,
                     values=["power — Máxima potencia",
                             "efficiency — Menor consumo",
                             "speed — Máxima aceleración"],
                     state="readonly", width=26).grid(row=0, column=1, padx=4)

        ttk.Label(ctrl, text="Combinaciones:").grid(row=0, column=2, sticky="w", padx=8)
        self._n_var = tk.StringVar(value="1000")
        ttk.Entry(ctrl, textvariable=self._n_var, width=8).grid(row=0, column=3, padx=4)

        ttk.Label(ctrl, text="Perfil seguridad:").grid(row=0, column=4, sticky="w", padx=8)
        self._profile_var = tk.StringVar(value="street")
        ttk.Combobox(ctrl, textvariable=self._profile_var,
                     values=["street", "track", "economy"],
                     state="readonly", width=10).grid(row=0, column=5, padx=4)

        self._run_btn = ttk.Button(ctrl, text="▶  Simular",
                                   command=self._start_simulation, style="Accent.TButton")
        self._run_btn.grid(row=0, column=6, padx=12)

        self._save_btn = ttk.Button(ctrl, text="💾 Guardar mejor",
                                    command=self._save_best, state="disabled")
        self._save_btn.grid(row=0, column=7, padx=4)

        # ── Barra de progreso ────────────────────────────────────────────────
        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill="x", pady=(0, 8))

        self._progress = ttk.Progressbar(prog_frame, mode="determinate",
                                          maximum=100, value=0)
        self._progress.pack(fill="x", side="left", expand=True, padx=(0, 8))
        self._prog_label = ttk.Label(prog_frame, text="Listo", foreground=SUBTEXT)
        self._prog_label.pack(side="left")

        # ── Panel principal: resultados y detalle ────────────────────────────
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # Árbol de top resultados
        left = ttk.LabelFrame(paned, text=" 🏆  Top Resultados ", padding=4)
        paned.add(left, weight=2)

        cols = ("rank", "score", "power", "eff", "speed", "egt", "safe")
        self._tree = ttk.Treeview(left, columns=cols, show="headings",
                                   selectmode="browse", height=18)
        for c, w, txt in [("rank", 40, "#"), ("score", 65, "Score"),
                           ("power", 65, "Potencia"), ("eff", 65, "Eficiencia"),
                           ("speed", 65, "Velocidad"), ("egt", 65, "EGT °C"),
                           ("safe", 50, "Seg")]:
            self._tree.heading(c, text=txt)
            self._tree.column(c, width=w, anchor="center")

        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Panel detalle
        right = ttk.LabelFrame(paned, text=" 📋  Detalle del Candidato ", padding=8)
        paned.add(right, weight=1)

        self._detail_text = tk.Text(right, wrap="word", font=("Consolas", 9),
                                     bg=DARK_BG, fg=TEXT, relief="flat",
                                     state="disabled")
        self._detail_text.pack(fill="both", expand=True)

        # ── Barra de estado ──────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Configura y presiona ▶ Simular para comenzar.")
        ttk.Label(self, textvariable=self._status_var,
                  foreground=SUBTEXT).pack(anchor="w", pady=(6, 0))

    # ── Acciones ────────────────────────────────────────────────────────────

    def _start_simulation(self):
        try:
            n = int(self._n_var.get())
            assert 10 <= n <= 50000
        except (ValueError, AssertionError):
            messagebox.showerror("Error", "Combinaciones debe ser un número entre 10 y 50 000.")
            return

        goal_raw = self._goal_var.get().split(" ")[0]  # "power — ..." → "power"
        profile  = self._profile_var.get()

        self._run_btn.configure(state="disabled")
        self._save_btn.configure(state="disabled")
        self._progress["value"] = 0
        self._prog_label.configure(text="Iniciando...")
        self._tree.delete(*self._tree.get_children())
        self._status_var.set(f"Simulando {n} combinaciones con objetivo '{goal_raw}'...")
        self._candidates = []

        self._run_thread = threading.Thread(
            target=self._run_sandbox,
            args=(n, goal_raw, profile),
            daemon=True,
        )
        self._run_thread.start()

    def _run_sandbox(self, n: int, goal: str, profile: str):
        try:
            from ..optimizer.ecu_sandbox import ECUSandbox
            from ..ecu.ecu_reader import ECUReader

            class _FakeConn:
                def read_full_flash(self): return b"\x00" * 1024
                def write_full_flash(self, data): return True

            reader = ECUReader(conn=_FakeConn(), vin="DEMO")

            # Intenta enriquecer con datos reales del backend
            live_params = {}
            dtcs: list = []
            if self.backend and self.backend.is_online():
                sensors = self.backend.get_live_sensors()
                if isinstance(sensors, dict) and "error" not in sensors:
                    live_params = sensors
                dtc_data = self.backend.get_dtc_info("active")
                if isinstance(dtc_data, list):
                    dtcs = dtc_data

            sandbox = ECUSandbox(safety_profile=profile)
            sandbox.clone_from_vehicle(reader, live_params=live_params, dtcs=dtcs)
            self._sandbox = sandbox

            def _progress_cb(done, total):
                pct = done * 100 / total
                self._q.put(("progress", pct, done, total))

            results = sandbox.simulate_combinations(n=n, workers=6,
                                                     progress_callback=_progress_cb)
            best, top = sandbox.get_best_config(goal=goal, top_n=20)
            self._q.put(("done", top, best, goal, sandbox.run_state))

        except Exception as exc:
            self._q.put(("error", str(exc)))

    def _poll_queue(self):
        while not self._q.empty():
            msg = self._q.get_nowait()
            match msg[0]:
                case "progress":
                    _, pct, done, total = msg
                    self._progress["value"] = pct
                    self._prog_label.configure(
                        text=f"{done}/{total}  ({pct:.0f}%)")
                case "done":
                    _, top, best, goal, run_state = msg
                    self._on_simulation_done(top, best, goal, run_state)
                case "error":
                    _, err = msg
                    self._run_btn.configure(state="normal")
                    self._status_var.set(f"Error: {err}")
                    messagebox.showerror("Error en simulación", err)
        self.after(200, self._poll_queue)

    def _on_simulation_done(self, top, best, goal, run_state):
        self._candidates = top
        self._run_btn.configure(state="normal")
        self._save_btn.configure(state="normal")
        self._progress["value"] = 100
        self._prog_label.configure(text="Completado")
        self._status_var.set(
            f"✓ {run_state.total} candidatos | "
            f"{run_state.safe_count} seguros | "
            f"{run_state.elapsed_sec:.1f}s")

        self._tree.delete(*self._tree.get_children())
        weights = {"power": {"power":1,"efficiency":0.1,"speed":0.3},
                   "efficiency": {"power":0.1,"efficiency":1,"speed":0.1},
                   "speed": {"power":0.4,"efficiency":0.1,"speed":1}}.get(goal, {})
        for rank, c in enumerate(top, 1):
            cs = sum(c.scores.get(k, 0) * w for k, w in weights.items())
            tag = "safe" if c.is_safe else "unsafe"
            self._tree.insert("", "end", iid=str(c.candidate_id),
                              tags=(tag,),
                              values=(
                                  rank,
                                  f"{cs:.1f}",
                                  f"{c.scores.get('power',0):.1f}",
                                  f"{c.scores.get('efficiency',0):.1f}",
                                  f"{c.scores.get('speed',0):.1f}",
                                  f"{c.egt_celsius:.0f}",
                                  "✓" if c.is_safe else "✗",
                              ))
        self._tree.tag_configure("safe",   foreground=GREEN)
        self._tree.tag_configure("unsafe", foreground=RED)

        # Selecciona el primero automáticamente
        if top:
            self._tree.selection_set(str(top[0].candidate_id))
            self._show_candidate(top[0])

    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel or not hasattr(self, "_candidates"):
            return
        cid = int(sel[0])
        for c in self._candidates:
            if c.candidate_id == cid:
                self._show_candidate(c)
                return

    def _show_candidate(self, c):
        self._detail_text.configure(state="normal")
        self._detail_text.delete("1.0", "end")
        self._detail_text.insert("end", c.summary())
        if c.delta_pct:
            self._detail_text.insert("end", "\n\nVariaciones aplicadas:\n")
            for k, v in c.delta_pct.items():
                sign = "+" if v >= 0 else ""
                self._detail_text.insert("end", f"  {k:12s}: {sign}{v:.2f}%\n")
        self._detail_text.configure(state="disabled")

    def _save_best(self):
        if self._sandbox is None:
            return
        goal_raw = self._goal_var.get().split(" ")[0]
        try:
            path = self._sandbox.save_best_to_ssmap(goal=goal_raw)
            messagebox.showinfo("Guardado", f"Mejor configuración guardada en:\n{path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
