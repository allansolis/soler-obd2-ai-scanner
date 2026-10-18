"""
Tab EV — Dashboard de vehículos eléctricos e híbridos.
Muestra: BMS (SOC/SOH/voltaje/corriente), estado de carga, DTCs EV, detección de marca.
"""
from __future__ import annotations

import math
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

# ── Paleta (coincide con app.py) ───────────────────────────────────────────────
BG      = "#080812"
SURFACE = "#0e0e1c"
CARD    = "#141428"
BORDER  = "#1e1e38"
ACCENT  = "#7c3aed"
ACCENT2 = "#a855f7"
CYAN    = "#06b6d4"
GREEN   = "#10b981"
RED     = "#f43f5e"
YELLOW  = "#f59e0b"
TEXT    = "#e2e8f0"
SUBTEXT = "#64748b"
ENTRY_BG = "#1a1a32"

EV_GREEN   = "#34d399"   # verde EV
EV_BLUE    = "#38bdf8"   # azul carga
EV_ORANGE  = "#fb923c"   # temperatura alta

SEVERITY_COLOR = {
    "critical": RED,
    "warning":  YELLOW,
    "info":     CYAN,
    "":         TEXT,
}

# ── Datos demo ────────────────────────────────────────────────────────────────

_DEMO_BMS = {
    "brand":        "VW_MEB",
    "soc_pct":      78.5,
    "soh_pct":      96.2,
    "pack_voltage": 390.4,
    "pack_current": -12.3,
    "pack_power_kw": -4.8,
    "temp_max":     28.0,
    "temp_min":     24.5,
    "temp_delta":    3.5,
    "motor_temp":   42.0,
    "inverter_temp": 35.0,
    "cells_count":  96,
    "cells_max_v":  4.08,
    "cells_min_v":  4.05,
    "cells_delta_v": 0.03,
    "range_km":     214.0,
    "energy_kwh_total": 58400.0,
}

_DEMO_CHARGING = {
    "state":     "DISCONNECTED",
    "protocol":  "—",
    "voltage_v": 0.0,
    "current_a": 0.0,
    "power_kw":  0.0,
    "energy_kwh": 0.0,
    "elapsed_s":  0,
    "soc_start":  0.0,
    "target_soc": 80.0,
}

_DEMO_DTCS = [
    {"code": "P0A80", "description": "Replace HV Battery Sub Pack A",
     "system": "EV Battery", "severity": "critical"},
    {"code": "B3010", "description": "EV Charge Port Communication Lost",
     "system": "EV Charging", "severity": "warning"},
]


# ── Gauge circular canvas ─────────────────────────────────────────────────────

class CircularGauge(tk.Canvas):
    """Gauge circular con arco de color y valor central."""

    def __init__(self, parent, label="", value=0.0, max_val=100.0,
                 unit="%", color=EV_GREEN, size=110, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=CARD, highlightthickness=0, **kw)
        self._label   = label
        self._value   = value
        self._max_val = max_val
        self._unit    = unit
        self._color   = color
        self._size    = size
        self._draw()

    def update_value(self, value: float, color: str | None = None):
        self._value = value
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self._size
        pad = 10
        x0, y0, x1, y1 = pad, pad, s - pad, s - pad

        # Arco de fondo
        self.create_arc(x0, y0, x1, y1,
                        start=220, extent=-260,
                        style="arc", outline=BORDER, width=8)

        # Arco de valor
        pct   = max(0.0, min(1.0, self._value / self._max_val))
        sweep = int(-260 * pct)
        if sweep != 0:
            self.create_arc(x0, y0, x1, y1,
                            start=220, extent=sweep,
                            style="arc", outline=self._color, width=8)

        # Valor central
        cx, cy = s // 2, s // 2 - 2
        self.create_text(cx, cy - 4,
                         text=f"{self._value:.1f}",
                         fill=TEXT, font=("Consolas", 12, "bold"),
                         anchor="center")
        self.create_text(cx, cy + 12,
                         text=self._unit,
                         fill=SUBTEXT, font=("Consolas", 8),
                         anchor="center")
        # Etiqueta abajo
        self.create_text(cx, s - 8,
                         text=self._label,
                         fill=SUBTEXT, font=("Consolas", 7),
                         anchor="center")


# ── KPI Card ──────────────────────────────────────────────────────────────────

