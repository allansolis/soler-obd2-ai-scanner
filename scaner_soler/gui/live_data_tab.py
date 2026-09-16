"""
Tab 2 — Datos en Vivo: gauges de PIDs en tiempo real.
"""
import threading
import time
import tkinter as tk
from tkinter import ttk
import math

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"

# Demo values cycling
import random

_DEMO_BASE = {
    "rpm":          {"value": 850,  "unit": "RPM",   "min": 0,    "max": 8000,  "warn": 6500},
    "map_kpa":      {"value": 35,   "unit": "kPa",   "min": 0,    "max": 250,   "warn": 200},
    "throttle":     {"value": 5,    "unit": "%",     "min": 0,    "max": 100,   "warn": 95},
    "coolant_temp": {"value": 87,   "unit": "°C",    "min": -20,  "max": 130,   "warn": 105},
    "iat":          {"value": 28,   "unit": "°C",    "min": -20,  "max": 80,    "warn": 65},
    "maf":          {"value": 3.2,  "unit": "g/s",   "min": 0,    "max": 250,   "warn": 200},
    "o2_v":         {"value": 0.45, "unit": "V",     "min": 0,    "max": 1.1,   "warn": 1.0},
    "fuel_trim_st": {"value": 2.3,  "unit": "%",     "min": -30,  "max": 30,    "warn": 15},
    "ignition_adv": {"value": 12,   "unit": "°",     "min": -10,  "max": 50,    "warn": 44},
    "speed":        {"value": 0,    "unit": "km/h",  "min": 0,    "max": 260,   "warn": 240},
    "battery_v":    {"value": 13.8, "unit": "V",     "min": 8,    "max": 16,    "warn": 14.8},
    "load_pct":     {"value": 18,   "unit": "%",     "min": 0,    "max": 100,   "warn": 95},
}

PID_LABELS = {
    "rpm": "RPM Motor", "map_kpa": "MAP", "throttle": "Acelerador",
    "coolant_temp": "T° Refrigerante", "iat": "T° Admisión",
    "maf": "MAF", "o2_v": "O₂ Voltaje", "fuel_trim_st": "Trim Combustible (CT)",
    "ignition_adv": "Avance Encendido", "speed": "Velocidad",
    "battery_v": "Batería", "load_pct": "Carga Motor",
}


class GaugeCanvas(tk.Canvas):
    """Single circular gauge widget."""

    def __init__(self, parent, label, unit, min_val, max_val, warn_val, **kw):
        super().__init__(parent, width=130, height=130, bg=DARK_BG,
                         highlightthickness=0, **kw)
        self.label    = label
        self.unit     = unit
        self.min_val  = min_val
        self.max_val  = max_val
        self.warn_val = warn_val
        self._value   = min_val
        self._draw_static()
        self.update_value(min_val)

    def _draw_static(self):
        cx, cy, r = 65, 65, 52
        # background arc track
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                        start=225, extent=-270, style="arc",
                        outline="#313244", width=8)
        # warn arc
        warn_frac = (self.warn_val - self.min_val) / max(self.max_val - self.min_val, 1)
        warn_ext  = warn_frac * -270
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                        start=225, extent=warn_ext, style="arc",
                        outline="#45475a", width=8)
        # label
        self.create_text(cx, cy + 32, text=self.label,
                         font=("Consolas", 7), fill="#6c7086", anchor="center")

    def update_value(self, value):
        self._value = value
        self.delete("dynamic")
        cx, cy, r = 65, 65, 52
        span  = max(self.max_val - self.min_val, 1)
        frac  = max(0, min(1, (value - self.min_val) / span))
        ext   = frac * -270
        color = RED if value >= self.warn_val else ACCENT

        if abs(ext) > 2:
            self.create_arc(cx - r, cy - r, cx + r, cy + r,
                            start=225, extent=ext, style="arc",
                            outline=color, width=8, tags="dynamic")
        # needle
        angle_deg = 225 - frac * 270
        angle_rad = math.radians(angle_deg)
        nx = cx + (r - 14) * math.cos(angle_rad)
        ny = cy - (r - 14) * math.sin(angle_rad)
        self.create_line(cx, cy, nx, ny, fill=color, width=2, tags="dynamic")
        self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                         fill=ENTRY_BG, outline=color, width=2, tags="dynamic")

        # value text
        fmt = f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"
        self.create_text(cx, cy - 12, text=fmt,
                         font=("Consolas", 14, "bold"), fill=color,
                         anchor="center", tags="dynamic")
        self.create_text(cx, cy + 8, text=self.unit,
                         font=("Consolas", 8), fill="#9399b2",
                         anchor="center", tags="dynamic")


class LiveDataTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app       = app
        self._running  = False
        self._gauges   = {}
        self._values   = {k: v["value"] for k, v in _DEMO_BASE.items()}
        self._build()

    def _build(self):
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=10, pady=8)
        ttk.Button(ctrl, text="▶ Iniciar",  style="Accent.TButton",
                   command=self._start).pack(side="left", padx=4)
        ttk.Button(ctrl, text="⏹ Detener",
                   command=self._stop).pack(side="left", padx=4)
        self.hz_var = tk.StringVar(value="20 Hz")
        ttk.Label(ctrl, text="  Tasa:").pack(side="left")
        ttk.Combobox(ctrl, textvariable=self.hz_var,
                     values=["5 Hz", "10 Hz", "20 Hz"], width=8,
                     state="readonly").pack(side="left", padx=4)
        self.status_lbl = ttk.Label(ctrl, text="● Detenido", foreground=RED)
        self.status_lbl.pack(side="right", padx=10)

        # Gauge grid
        gauge_frame = ttk.Frame(self)
        gauge_frame.pack(fill="both", expand=True, padx=10, pady=4)

        pids = list(_DEMO_BASE.keys())
        cols = 6
        for i, pid in enumerate(pids):
            info = _DEMO_BASE[pid]
            g = GaugeCanvas(gauge_frame,
                            label=PID_LABELS.get(pid, pid),
                            unit=info["unit"],
                            min_val=info["min"],
                            max_val=info["max"],
                            warn_val=info["warn"])
            g.grid(row=i // cols, column=i % cols, padx=8, pady=8)
            self._gauges[pid] = g

        # Raw values table below
        table_lf = ttk.LabelFrame(self, text="Valores numéricos")
        table_lf.pack(fill="x", padx=10, pady=(0, 8))

        self._val_vars = {}
        row_frame = ttk.Frame(table_lf)
        row_frame.pack(fill="x", padx=6, pady=4)
        for i, pid in enumerate(pids):
            col = i % 6
            row = i // 6
            ttk.Label(row_frame, text=PID_LABELS.get(pid, pid) + ":",
                      width=20, anchor="e").grid(row=row, column=col * 2, padx=4, pady=1, sticky="e")
            var = tk.StringVar(value=f"{self._values[pid]:.1f}")
            ttk.Label(row_frame, textvariable=var, foreground=ACCENT,
                      font=("Consolas", 10, "bold"), width=8).grid(row=row, column=col * 2 + 1, sticky="w")
            self._val_vars[pid] = var

    def _start(self):
        self._running = True
        self.status_lbl.config(text="● En vivo", foreground=GREEN)
        threading.Thread(target=self._loop, daemon=True).start()

    def _stop(self):
        self._running = False
        self.status_lbl.config(text="● Detenido", foreground=RED)

    def _loop(self):
        hz  = int(self.hz_var.get().split()[0])
        dt  = 1.0 / hz
        t   = 0.0
        while self._running:
            t += dt
            new_vals = self._simulate(t)
            self.after(0, lambda v=new_vals: self._refresh(v))
            time.sleep(dt)

    def _simulate(self, t: float) -> dict:
        import math
        v = {}
        v["rpm"]          = 850 + 200 * math.sin(t * 0.3) + random.gauss(0, 10)
        v["map_kpa"]      = 35  + 10  * math.sin(t * 0.5) + random.gauss(0, 1)
        v["throttle"]     = max(0, 5 + 3 * math.sin(t * 0.2) + random.gauss(0, 0.5))
        v["coolant_temp"] = 87  + 2   * math.sin(t * 0.05)
        v["iat"]          = 28  + random.gauss(0, 0.3)
        v["maf"]          = max(0, 3.2 + 0.5 * math.sin(t * 0.4) + random.gauss(0, 0.1))
        v["o2_v"]         = 0.45 + 0.42 * math.sin(t * 1.2)
        v["fuel_trim_st"] = 2.3 + 1.5 * math.sin(t * 0.7)
        v["ignition_adv"] = 12  + 3   * math.sin(t * 0.15)
        v["speed"]        = max(0, 0   + random.gauss(0, 0.1))
        v["battery_v"]    = 13.8 + 0.2 * math.sin(t * 0.1)
        v["load_pct"]     = max(0, 18  + 5 * math.sin(t * 0.25))
        return v

    def _refresh(self, vals: dict):
        for pid, gauge in self._gauges.items():
            val = vals.get(pid, 0)
            gauge.update_value(val)
            if pid in self._val_vars:
                self._val_vars[pid].set(f"{val:.1f}")

    def on_close(self):
        self._running = False
