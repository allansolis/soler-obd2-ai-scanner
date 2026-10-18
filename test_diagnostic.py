"""
Tests para DiagnosticEngine + DiagnosticReport + DTCDatabase.
Usa mocks de VehicleConnection para evitar hardware real.
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results: list[tuple[bool, str]] = []

def check(cond: bool, msg: str):
    results.append((cond, msg))
    print(f"  {PASS if cond else FAIL}  {msg}")


# ── Mock VehicleConnection ─────────────────────────────────────────────────────

class MockVehicleConn:
    def __init__(self, dtcs=None, live=None):
        self._dtcs = dtcs or []
        self._live = live or {}

    def get_vehicle_info(self) -> dict:
        return {"vin": "WBA3G5108ENS94322", "ecu_name": "Bosch ME17 (mock)"}

    def get_all_dtc(self):
        from scaner_soler.comm.base import DTC
        return [DTC(code=c, category="P", status="confirmed") for c in self._dtcs]

    def get_live_data(self, pids=None) -> dict:
        return self._live or {
            "rpm":          {"value": 850, "unit": "rpm"},
            "coolant_temp": {"value": 88, "unit": "°C"},
            "speed":        {"value": 0, "unit": "km/h"},
            "throttle":     {"value": 3.1, "unit": "%"},
            "fuel_trim_st": {"value": 1.5, "unit": "%"},
        }

    def get_freeze_frame(self, code: str) -> dict:
        return {"rpm": 1200, "throttle": 15.0, "map_kpa": 45.0}

    def live_stream(self, pids=None, hz=10):
        from scaner_soler.comm.base import LiveDataFrame
        for i in range(3):
            yield LiveDataFrame(
                timestamp=datetime.now().timestamp() + i * 0.1,
                values={"rpm": 850 + i * 10},
            )


class FailingConn(MockVehicleConn):
    """Conexión que falla en todos los métodos."""
    def get_vehicle_info(self): raise ConnectionError("ELM desconectado")
    def get_all_dtc(self): raise ConnectionError("ELM desconectado")
    def get_live_data(self, pids=None): raise ConnectionError("ELM desconectado")
    def get_freeze_frame(self, code): raise ConnectionError("ELM desconectado")


# ── Suite 1: DiagnosticReport ──────────────────────────────────────────────────

def suite_report():
    print("\n" + "─" * 60)
    print("  1. DiagnosticReport — propiedades y summary()")
    print("─" * 60)

    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticReport
    from scaner_soler.comm.base import DTC

    report = DiagnosticReport(vin="TEST123", ecu_name="Bosch ME17")
    check(report.vin == "TEST123", "DiagnosticReport(vin=...) OK")
    check(isinstance(report.timestamp, datetime), "timestamp es datetime")
    check(report.has_critical == False, "has_critical=False sin DTCs")
    check(report.confirmed_dtcs == [], "confirmed_dtcs vacío")
    check(report.pending_dtcs == [], "pending_dtcs vacío")

    # Agregar DTCs
    report.dtcs = [
        DTC(code="P0300", category="P", status="confirmed", severity="critical", description="Fallo encendido"),
        DTC(code="P0171", category="P", status="pending",   severity="warning",  description="Mezcla pobre"),
    ]
    check(report.has_critical == True, "has_critical=True con DTC crítico")
    check(len(report.confirmed_dtcs) == 1, f"confirmed_dtcs=1: {[d.code for d in report.confirmed_dtcs]}")
    check(len(report.pending_dtcs) == 1, f"pending_dtcs=1: {[d.code for d in report.pending_dtcs]}")

    # summary()
    s = report.summary()
    check("REPORTE" in s, "summary() contiene 'REPORTE'")
    check("P0300" in s, "summary() contiene 'P0300'")
    check("P0171" in s, "summary() contiene 'P0171'")
    check("TEST123" in s, "summary() contiene VIN")


# ── Suite 2: DiagnosticEngine — full_scan ─────────────────────────────────────

def suite_full_scan():
    print("\n" + "─" * 60)
    print("  2. DiagnosticEngine — full_scan() con mock")
    print("─" * 60)

    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine, DiagnosticReport

    conn = MockVehicleConn(dtcs=["P0300", "P0171"])
    engine = DiagnosticEngine(conn)

    check(hasattr(engine, "full_scan"), "DiagnosticEngine tiene full_scan()")
    check(hasattr(engine, "quick_health_check"), "DiagnosticEngine tiene quick_health_check()")
    check(hasattr(engine, "live_monitor"), "DiagnosticEngine tiene live_monitor()")

    report = engine.full_scan()
    check(isinstance(report, DiagnosticReport), "full_scan() retorna DiagnosticReport")
    check(report.vin == "WBA3G5108ENS94322", f"vin leído del mock: {report.vin}")
    check(len(report.dtcs) == 2, f"dtcs=2: {[d.code for d in report.dtcs]}")
    check("P0300" in [d.code for d in report.dtcs], "P0300 en dtcs")
    check(len(report.live_data) > 0, f"live_data tiene {len(report.live_data)} entradas")
    check(len(report.freeze_frames) > 0, f"freeze_frames capturados: {list(report.freeze_frames.keys())}")


# ── Suite 3: full_scan() con conexión fallida ──────────────────────────────────

def suite_error_handling():
    print("\n" + "─" * 60)
    print("  3. DiagnosticEngine — manejo de errores de conexión")
    print("─" * 60)

    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    engine = DiagnosticEngine(FailingConn())
    try:
        report = engine.full_scan()
        check(True, "full_scan() no lanza excepción con conexión fallida")
        check(report is not None, "full_scan() retorna DiagnosticReport incluso con errores")
        check("_scan_errors" in report.vehicle_info,
              "vehicle_info tiene '_scan_errors' cuando hay fallos")
    except Exception as e:
        check(False, f"full_scan() lanzó excepción inesperada: {e}")


# ── Suite 4: quick_health_check ────────────────────────────────────────────────

def suite_health_check():
    print("\n" + "─" * 60)
    print("  4. DiagnosticEngine — quick_health_check()")
    print("─" * 60)

    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine
    from scaner_soler.comm.base import DTC

    # Sin DTCs
    engine = DiagnosticEngine(MockVehicleConn())
    result = engine.quick_health_check()
    check(isinstance(result, dict), "quick_health_check() retorna dict")
    check("status" in result, "resultado tiene campo 'status'")
    check("dtcs" in result, "resultado tiene campo 'dtcs'")
    check("live" in result, "resultado tiene campo 'live'")
    check(result["status"] == "OK", f"status=OK sin DTCs: {result['status']}")

    # Con DTC crítico
    class CriticalConn(MockVehicleConn):
        def get_all_dtc(self):
            from scaner_soler.comm.base import DTC
            return [DTC(code="P0300", category="P", status="confirmed", severity="critical")]
    engine2 = DiagnosticEngine(CriticalConn())
    result2 = engine2.quick_health_check()
    check(result2["status"] == "CRITICAL", f"status=CRITICAL con DTC crítico: {result2['status']}")


# ── Suite 5: DTCDatabase ───────────────────────────────────────────────────────

def suite_dtc_database():
    print("\n" + "─" * 60)
    print("  5. DTCDatabase — lookup y search")
    print("─" * 60)

    from scaner_soler.diagnostic.dtc_database import DTCDatabase

    db = DTCDatabase()
    check(hasattr(db, "lookup"), "DTCDatabase tiene lookup()")
    check(hasattr(db, "search") or hasattr(db, "query"), "DTCDatabase tiene search()/query()")

    # lookup código conocido
    info = db.lookup("P0300")
    check(isinstance(info, dict), f"lookup('P0300') retorna dict: {type(info).__name__}")
    if info:
        check("description" in info or "code" in info,
              f"info tiene campos esperados: {list(info.keys())[:5]}")


# ── Suite 6: live_monitor generator ───────────────────────────────────────────

def suite_live_monitor():
    print("\n" + "─" * 60)
    print("  6. DiagnosticEngine — live_monitor() generator")
    print("─" * 60)

    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    engine = DiagnosticEngine(MockVehicleConn())
    frames = list(engine.live_monitor())
    check(len(frames) == 3, f"live_monitor() yields 3 frames del mock: {len(frames)}")
    if frames:
        check(hasattr(frames[0], "values") or isinstance(frames[0], dict),
              f"frame es LiveDataFrame o dict: {type(frames[0]).__name__}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TESTS DIAGNÓSTICO — Scaner Soler Pro")
    print("=" * 60)

    suite_report()
    suite_full_scan()
    suite_error_handling()
    suite_health_check()
    suite_dtc_database()
    suite_live_monitor()

    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print("\n" + "=" * 60)
    print(f"  RESULTADO FINAL: {passed}/{total} checks pasaron")
    print("=" * 60)

    if passed < total:
        failed = [msg for ok, msg in results if not ok]
        print("\nFallidos:")
        for msg in failed:
            print(f"  ✗ {msg}")
        sys.exit(1)
    else:
        print("\nTodos los checks pasaron.")