class KPICard(tk.Canvas):
    def __init__(self, parent, label="", value="—", unit="", color=CYAN,
                 width=160, height=72, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=CARD, highlightthickness=0, **kw)
        self._label = label
        self._value = value
        self._unit  = unit
        self._color = color
        self._w     = width
        self._h     = height
        self._draw()

    def update(self, value: str, color: str | None = None):
        self._value = str(value)
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        # Borde superior coloreado
        self.create_rectangle(0, 0, self._w, 3, fill=self._color, outline="")
        cx = self._w // 2
        # Valor grande
        self.create_text(cx, 32,
                         text=self._value,
                         fill=TEXT, font=("Consolas", 14, "bold"),
                         anchor="center")
        # Unidad
        if self._unit:
            self.create_text(cx, 48,
                             text=self._unit,
                             fill=self._color, font=("Consolas", 8),
                             anchor="center")
        # Etiqueta
        self.create_text(cx, 62,
                         text=self._label,
                         fill=SUBTEXT, font=("Consolas", 7),
                         anchor="center")


# ── Barra de progreso personalizada ──────────────────────────────────────────

class ProgressBar(tk.Canvas):
    def __init__(self, parent, value=0.0, max_val=100.0, color=EV_GREEN,
                 width=200, height=16, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=CARD, highlightthickness=0, **kw)
        self._val     = value
        self._max     = max_val
        self._color   = color
        self._w       = width
        self._h       = height
        self._draw()

    def update_value(self, value: float, color: str | None = None):
        self._val = value
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        r  = self._h // 2
        # Fondo
        self.create_rounded_rect(0, 0, self._w, self._h, r, fill=BORDER, outline="")
        # Relleno
        pct  = max(0.0, min(1.0, self._val / self._max))
        fill = int(self._w * pct)
        if fill > r * 2:
            self.create_rounded_rect(0, 0, fill, self._h, r, fill=self._color, outline="")

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)


# ── Tab principal ─────────────────────────────────────────────────────────────

