from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


KNOCK_THRESHOLD = 2.5   # sensor voltage — calibrate per vehicle


@dataclass
class SessionReport:
    session_file: str
    total_samples: int = 0
    duration_sec: float = 0.0
    rpm_max: float = 0.0
    speed_max: float = 0.0
    knock_events: int = 0
    fuel_trim_avg: float = 0.0
    cell_usage: dict = field(default_factory=dict)   # (rpm_bin, load_bin) -> count
    knock_cells: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== ANALISIS DE SESION ===",
            f"Archivo:     {self.session_file}",
            f"Muestras:    {self.total_samples}",
            f"Duracion:    {self.duration_sec:.1f}s",
            f"RPM max:     {self.rpm_max:.0f}",
            f"Velocidad max: {self.speed_max:.0f} km/h",
            f"Eventos knock: {self.knock_events}",
            f"Fuel trim avg: {self.fuel_trim_avg:+.1f}%",
        ]
        if self.suggestions:
            lines.append("\nSUGERENCIAS:")
            for s in self.suggestions:
                lines.append(f"  • {s}")
        return "\n".join(lines)


class SessionAnalyzer:

    RPM_BINS  = [0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000]
    LOAD_BINS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    def analyze(self, session_file: str | Path) -> SessionReport:
        path = Path(session_file)
        if not path.exists():
            raise FileNotFoundError(f"Session file not found: {path}")

        df = pd.read_csv(path)
        report = SessionReport(session_file=str(path))

        if df.empty:
            return report

        df = df.dropna(subset=["timestamp"])
        report.total_samples = len(df)
        report.duration_sec = float(df["timestamp"].max() - df["timestamp"].min())

        if "rpm" in df.columns:
            report.rpm_max = float(df["rpm"].dropna().max())

        if "speed" in df.columns:
            report.speed_max = float(df["speed"].dropna().max())

        # Fuel trim analysis
        if "fuel_trim_st" in df.columns:
            report.fuel_trim_avg = float(df["fuel_trim_st"].dropna().mean())
            if abs(report.fuel_trim_avg) > 10:
                direction = "pobre" if report.fuel_trim_avg > 0 else "rica"
                report.suggestions.append(
                    f"Fuel trim promedio {report.fuel_trim_avg:+.1f}% — mezcla {direction}. "
                    f"Revisar inyectores o mapa de combustible."
                )

        # Knock analysis
        if "knock_sensor" in df.columns:
            knock_rows = df[df["knock_sensor"] > KNOCK_THRESHOLD]
            report.knock_events = len(knock_rows)
            if report.knock_events > 0:
                report.suggestions.append(
                    f"{report.knock_events} eventos de detonacion detectados. "
                    f"Reducir avance de encendido en zonas de alta carga/RPM."
                )
                if "rpm" in knock_rows.columns and "map_kpa" in knock_rows.columns:
                    for _, row in knock_rows.iterrows():
                        rpm = row.get("rpm")
                        load = row.get("map_kpa")
                        if rpm and load:
                            report.knock_cells.append({
                                "rpm": float(rpm),
                                "load_kpa": float(load),
                                "knock_v": float(row["knock_sensor"]),
                            })

        # Cell usage heatmap
        if "rpm" in df.columns and "map_kpa" in df.columns:
            rpm_labels = [str(b) for b in self.RPM_BINS[:-1]]
            load_labels = [str(b) for b in self.LOAD_BINS[:-1]]
            rpm_cut = pd.cut(df["rpm"].dropna(), bins=self.RPM_BINS, labels=rpm_labels)
            load_cut = pd.cut(df["map_kpa"].dropna(), bins=self.LOAD_BINS, labels=load_labels)
            counts = pd.DataFrame({"rpm": rpm_cut, "load": load_cut}).dropna()
            usage = counts.groupby(["rpm", "load"]).size().to_dict()
            report.cell_usage = {f"{k[0]}rpm_{k[1]}kpa": v for k, v in usage.items()}

        # RPM vs redline check
        if report.rpm_max > 7500:
            report.suggestions.append(
                f"Se alcanzaron {report.rpm_max:.0f} RPM. Verificar que el limitador este configurado correctamente."
            )

        return report
