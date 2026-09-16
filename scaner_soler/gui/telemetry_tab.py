"""
Tab 5 — Telemetría: TrackLogger + SessionAnalyzer + gráficos de sesión.
"""
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import csv
import random
import math
from datetime import datetime

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"

SESSIONS_DIR = Path("sessions")


def _load_matplotlib():
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    return FigureCanvasTkAgg, Figure


class TelemetryTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app      = app
        self._running = False
        self._session_path: Path | None = None
        self._canvas_widget = None
        self._demo_t  = 0.0
        self._build()

    def _build(self):
        # Top row — controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        rec_lf = ttk.LabelFrame(top, text="Grabación")
        rec_lf.pack(side="left", padx=(0, 10))

        ttk.Label(rec_lf, text="Sesión:").grid(row=0, column=0, padx=6)
        self.session_name = ttk.Entry(rec_lf, width=20)
        self.session_name.insert(0, f"sesion_{datetime.now().strftime('%H%M%S')}")
        self.session_name.grid(row=0, column=1, padx=4)

        self.rec_btn = ttk.Button(rec_lf, text="⏺ Iniciar", style="Accent.TButton",
                                  command=self._toggle_record)
        self.rec_btn.grid(row=1, column=0, columnspan=2, padx=6, pady=4, sticky="ew")

        self.rec_status = ttk.Label(rec_lf, text="● Detenido", foreground=RED)
        self.rec_status.grid(row=2, column=0, columnspan=2, padx=6, pady=2)

        analyze_lf = ttk.LabelFrame(top, text="Analizar sesión guardada")
        analyze_lf.pack(side="left", padx=(0, 10))
        ttk.Button(analyze_lf, text="📂 Abrir CSV…", command=self._open_csv).pack(padx=8, pady=6)
        ttk.Button(analyze_lf, text="📊 Analizar",   command=self._analyze).pack(padx=8, pady=2)

        # Live mini-chart
        chart_lf = ttk.LabelFrame(self, text="Telemetría en vivo — RPM / Temp / Acelerador")
        chart_lf.pack(fill="x", padx=10, pady=(0, 4))
        self.live_canvas = tk.Canvas(chart_lf, height=90,
                                     bg=ENTRY_BG, highlightthickness=0)
        self.live_canvas.pack(fill="x", padx=6, pady=4)
        self._live_rpm    = []
        self._live_temp   = []
        self._live_tps    = []

        # Analysis results
        results_lf = ttk.LabelFrame(self, text="Resultados de análisis")
        results_lf.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # Left: text summary
        self.analysis_text = tk.Text(results_lf, width=36, bg=ENTRY_BG, fg=FG,
                                     font=("Consolas", 9), relief="flat",
                                     state="disabled")
        self.analysis_text.pack(side="left", fill="y", padx=(6, 0), pady=4)

        # Right: session plot
        self.plot_frame = ttk.Frame(results_lf)
        self.plot_frame.pack(side="right", fill="both", expand=True, padx=6, pady=4)

    # ── Recording ─────────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self._running:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        SESSIONS_DIR.mkdir(exist_ok=True)
        name = self.session_name.get() or f"sesion_{datetime.now().strftime('%H%M%S')}"
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_path = SESSIONS_DIR / f"{name}_{ts}.csv"
        self._running      = True
        self.rec_btn.config(text="⏹ Detener")
        self.rec_status.config(text="● Grabando", foreground=RED)
        self._live_rpm.clear(); self._live_temp.clear(); self._live_tps.clear()
        self._demo_t = 0.0
        threading.Thread(target=self._record_loop, daemon=True).start()

    def _stop_record(self):
        self._running = False
        self.rec_btn.config(text="⏺ Iniciar")
        self.rec_status.config(text="● Detenido", foreground=RED)
        self.app.set_status(f"Sesión grabada: {self._session_path}")

    def _record_loop(self):
        fields = ["timestamp", "source", "rpm", "map_kpa", "throttle",
                  "ignition_advance", "coolant_temp", "iat", "speed",
                  "maf", "o2_v", "fuel_trim_st"]
        with open(self._session_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            while self._running:
                t0 = time.time()
                row = self._demo_row(t0)
                writer.writerow(row)
                f.flush()
                self.after(0, lambda r=row: self._update_live(r))
                time.sleep(0.05)  # 20 Hz demo

    def _demo_row(self, t0: float) -> dict:
        self._demo_t += 0.05
        t = self._demo_t
        return {
            "timestamp":       t0,
            "source":          "fast",
            "rpm":             850 + 400 * abs(math.sin(t * 0.4)) + random.gauss(0, 15),
            "map_kpa":         35  + 20  * abs(math.sin(t * 0.3)),
            "throttle":        max(0, 5 + 20 * abs(math.sin(t * 0.2))),
            "ignition_advance":12  + 4   * math.sin(t * 0.15),
            "coolant_temp":    87  + random.gauss(0, 0.3),
            "iat":             28  + random.gauss(0, 0.2),
            "speed":           max(0, 0 + random.gauss(0, 0.1)),
            "maf":             max(0, 3.2 + random.gauss(0, 0.1)),
            "o2_v":            0.45 + 0.4 * math.sin(t * 1.1),
            "fuel_trim_st":    2.3 + random.gauss(0, 0.5),
        }

    def _update_live(self, row: dict):
        self._live_rpm.append(float(row.get("rpm", 0)))
        self._live_temp.append(float(row.get("coolant_temp", 0)))
        self._live_tps.append(float(row.get("throttle", 0)))
        if len(self._live_rpm) > 200:
            self._live_rpm.pop(0)
            self._live_temp.pop(0)
            self._live_tps.pop(0)
        self._draw_live()

    def _draw_live(self):
        c = self.live_canvas
        c.delete("all")
        w = c.winfo_width() or 800
        h = 90
        n = len(self._live_rpm)
        if n < 2:
            return

        def draw_signal(data, color, mn, mx, offset=0):
            rng = max(mx - mn, 1)
            pts = []
            for i, v in enumerate(data):
                x = int(i / (n - 1) * (w - 2)) + 1
                y = h - offset - int((v - mn) / rng * (h / 3))
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(pts, fill=color, width=1, smooth=True)

        draw_signal(self._live_rpm,  ACCENT, 0, 8000, offset=0)
        draw_signal(self._live_temp, YELLOW, 50, 120, offset=30)
        draw_signal(self._live_tps,  GREEN,  0, 100,  offset=60)

        # Legend
        c.create_text(4, 6,  text=f"RPM: {self._live_rpm[-1]:.0f}",
                      fill=ACCENT,  anchor="w", font=("Consolas", 7))
        c.create_text(4, 36, text=f"Temp: {self._live_temp[-1]:.1f}°C",
                      fill=YELLOW,  anchor="w", font=("Consolas", 7))
        c.create_text(4, 66, text=f"TPS: {self._live_tps[-1]:.1f}%",
                      fill=GREEN,   anchor="w", font=("Consolas", 7))

    # ── Analysis ──────────────────────────────────────────────────────────────

    def _open_csv(self):
        SESSIONS_DIR.mkdir(exist_ok=True)
        path = filedialog.askopenfilename(
            initialdir=str(SESSIONS_DIR),
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            title="Abrir sesión de telemetría",
        )
        if path:
            self._session_path = Path(path)

    def _analyze(self):
        if not self._session_path or not self._session_path.exists():
            # Generate demo session for analysis
            self._generate_demo_csv()
        threading.Thread(target=self._run_analysis, daemon=True).start()

    def _generate_demo_csv(self):
        SESSIONS_DIR.mkdir(exist_ok=True)
        self._session_path = SESSIONS_DIR / "demo_analysis.csv"
        fields = ["timestamp", "source", "rpm", "map_kpa", "throttle",
                  "ignition_advance", "coolant_temp", "speed",
                  "maf", "o2_v", "fuel_trim_st", "knock_sensor"]
        with open(self._session_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            t = 0.0
            for _ in range(600):
                t += 0.05
                w.writerow({
                    "timestamp": t,
                    "source": "fast",
                    "rpm":       max(0, 1200 + 3000 * abs(math.sin(t * 0.2)) + random.gauss(0, 50)),
                    "map_kpa":   max(0, 40 + 60 * abs(math.sin(t * 0.15))),
                    "throttle":  max(0, 10 + 70 * abs(math.sin(t * 0.2))),
                    "ignition_advance": 15 + 8 * math.sin(t * 0.1),
                    "coolant_temp": 88 + random.gauss(0, 0.5),
                    "speed":     max(0, 50 * abs(math.sin(t * 0.08))),
                    "maf":       max(0, 5 + 20 * abs(math.sin(t * 0.2))),
                    "o2_v":      0.45 + 0.42 * math.sin(t * 1.2),
                    "fuel_trim_st": random.gauss(2.0, 3.0),
                    "knock_sensor": max(0, random.gauss(0, 0.8) + (3.0 if random.random() < 0.04 else 0)),
                })

    def _run_analysis(self):
        try:
            from ..telemetry.session_analyzer import SessionAnalyzer
            analyzer = SessionAnalyzer()
            report   = analyzer.analyze(self._session_path)
            self.after(0, lambda: self._show_analysis(report))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _show_analysis(self, report):
        self.analysis_text.config(state="normal")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", report.summary())
        self.analysis_text.config(state="disabled")
        self._plot_session(report)
        self.app.set_status(f"Análisis completo — {report.total_samples} muestras, "
                            f"{report.knock_events} knock events")

    def _plot_session(self, report):
        try:
            FigureCanvasTkAgg, Figure = _load_matplotlib()
            import pandas as pd

            df  = pd.read_csv(self._session_path)
            fig = Figure(figsize=(8, 4.5), facecolor=DARK_BG)

            pids = [("rpm", ACCENT, "RPM"), ("throttle", GREEN, "Acelerador %"),
                    ("coolant_temp", YELLOW, "T° Refr."), ("fuel_trim_st", RED, "Fuel Trim")]
            valid_pids = [(c, col, lbl) for c, col, lbl in pids if c in df.columns]
            rows = math.ceil(len(valid_pids) / 2)

            for i, (col_name, color, label) in enumerate(valid_pids):
                ax = fig.add_subplot(rows, 2, i + 1)
                ax.set_facecolor(ENTRY_BG)
                ax.plot(df["timestamp"], df[col_name].fillna(method="ffill"),
                        color=color, linewidth=0.8, alpha=0.9)
                ax.set_ylabel(label, color="#9399b2", fontsize=7)
                ax.set_xlabel("t (s)",  color="#9399b2", fontsize=6)
                ax.tick_params(colors="#9399b2", labelsize=6)
                for spine in ax.spines.values():
                    spine.set_edgecolor("#45475a")

            fig.suptitle("Análisis de Sesión", color=FG, fontsize=10)
            fig.tight_layout()

            if self._canvas_widget:
                self._canvas_widget.get_tk_widget().destroy()
            canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self._canvas_widget = canvas
        except Exception:
            pass

    def on_close(self):
        self._running = False
