"""
Tab 3 — Editor de Mapas ECU: visualización 3D/heatmap + edición de celdas.
Usa matplotlib embebido en Tkinter.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import numpy as np

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
RED      = "#f38ba8"
GREEN    = "#a6e3a1"
YELLOW   = "#f9e2af"


def _load_matplotlib():
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    return plt, FigureCanvasTkAgg, Figure


class MapEditorTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app     = app
        self._maps   = {}
        self._cur    = None
        self._reader = None
        self._build()
        self._load_demo()

    def _build(self):
        # Left: controls
        left = ttk.Frame(self, width=220)
        left.pack(side="left", fill="y", padx=(10, 4), pady=8)
        left.pack_propagate(False)

        ttk.LabelFrame(left, text="Mapa activo").pack(fill="x", pady=4)
        self.map_var = tk.StringVar()
        self.map_cb  = ttk.Combobox(left, textvariable=self.map_var,
                                    state="readonly", width=22)
        self.map_cb.pack(fill="x", padx=6, pady=4)
        self.map_cb.bind("<<ComboboxSelected>>", lambda _: self._switch_map())

        ttk.Button(left, text="Cargar Demo", command=self._load_demo).pack(fill="x", padx=6, pady=2)
        ttk.Button(left, text="Guardar Perfil (.ssmap)", command=self._save_profile).pack(fill="x", padx=6, pady=2)

        sep = ttk.Separator(left, orient="horizontal")
        sep.pack(fill="x", pady=8)

        ttk.LabelFrame(left, text="Editar región").pack(fill="x", pady=4)
        ttk.Label(left, text="RPM idx inicio:").pack(anchor="w", padx=6)
        self.rpm_start = ttk.Spinbox(left, from_=0, to=15, width=8)
        self.rpm_start.pack(fill="x", padx=6); self.rpm_start.set(8)
        ttk.Label(left, text="RPM idx fin:").pack(anchor="w", padx=6)
        self.rpm_end = ttk.Spinbox(left, from_=0, to=15, width=8)
        self.rpm_end.pack(fill="x", padx=6); self.rpm_end.set(15)
        ttk.Label(left, text="Carga idx inicio:").pack(anchor="w", padx=6)
        self.load_start = ttk.Spinbox(left, from_=0, to=12, width=8)
        self.load_start.pack(fill="x", padx=6); self.load_start.set(8)
        ttk.Label(left, text="Carga idx fin:").pack(anchor="w", padx=6)
        self.load_end = ttk.Spinbox(left, from_=0, to=12, width=8)
        self.load_end.pack(fill="x", padx=6); self.load_end.set(12)
        ttk.Label(left, text="Delta:").pack(anchor="w", padx=6)
        self.delta_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(left, from_=-20, to=20, increment=0.5,
                    textvariable=self.delta_var, width=8).pack(fill="x", padx=6)
        ttk.Button(left, text="➕ Aplicar Delta", style="Accent.TButton",
                   command=self._apply_delta).pack(fill="x", padx=6, pady=4)
        ttk.Button(left, text="↩ Restaurar Backup",
                   command=self._restore).pack(fill="x", padx=6, pady=2)

        sep2 = ttk.Separator(left, orient="horizontal")
        sep2.pack(fill="x", pady=8)

        ttk.Label(left, text="Vista:").pack(anchor="w", padx=6)
        self.view_var = tk.StringVar(value="3D")
        for v in ("3D", "Heatmap", "Diferencia"):
            ttk.Radiobutton(left, text=v, variable=self.view_var, value=v,
                            command=self._redraw).pack(anchor="w", padx=12)

        self.info_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.info_var, foreground=ACCENT,
                  font=("Consolas", 9), wraplength=200).pack(fill="x", padx=6, pady=8)

        # Right: plot
        self.plot_frame = ttk.Frame(self)
        self.plot_frame.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=8)
        self._canvas_widget = None

    def _load_demo(self):
        from ..ecu.ecu_reader import ECUReader
        self._reader = ECUReader(conn=None, vin="DEMO123")
        self._maps   = self._reader.load_demo_maps()
        names = list(self._maps.keys())
        self.map_cb["values"] = names
        self.map_var.set(names[0])
        self._cur = self._maps[names[0]]
        self._redraw()

    def _switch_map(self):
        name = self.map_var.get()
        if name in self._maps:
            self._cur = self._maps[name]
            self._redraw()

    def _redraw(self):
        if self._cur is None:
            return
        threading.Thread(target=self._render, daemon=True).start()

    def _render(self):
        try:
            plt, FigureCanvasTkAgg, Figure = _load_matplotlib()
            import matplotlib.cm as cm

            table = self._cur
            view  = self.view_var.get()

            fig = Figure(figsize=(8, 5.5), facecolor=DARK_BG)
            ax  = fig.add_subplot(111, projection=("3d" if view == "3D" else None))
            ax.set_facecolor(DARK_BG)
            fig.patch.set_facecolor(DARK_BG)
            for spine in getattr(ax, "spines", {}).values():
                spine.set_edgecolor("#45475a")
            ax.tick_params(colors="#9399b2", labelsize=7)
            ax.xaxis.label.set_color("#9399b2")
            ax.yaxis.label.set_color("#9399b2")

            rpm_ax  = table.rpm_axis
            load_ax = table.load_axis
            data    = table.values if view != "Diferencia" else table.diff
            X, Y    = np.meshgrid(load_ax, rpm_ax)

            if view == "3D":
                surf = ax.plot_surface(X, Y, data, cmap="plasma", alpha=0.88,
                                       edgecolor="none")
                fig.colorbar(surf, ax=ax, shrink=0.5, pad=0.1,
                             label=table.unit).ax.yaxis.label.set_color("#9399b2")
                ax.set_xlabel("Carga %", labelpad=4)
                ax.set_ylabel("RPM",     labelpad=4)
                ax.set_zlabel(table.unit, labelpad=4)
                ax.zaxis.label.set_color("#9399b2")
                ax.zaxis.set_tick_params(colors="#9399b2")
            else:
                cmap = "RdYlGn_r" if view == "Diferencia" else "plasma"
                im = ax.pcolormesh(X, Y, data, cmap=cmap, shading="auto")
                fig.colorbar(im, ax=ax, label=table.unit).ax.yaxis.label.set_color("#9399b2")
                ax.set_xlabel("Carga %")
                ax.set_ylabel("RPM")
                # Annotate cells
                if data.shape[0] <= 16 and data.shape[1] <= 13:
                    for i, rpm in enumerate(rpm_ax):
                        for j, ld in enumerate(load_ax):
                            ax.text(ld, rpm, f"{data[i,j]:.1f}",
                                    ha="center", va="center",
                                    fontsize=5.5, color="#cdd6f4", alpha=0.8)

            ax.set_title(f"{table.name} — {table.unit}",
                         color=FG, fontsize=11, pad=8)
            fig.tight_layout()

            self.after(0, lambda: self._embed_plot(fig, FigureCanvasTkAgg))
        except Exception as e:
            self.after(0, lambda: self.info_var.set(f"Error render: {e}"))

    def _embed_plot(self, fig, FigureCanvasTkAgg):
        if self._canvas_widget:
            self._canvas_widget.get_tk_widget().destroy()
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_widget = canvas
        # Show checksum
        self.info_var.set(
            f"Mapa: {self._cur.name}\n"
            f"Tamaño: {self._cur.values.shape}\n"
            f"Min/Max: {self._cur.values.min():.2f} / {self._cur.values.max():.2f}\n"
            f"Checksum: {self._cur.checksum()}"
        )

    def _apply_delta(self):
        if self._cur is None:
            return
        try:
            rs = int(self.rpm_start.get())
            re = int(self.rpm_end.get())
            ls = int(self.load_start.get())
            le = int(self.load_end.get())
            delta = float(self.delta_var.get())
            from ..ecu.maps.map_editor import MapEditor
            editor = MapEditor(self._cur)
            editor.add_to_region(slice(rs, re + 1), slice(ls, le + 1), delta)
            self._redraw()
            self.app.set_status(f"Delta {delta:+.2f} aplicado a región RPM[{rs}:{re}] Load[{ls}:{le}]")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _restore(self):
        if self._cur is None:
            return
        self._cur.restore_backup()
        self._redraw()
        self.app.set_status("Mapa restaurado al backup.")

    def _save_profile(self):
        if not self._maps:
            return
        if self._reader is None:
            from ..ecu.ecu_reader import ECUReader
            self._reader = ECUReader(conn=None, vin="DEMO123")
        path = self._reader.save_map_profile(self._maps, profile_name="gui_export")
        messagebox.showinfo("Guardado", f"Perfil guardado:\n{path}")
