"""Widgets personalizados con estilo moderno para Scaner Soler Pro."""
import tkinter as tk
from tkinter import ttk

DARK_BG = "#1e1e2e"
SURFACE = "#313244"
ACCENT = "#89b4fa"
TEXT = "#cdd6f4"
GREEN = "#a6e3a1"
RED = "#f38ba8"
YELLOW = "#f9e2af"


class GaugeWidget(tk.Canvas):
    """Gauge circular para mostrar valores como RPM, temperatura, etc."""
    def __init__(self, parent, label="", min_val=0, max_val=100, unit="", **kw):
        super().__init__(parent, width=120, height=120,
                        bg=DARK_BG, highlightthickness=0, **kw)
        self.label = label
        self.min_val = min_val
        self.max_val = max_val
        self.unit = unit
        self._value = min_val
        self._draw()

    def set_value(self, value):
        self._value = max(self.min_val, min(self.max_val, value))
        self.delete("all")
        self._draw()

    def _draw(self):
        cx, cy, r = 60, 55, 45
        # Arco de fondo
        self.create_arc(cx-r, cy-r, cx+r, cy+r,
                        start=220, extent=-260,
                        outline="#45475a", width=8, style="arc")
        # Arco de valor
        pct = (self._value - self.min_val) / max(self.max_val - self.min_val, 1)
        extent = -int(pct * 260)
        color = GREEN if pct < 0.7 else (YELLOW if pct < 0.9 else RED)
        if extent != 0:
            self.create_arc(cx-r, cy-r, cx+r, cy+r,
                            start=220, extent=extent,
                            outline=color, width=8, style="arc")
        # Valor
        self.create_text(cx, cy, text=f"{self._value:.1f}",
                         fill=TEXT, font=("Consolas", 14, "bold"))
        self.create_text(cx, cy+18, text=self.unit,
                         fill="#585b70", font=("Consolas", 8))
        self.create_text(cx, cy+35, text=self.label,
                         fill=ACCENT, font=("Consolas", 8, "bold"))


class LEDIndicator(tk.Canvas):
    """Indicador LED circular que puede estar ON/OFF/parpadeando."""
    def __init__(self, parent, label="", **kw):
        super().__init__(parent, width=20, height=20,
                        bg=DARK_BG, highlightthickness=0, **kw)
        self.label = label
        self._state = False
        self._draw()

    def set_state(self, state: bool):
        self._state = state
        self.delete("all")
        self._draw()

    def _draw(self):
        color = GREEN if self._state else "#45475a"
        self.create_oval(2, 2, 18, 18, fill=color, outline="")


class StatusBar(tk.Frame):
    """Barra de estado moderna con múltiples indicadores."""
    def __init__(self, parent, **kw):
        super().__init__(parent, bg="#11111b", height=28, **kw)
        self.pack_propagate(False)
        self._vars = {}
        self._add_indicator("version", "v2.0 Pro", "#585b70")
        self._add_separator()
        self._add_indicator("protocol", "Sin protocolo", "#585b70")
        self._add_separator()
        self._add_indicator("vin", "VIN: —", "#585b70")
        self._add_separator()
        self._add_indicator("voltage", "—V", "#585b70")
        self._add_separator()
        self._led = LEDIndicator(self)
        self._led.pack(side="right", padx=(0, 4))
        self._add_indicator("status", "Desconectado", RED, side="right")

    def _add_separator(self):
        tk.Label(self, text="│", bg="#11111b", fg="#313244",
                font=("Consolas", 9)).pack(side="left", padx=2)

    def _add_indicator(self, key, text, color, side="left"):
        v = tk.StringVar(value=text)
        self._vars[key] = v
        tk.Label(self, textvariable=v, bg="#11111b", fg=color,
                font=("Consolas", 9), padx=8).pack(side=side)

    def update_status(self, **kwargs):
        """Actualiza indicadores. Acepta: version, protocol, vin, voltage, status, connected."""
        for k, v in kwargs.items():
            if k in self._vars:
                self._vars[k].set(v)
        if "connected" in kwargs:
            self._led.set_state(bool(kwargs["connected"]))
