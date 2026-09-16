import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..comm.vehicle_conn import VehicleConnection
from ..comm.base import DTC, LiveDataFrame
from .dtc_database import DTCDatabase


@dataclass
class DiagnosticReport:
    timestamp: datetime = field(default_factory=datetime.now)
    vin: str = ""
    ecu_name: str = ""
    dtcs: list[DTC] = field(default_factory=list)
    live_data: dict = field(default_factory=dict)
    freeze_frames: dict = field(default_factory=dict)   # {dtc_code: freeze_frame}
    vehicle_info: dict = field(default_factory=dict)

    @property
    def has_critical(self) -> bool:
        return any(d.severity == "critical" for d in self.dtcs)

    @property
    def confirmed_dtcs(self) -> list[DTC]:
        return [d for d in self.dtcs if d.status == "confirmed"]

    @property
    def pending_dtcs(self) -> list[DTC]:
        return [d for d in self.dtcs if d.status == "pending"]

    def summary(self) -> str:
        lines = [
            f"=== REPORTE DE DIAGNOSTICO ===",
            f"Fecha:   {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"VIN:     {self.vin or 'N/D'}",
            f"ECU:     {self.ecu_name or 'N/D'}",
            f"",
            f"DTCs activos: {len(self.confirmed_dtcs)}  |  Pendientes: {len(self.pending_dtcs)}",
        ]
        for d in self.dtcs:
            mark = "!" if d.severity == "critical" else "~"
            lines.append(f"  [{mark}] {d.code} — {d.description} ({d.status})")
        if not self.dtcs:
            lines.append("  Sin codigos de falla.")
        if self.live_data:
            lines.append("")
            lines.append("DATOS EN VIVO:")
            for k, v in list(self.live_data.items())[:12]:
                val = v.get("value")
                unit = v.get("unit", "")
                lines.append(f"  {k:<25} {val} {unit}")
        return "\n".join(lines)


class DiagnosticEngine:

    def __init__(self, conn: VehicleConnection, dtc_db: Optional[DTCDatabase] = None):
        self.conn = conn
        self.dtc_db = dtc_db or DTCDatabase()

    def full_scan(self) -> DiagnosticReport:
        report = DiagnosticReport()

        try:
            report.vehicle_info = self.conn.get_vehicle_info()
            report.vin = report.vehicle_info.get("vin", "")
            report.ecu_name = report.vehicle_info.get("ecu_name", "")
        except Exception:
            pass

        try:
            raw_dtcs = self.conn.get_all_dtc()
            report.dtcs = self._enrich_dtcs(raw_dtcs)
        except Exception:
            pass

        try:
            report.live_data = self.conn.get_live_data()
        except Exception:
            pass

        try:
            for dtc in report.confirmed_dtcs[:5]:
                ff = self.conn.get_freeze_frame(dtc.code)
                if ff:
                    report.freeze_frames[dtc.code] = ff
        except Exception:
            pass

        return report

    def _enrich_dtcs(self, dtcs: list[DTC]) -> list[DTC]:
        enriched = []
        for dtc in dtcs:
            info = self.dtc_db.lookup(dtc.code)
            dtc.description = info.get("description", dtc.description)
            dtc.system = info.get("system", dtc.system)
            dtc.severity = info.get("severity", dtc.severity)
            dtc.suggested_action = info.get("suggested_action", dtc.suggested_action)
            enriched.append(dtc)
        return enriched

    def live_monitor(self, pids: list[int] | None = None, hz: int = 10):
        """Yields LiveDataFrame at `hz` rate until connection drops."""
        yield from self.conn.live_stream(pids=pids, hz=hz)

    def quick_health_check(self) -> dict:
        """Fast check: DTCs + key live values. No freeze frames."""
        result = {"dtcs": [], "live": {}, "status": "OK"}
        try:
            result["dtcs"] = self._enrich_dtcs(self.conn.get_all_dtc())
        except Exception as e:
            result["dtc_error"] = str(e)
        try:
            live = self.conn.get_live_data([0x05, 0x0C, 0x0D, 0x11, 0x5C])
            result["live"] = {k: v["value"] for k, v in live.items()}
        except Exception as e:
            result["live_error"] = str(e)
        if any(d.severity == "critical" for d in result["dtcs"]):
            result["status"] = "CRITICAL"
        elif result["dtcs"]:
            result["status"] = "WARNING"
        return result
