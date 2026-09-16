"""
Tab 4 — Optimizador: corre MapOptimizer con perfil y combustible elegidos,
muestra comparativa antes/después.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"

PROFILE_DESC = {
    "street": "Calle  — λ=1.0, margen −2°, boost 85%.\nMáxima confiabilidad y durabilidad.",
    "track":  "Pista  — λ=0.88, MBT sin margen, boost 100%.\nPotencia máxima con seguridad.",
    "race":   "Carrera— λ=0.83, MBT exacto, boost 100%.\nRendimiento absoluto, solo combustible racing.",
}


def _load_matplotlib():
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    return FigureCanvasTkAgg, Figure


class OptimizerTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._base_table  = None
        self._opt_table   = None
        self._canvas_widget = None
        self._build()
        self._load_base()

    def _build(self):
        # Top row — settings
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        settings_lf = ttk.LabelFrame(top, text="Parámetros de optimización")
        settings_lf.pack(side="left", padx=(0, 10))

        ttk.Label(settings_lf, text="Perfil:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.profile_var = tk.StringVar(value="track")
        cb = ttk.Combobox(settings_lf, textvariable=self.profile_var,
                          values=["street", "track", "race"],
                          state="readonly", width=10)
        cb.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _: self._update_profile_desc())

        ttk.Label(settings_lf, text="Combustible (oct):").grid(row=1, column=0, padx=6, sticky="e")
        self.fuel_var = tk.IntVar(value=98)
        fuel_cb = ttk.Combobox(settings_lf, textvariable=self.fuel_var,
                               values=[87, 91, 95, 98, 100, 104],
                               state="readonly", width=10)
        fuel_cb.grid(row=1, column=1, padx=4, pady=4, sticky="w")

        ttk.Label(settings_lf, text="EGT máx (°C):").grid(row=2, column=0, padx=6, sticky="e")
        self.egt_var = tk.IntVar(value=900)
        ttk.Spinbox(settings_lf, from_=700, to=980, increment=10,
                    textvariable=self.egt_var, width=10).grid(row=2, column=1, padx=4, pady=4)

        ttk.Button(settings_lf, text="⚡ Optimizar", style="Accent.TButton",
                   command=self._run_optimization).grid(row=3, column=0, columnspan=2,
                                                        padx=6, pady=8, sticky="ew")

        # Profile description
        desc_lf = ttk.LabelFrame(top, text="Descripción del perfil")
        desc_lf.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.desc_var = tk.StringVar(value=PROFILE_DESC["track"])
        ttk.Label(desc_lf, textvariable=self.desc_var, justify="left",
                  font=("Consolas", 9)).pack(padx=10, pady=8, anchor="w")

        # Safety limits display
        safety_lf = ttk.LabelFrame(top, text="Límites de seguridad activos")
        safety_lf.pack(side="left", fill="y", padx=(0, 10))
        limits = [
            ("Avance máx:", "45°"),
            ("Lambda WOT:", ">0.78"),
            ("Boost máx:",  "2.5 bar"),
            ("EGT máx:",    "980°C"),
            ("Temp refr.:", "105°C"),
        ]
        for i, (lbl, val) in enumerate(limits):
            ttk.Label(safety_lf, text=lbl, foreground="#9399b2").grid(row=i, column=0, padx=8, sticky="e")
            ttk.Label(safety_lf, text=val, foreground=GREEN,
                      font=("Consolas", 10, "bold")).grid(row=i, column=1, padx=4, sticky="w")

        # Progress / summary
        self.summary_var = tk.StringVar(value="Listo para optimizar. Presiona ⚡ Optimizar.")
        summary_lf = ttk.LabelFrame(self, text="Resumen de optimización")
        summary_lf.pack(fill="x", padx=10, pady=(0, 4))
        self.prog = ttk.Progressbar(summary_lf, mode="indeterminate")
        self.prog.pack(fill="x", padx=8, pady=4)
        tk.Text(summary_lf, textvariable=None, height=4,
                bg=ENTRY_BG, fg=ACCENT, font=("Consolas", 9),
                relief="flat", state="disabled").pack(fill="x", padx=8, pady=(0, 6))
        self.summary_text = summary_lf.winfo_children()[-1]
        self._write_summary("Listo para optimizar.")

        # Plot area
        self.plot_frame = ttk.Frame(self)
        self.plot_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    def _write_summary(self, text: str):
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.config(state="disabled")

    def _update_profile_desc(self):
        p = self.profile_var.get()
        self.desc_var.set(PROFILE_DESC.get(p, ""))

    def _load_base(self):
        from ..ecu.ecu_reader import ECUReader
        reader = ECUReader(conn=None, vin="DEMO")
        maps   = reader.load_demo_maps()
        self._base_table = maps["ignition"]

    def _run_optimization(self):
        if self._base_table is None:
            self._load_base()
        self.prog.start(12)
        self._write_summary("Optimizando con SLSQP…")
        threading.Thread(target=self._optimize_thread, daemon=True).start()

    def _optimize_thread(self):
        try:
            from ..optimizer.map_optimizer import MapOptimizer
            opt = MapOptimizer(profile=self.profile_var.get(),
                               fuel_grade=self.fuel_var.get())
            opt_table = opt.optimize_ignition(self._base_table,
                                               max_egt=float(self.egt_var.get()))
            summary = opt.summary(self._base_table, opt_table)
            self._opt_table = opt_table
            self.after(0, lambda: self._show_result(summary))
        except Exception as e:
            self.after(0, lambda: self._show_error(str(e)))

    def _show_result(self, summary: str):
        self.prog.stop()
        self._write_summary(summary)
        self.app.set_status("Optimización SLSQP completada.")
        self._render_comparison()

    def _show_error(self, msg: str):
        self.prog.stop()
        self._write_summary(f"Error: {msg}")

    def _render_comparison(self):
        if self._base_table is None or self._opt_table is None:
            return
        threading.Thread(target=self._draw_comparison, daemon=True).start()

    def _draw_comparison(self):
        try:
            FigureCanvasTkAgg, Figure = _load_matplotlib()
            import matplotlib.cm as cm

            base = self._base_table
            opt  = self._opt_table
            diff = opt.values - base.values
            rpm  = base.rpm_axis
            load = base.load_axis
            X, Y = np.meshgrid(load, rpm)

            fig = Figure(figsize=(11, 4), facecolor=DARK_BG)
            for idx, (data, title, cmap) in enumerate([
                (base.values, f"Base — {base.name}", "plasma"),
                (opt.values,  f"Optimizado ({self.profile_var.get()})", "inferno"),
                (diff,         "Diferencia (opt − base)", "RdYlGn"),
            ]):
                ax = fig.add_subplot(1, 3, idx + 1)
                ax.set_facecolor(DARK_BG)
                im = ax.pcolormesh(X, Y, data, cmap=cmap, shading="auto")
                fig.colorbar(im, ax=ax, shrink=0.7).ax.yaxis.label.set_color("#9399b2")
                ax.set_title(title, color=FG, fontsize=9)
                ax.set_xlabel("Carga %", fontsize=7, color="#9399b2")
                ax.set_ylabel("RPM",     fontsize=7, color="#9399b2")
                ax.tick_params(colors="#9399b2", labelsize=6)
            fig.tight_layout()
            self.after(0, lambda: self._embed_plot(fig, FigureCanvasTkAgg))
        except Exception as e:
            self.after(0, lambda: self._write_summary(f"Error render: {e}"))

    def _embed_plot(self, fig, FigureCanvasTkAgg):
        if self._canvas_widget:
            self._canvas_widget.get_tk_widget().destroy()
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_widget = canvas