class EVTab(tk.Frame):
    """
    Tab EV — conecta con ECUReader para leer BMS y ChargingSession.
    Funciona en modo demo sin hardware.
    """

    def __init__(self, parent, app=None, **kw):
        super().__init__(parent, bg=BG, **kw)
        self._app      = app
        self._demo     = True
        self._bms_data = dict(_DEMO_BMS)
        self._chg_data = dict(_DEMO_CHARGING)
        self._dtcs     = list(_DEMO_DTCS)
        self._running  = False

        self._build_ui()
        self._update_display()
        self._schedule_demo_tick()

    # ── Construcción de la UI ─────────────────────────────────────────────────

    def _build_ui(self):
        # ── Cabecera ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x", pady=(0, 1))
        tk.Frame(hdr, bg=ACCENT, height=2).pack(fill="x")
        inner_hdr = tk.Frame(hdr, bg=SURFACE)
        inner_hdr.pack(fill="x", padx=16, pady=8)

        tk.Label(inner_hdr, text="⚡  EV / BMS Dashboard",
                 bg=SURFACE, fg=TEXT,
                 font=("Consolas", 11, "bold")).pack(side="left")

        # Indicadores de marca y modo
        self._brand_lbl = tk.Label(inner_hdr, text="MARCA: VW MEB",
                                   bg=SURFACE, fg=EV_GREEN,
                                   font=("Consolas", 9, "bold"))
        self._brand_lbl.pack(side="left", padx=(20, 0))

        self._mode_lbl = tk.Label(inner_hdr, text="● DEMO",
                                  bg=SURFACE, fg=YELLOW,
                                  font=("Consolas", 9, "bold"))
        self._mode_lbl.pack(side="right")

        # Botones de acción
        btn_frame = tk.Frame(inner_hdr, bg=SURFACE)
        btn_frame.pack(side="right", padx=(0, 16))
        ttk.Button(btn_frame, text="Escanear EV",
                   style="Accent.TButton",
                   command=self._on_scan).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Borrar DTCs",
                   command=self._on_clear_dtcs).pack(side="left", padx=4)

        # ── Cuerpo principal ──────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=2)
        body.rowconfigure(1, weight=1)

        # Panel izquierdo: gauges BMS + KPIs
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self._build_bms_panel(left)

        # Panel derecho: carga
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self._build_charging_panel(right)

        # Fila inferior: DTCs EV
        bottom = tk.Frame(body, bg=BG)
        bottom.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(4, 0))

        self._build_dtc_panel(bottom)

    def _build_bms_panel(self, parent):
        lf = tk.LabelFrame(parent, text=" Battery Management System ",
                           bg=BG, fg=SUBTEXT,
                           font=("Consolas", 8, "bold"),
                           relief="flat", bd=1, highlightbackground=BORDER,
                           highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=4, pady=4)

        # Gauges SOC + SOH
        gauge_row = tk.Frame(lf, bg=BG)
        gauge_row.pack(pady=8)

        self._gauge_soc = CircularGauge(
            gauge_row, label="SOC", value=78.5, max_val=100.0,
            unit="%", color=EV_GREEN, size=120)
        self._gauge_soc.pack(side="left", padx=16)

        self._gauge_soh = CircularGauge(
            gauge_row, label="SOH", value=96.2, max_val=100.0,
            unit="%", color=EV_BLUE, size=120)
        self._gauge_soh.pack(side="left", padx=16)

        self._gauge_temp = CircularGauge(
            gauge_row, label="Temp. Máx.", value=28.0, max_val=60.0,
            unit="°C", color=YELLOW, size=120)
        self._gauge_temp.pack(side="left", padx=16)

        # Barra de carga
        bar_frame = tk.Frame(lf, bg=BG)
        bar_frame.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(bar_frame, text="Carga del pack:", bg=BG, fg=SUBTEXT,
                 font=("Consolas", 8)).pack(side="left")
        self._soc_bar = ProgressBar(bar_frame, value=78.5, color=EV_GREEN,
                                    width=260, height=14)
        self._soc_bar.pack(side="left", padx=(8, 0))
        self._soc_pct_lbl = tk.Label(bar_frame, text="78.5%",
                                     bg=BG, fg=EV_GREEN,
                                     font=("Consolas", 9, "bold"))
        self._soc_pct_lbl.pack(side="left", padx=(8, 0))

        # KPI cards
        kpi_row = tk.Frame(lf, bg=BG)
        kpi_row.pack(pady=(0, 8))

        self._kpi_voltage = KPICard(kpi_row, label="Voltaje Pack", value="390.4",
                                    unit="V", color=EV_BLUE, width=140)
        self._kpi_voltage.pack(side="left", padx=6)

        self._kpi_current = KPICard(kpi_row, label="Corriente", value="-12.3",
                                    unit="A", color=CYAN, width=140)
        self._kpi_current.pack(side="left", padx=6)

        self._kpi_power = KPICard(kpi_row, label="Potencia", value="-4.8",
                                  unit="kW", color=ACCENT2, width=140)
        self._kpi_power.pack(side="left", padx=6)

        self._kpi_range = KPICard(kpi_row, label="Autonomía est.", value="214",
                                  unit="km", color=EV_GREEN, width=140)
        self._kpi_range.pack(side="left", padx=6)

        # Celdas
        cell_frame = tk.Frame(lf, bg=BG)
        cell_frame.pack(padx=16, pady=(0, 8), fill="x")
        tk.Label(cell_frame, text="Celdas:", bg=BG, fg=SUBTEXT,
                 font=("Consolas", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(cell_frame, text="Máx:", bg=BG, fg=SUBTEXT,
                 font=("Consolas", 8)).grid(row=0, column=1, sticky="e", padx=(16, 4))
        self._cell_max_lbl = tk.Label(cell_frame, text="4.08 V",
                                      bg=BG, fg=TEXT,
                                      font=("Consolas", 8, "bold"))
        self._cell_max_lbl.grid(row=0, column=2, sticky="w")
        tk.Label(cell_frame, text="Mín:", bg=BG, fg=SUBTEXT,
                 font=("Consolas", 8)).grid(row=0, column=3, sticky="e", padx=(16, 4))
        self._cell_min_lbl = tk.Label(cell_frame, text="4.05 V",
                                      bg=BG, fg=TEXT,
                                      font=("Consolas", 8, "bold"))
        self._cell_min_lbl.grid(row=0, column=4, sticky="w")
        tk.Label(cell_frame, text="ΔV:", bg=BG, fg=SUBTEXT,
                 font=("Consolas", 8)).grid(row=0, column=5, sticky="e", padx=(16, 4))
        self._cell_delta_lbl = tk.Label(cell_frame, text="0.030 V",
                                        bg=BG, fg=TEXT,
                                        font=("Consolas", 8, "bold"))
        self._cell_delta_lbl.grid(row=0, column=6, sticky="w")

    def _build_charging_panel(self, parent):
        lf = tk.LabelFrame(parent, text=" Sesión de Carga ",
                           bg=BG, fg=SUBTEXT,
                           font=("Consolas", 8, "bold"),
                           relief="flat", bd=1, highlightbackground=BORDER,
                           highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=4, pady=4)

        # Estado principal
        state_frame = tk.Frame(lf, bg=BG)
        state_frame.pack(pady=10)

        self._chg_state_canvas = tk.Canvas(state_frame, width=220, height=60,
                                            bg=CARD, highlightthickness=0)
        self._chg_state_canvas.pack()

        # Gauge de progreso de carga
        self._gauge_chg = CircularGauge(
            lf, label="SOC objetivo", value=0.0, max_val=100.0,
            unit="%", color=EV_BLUE, size=110)
        self._gauge_chg.pack(pady=4)

        # KPIs de carga
        chg_kpis = tk.Frame(lf, bg=BG)
        chg_kpis.pack(pady=(0, 8))

        self._kpi_chg_v = KPICard(chg_kpis, label="V carga", value="—",
                                   unit="V", color=EV_BLUE, width=100, height=72)
        self._kpi_chg_v.pack(side="left", padx=4)

        self._kpi_chg_a = KPICard(chg_kpis, label="A carga", value="—",
                                   unit="A", color=EV_GREEN, width=100, height=72)
        self._kpi_chg_a.pack(side="left", padx=4)

        self._kpi_chg_kw = KPICard(chg_kpis, label="Potencia", value="—",
                                    unit="kW", color=ACCENT2, width=100, height=72)
        self._kpi_chg_kw.pack(side="left", padx=4)

        # Energía entregada
        energy_frame = tk.Frame(lf, bg=BG)
        energy_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(energy_frame, text="Energía entregada:",
                 bg=BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")
        self._energy_lbl = tk.Label(energy_frame, text="0.00 kWh",
                                    bg=BG, fg=TEXT,
                                    font=("Consolas", 9, "bold"))
        self._energy_lbl.pack(side="left", padx=8)

        # Protocolo
        proto_frame = tk.Frame(lf, bg=BG)
        proto_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(proto_frame, text="Protocolo:",
                 bg=BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")
        self._proto_lbl = tk.Label(proto_frame, text="—",
                                   bg=BG, fg=CYAN,
                                   font=("Consolas", 8, "bold"))
        self._proto_lbl.pack(side="left", padx=8)

        # Temperatura motor / inversor
        temp_frame = tk.Frame(lf, bg=BG)
        temp_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(temp_frame, text="Motor:",
                 bg=BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")
        self._motor_temp_lbl = tk.Label(temp_frame, text="42 °C",
                                        bg=BG, fg=TEXT,
                                        font=("Consolas", 8, "bold"))
        self._motor_temp_lbl.pack(side="left", padx=(4, 16))
        tk.Label(temp_frame, text="Inversor:",
                 bg=BG, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")
        self._inv_temp_lbl = tk.Label(temp_frame, text="35 °C",
                                      bg=BG, fg=TEXT,
                                      font=("Consolas", 8, "bold"))
        self._inv_temp_lbl.pack(side="left", padx=4)

    def _build_dtc_panel(self, parent):
        lf = tk.LabelFrame(parent, text=" DTCs Eléctricos / Híbridos ",
                           bg=BG, fg=SUBTEXT,
                           font=("Consolas", 8, "bold"),
                           relief="flat", bd=1, highlightbackground=BORDER,
                           highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ("Código", "Descripción", "Sistema", "Severidad")
        self._dtc_tree = ttk.Treeview(lf, columns=cols, show="headings",
                                       height=4)
        self._dtc_tree.heading("Código",      text="Código")
        self._dtc_tree.heading("Descripción", text="Descripción")
        self._dtc_tree.heading("Sistema",     text="Sistema")
        self._dtc_tree.heading("Severidad",   text="Severidad")
        self._dtc_tree.column("Código",      width=90,  anchor="center")
        self._dtc_tree.column("Descripción", width=420, anchor="w")
        self._dtc_tree.column("Sistema",     width=130, anchor="center")
        self._dtc_tree.column("Severidad",   width=100, anchor="center")

        sb = ttk.Scrollbar(lf, orient="vertical", command=self._dtc_tree.yview)
        self._dtc_tree.configure(yscrollcommand=sb.set)
        self._dtc_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4, padx=(0, 4))

        self._refresh_dtc_tree()

    # ── Actualización de la UI ─────────────────────────────────────────────────

    def _update_display(self):
        b = self._bms_data
        c = self._chg_data

        soc = b.get("soc_pct", 0.0) or 0.0
        soh = b.get("soh_pct", 0.0) or 0.0
        tmp = b.get("temp_max", 0.0) or 0.0

        # Color SOC según nivel
        soc_color = EV_GREEN if soc >= 50 else (YELLOW if soc >= 20 else RED)
        soh_color = EV_GREEN if soh >= 80 else (YELLOW if soh >= 60 else RED)
        tmp_color = EV_GREEN if tmp <= 35 else (YELLOW if tmp <= 45 else RED)

        self._gauge_soc.update_value(soc, soc_color)
        self._gauge_soh.update_value(soh, soh_color)
        self._gauge_temp.update_value(tmp, tmp_color)

        self._soc_bar.update_value(soc, soc_color)
        self._soc_pct_lbl.config(text=f"{soc:.1f}%", fg=soc_color)

        # KPIs pack
        self._kpi_voltage.update(f"{b.get('pack_voltage', 0):.1f}")
        cur = b.get("pack_current", 0) or 0.0
        self._kpi_current.update(f"{cur:+.1f}", CYAN if cur < 0 else EV_GREEN)
        pow_kw = b.get("pack_power_kw", 0) or 0.0
        self._kpi_power.update(f"{pow_kw:+.1f}", EV_GREEN if pow_kw < 0 else YELLOW)
        self._kpi_range.update(f"{b.get('range_km', 0):.0f}")

        # Celdas
        self._cell_max_lbl.config(text=f"{b.get('cells_max_v', 0):.3f} V")
        self._cell_min_lbl.config(text=f"{b.get('cells_min_v', 0):.3f} V")
        dv = b.get("cells_delta_v", 0) or 0.0
        dv_color = EV_GREEN if dv < 0.05 else RED
        self._cell_delta_lbl.config(text=f"{dv:.3f} V", fg=dv_color)

        # Motor/inversor
        self._motor_temp_lbl.config(
            text=f"{b.get('motor_temp', 0):.0f} °C",
            fg=EV_GREEN if (b.get("motor_temp") or 0) < 80 else RED)
        self._inv_temp_lbl.config(
            text=f"{b.get('inverter_temp', 0):.0f} °C",
            fg=EV_GREEN if (b.get("inverter_temp") or 0) < 70 else RED)

        # Marca
        brand_clean = b.get("brand", "—").replace("_", " ")
        self._brand_lbl.config(text=f"MARCA: {brand_clean}")

        # Carga
        state = c.get("state", "DISCONNECTED")
        self._update_charging_state(state)

        chg_v  = c.get("voltage_v", 0) or 0.0
        chg_a  = c.get("current_a", 0) or 0.0
        chg_kw = c.get("power_kw",  0) or 0.0
        if state == "CHARGING":
            self._kpi_chg_v.update(f"{chg_v:.0f}")
            self._kpi_chg_a.update(f"{chg_a:.0f}")
            self._kpi_chg_kw.update(f"{chg_kw:.1f}")
        else:
            self._kpi_chg_v.update("—")
            self._kpi_chg_a.update("—")
            self._kpi_chg_kw.update("—")

        self._energy_lbl.config(text=f"{c.get('energy_kwh', 0):.2f} kWh")
        self._proto_lbl.config(text=c.get("protocol", "—") or "—")

        target_soc = c.get("target_soc", 80.0) or 80.0
        self._gauge_chg.update_value(soc if state in ("CHARGING", "FINISHED") else 0.0)

    def _update_charging_state(self, state: str):
        canvas = self._chg_state_canvas
        canvas.delete("all")

        state_colors = {
            "DISCONNECTED":       SUBTEXT,
            "CONNECTED":          CYAN,
            "PROTOCOL_HANDSHAKE": YELLOW,
            "AUTHENTICATING":     YELLOW,
            "PRECHARGING":        EV_BLUE,
            "CHARGING":           EV_GREEN,
            "SUSPENDED_EV":       YELLOW,
            "SUSPENDED_EVSE":     EV_ORANGE,
            "FINISHING":          EV_BLUE,
            "FINISHED":           EV_GREEN,
            "FAULTED":            RED,
        }
        state_icons = {
            "DISCONNECTED":  "○",
            "CONNECTED":     "⌾",
            "CHARGING":      "⚡",
            "FINISHED":      "✓",
            "FAULTED":       "✗",
        }
        color = state_colors.get(state, SUBTEXT)
        icon  = state_icons.get(state, "◉")

        canvas.create_rectangle(0, 0, 220, 60, fill=CARD, outline="")
        canvas.create_rectangle(0, 0, 220, 3,  fill=color, outline="")
        canvas.create_text(110, 22, text=f"{icon}  {state}",
                          fill=color, font=("Consolas", 11, "bold"),
                          anchor="center")
        canvas.create_text(110, 44, text="Estado de carga",
                          fill=SUBTEXT, font=("Consolas", 8),
                          anchor="center")

    def _refresh_dtc_tree(self):
        for item in self._dtc_tree.get_children():
            self._dtc_tree.delete(item)
        for dtc in self._dtcs:
            sev   = dtc.get("severity", "")
            color = SEVERITY_COLOR.get(sev, TEXT)
            iid   = self._dtc_tree.insert(
                "", "end",
                values=(dtc.get("code", ""),
                        dtc.get("description", ""),
                        dtc.get("system", ""),
                        dtc.get("severity", "").upper()),
                tags=(sev,))
        for sev, color in SEVERITY_COLOR.items():
            self._dtc_tree.tag_configure(sev, foreground=color)

    # ── Simulación demo (tick cada 3s) ────────────────────────────────────────

    def _schedule_demo_tick(self):
        if not self._demo:
            return
        import random
        b = self._bms_data
        # Pequeñas variaciones para animar la pantalla
        b["soc_pct"]        = max(0.0, min(100.0, b["soc_pct"] + random.uniform(-0.2, 0.2)))
        b["pack_current"]   = b["pack_current"] + random.uniform(-0.5, 0.5)
        b["pack_power_kw"]  = b["pack_voltage"] * b["pack_current"] / 1000.0
        b["temp_max"]       = max(15, min(45, b["temp_max"] + random.uniform(-0.3, 0.3)))
        b["motor_temp"]     = max(20, min(90, b["motor_temp"] + random.uniform(-0.5, 0.5)))
        b["cells_delta_v"]  = max(0.0, min(0.1, b["cells_delta_v"] + random.uniform(-0.002, 0.002)))

        self._update_display()
        self.after(3000, self._schedule_demo_tick)

    # ── Handlers de botones ───────────────────────────────────────────────────

    def _on_scan(self):
        """Lanza un escaneo EV — en demo actualiza con datos de ejemplo."""
        if self._demo:
            self._mode_lbl.config(text="● ESCANEANDO…", fg=CYAN)
            self.after(1500, lambda: (
                self._refresh_dtc_tree(),
                self._update_display(),
                self._mode_lbl.config(text="● DEMO", fg=YELLOW)
            ))
        else:
            # Aquí iría la integración real con ECUReader.read_ev_bms()
            messagebox.showinfo("EV Scan",
                                "Conecte un adaptador ELM327 para leer datos reales.")

    def _on_clear_dtcs(self):
        if self._demo:
            self._dtcs.clear()
            self._refresh_dtc_tree()
        else:
            messagebox.showinfo("Borrar DTCs EV",
                                "Conecte un adaptador ELM327 y active el botón de borrado.")

    def on_close(self):
        self._demo = False

    def load_bms_data(self, bms_dict: dict):
        """Carga datos reales de BMSData (llamado desde hilo de diagnóstico)."""
        self._demo    = False
        self._bms_data = bms_dict
        self._mode_lbl.config(text="● EN VIVO", fg=EV_GREEN)
        self.after(0, self._update_display)

    def load_charging_data(self, chg_dict: dict):
        """Carga datos reales de ChargingSession."""
        self._chg_data = chg_dict
        self.after(0, self._update_display)

    def load_dtcs(self, dtcs: list[dict]):
        """Carga DTCs EV desde un escaneo real."""
        self._dtcs = dtcs
        self.after(0, self._refresh_dtc_tree)
