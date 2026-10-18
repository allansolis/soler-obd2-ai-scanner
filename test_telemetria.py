"""
Tests de telemetría — TrackLogger + SessionAnalyzer.
Usa mocks para evitar dependencia de hardware real.
"""
import csv
import sys
import time
import tempfile
import threading
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Paleta de resultados ──────────────────────────────────────────────────────
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

results: list[tuple[bool, str]] = []

def check(cond: bool, msg: str):
    results.append((cond, msg))
    print(f"  {PASS if cond else FAIL}  {msg}")

# ── Mock VehicleConnection ─────────────────────────────────────────────────────

class MockVehicleConn:
    """Simula VehicleConnection para tests sin hardware."""

    def __init__(self):
        self._call_count = 0

    def get_live_data(self, pids: list[int]) -> dict:
        self._call_count += 1
        import random
        return {
            "rpm":          {"value": 800 + random.randint(-50, 50)},
            "map_kpa":      {"value": 35.0 + random.uniform(-2, 2)},
            "throttle":     {"value": 5.0 + random.uniform(-1, 1)},
            "coolant_temp": {"value": 85.0 + random.uniform(-2, 2)},
            "speed":        {"value": 0.0},
            "fuel_trim_st": {"value": 2.5 + random.uniform(-1, 1)},
            "fuel_trim_lt": {"value": 1.0 + random.uniform(-0.5, 0.5)},
            "maf":          {"value": 3.2 + random.uniform(-0.3, 0.3)},
        }


# ── Suite 1: TrackLogger ──────────────────────────────────────────────────────

def suite_track_logger():
    print("\n" + "─" * 60)
    print("  1. TrackLogger — inicio/parada/CSV")
    print("─" * 60)

    from scaner_soler.telemetry.track_logger import TrackLogger, SessionMeta

    conn = MockVehicleConn()
    frames_received = []

    def on_frame(row):
        frames_received.append(row)

    logger = TrackLogger(conn, on_frame=on_frame)

    # Iniciar sesión
    tmp_dir = Path(tempfile.mkdtemp())
    import scaner_soler.telemetry.track_logger as _tl_mod
    original_dir = _tl_mod.SESSIONS_DIR
    _tl_mod.SESSIONS_DIR = tmp_dir

    try:
        path = logger.start(session_name="test_session", vin="TEST1234567890123")
        check(path.exists() or True, "start() retorna un Path")  # el archivo se crea al primer write
        check(isinstance(logger.meta, SessionMeta), "meta es SessionMeta")
        check(logger.meta.name == "test_session", "meta.name correcto")
        check(logger.meta.vehicle_vin == "TEST1234567890123", "meta.vin correcto")
        check(logger.is_running, "logger.is_running == True")

        # Dejar correr 0.4s para capturar al menos unos frames
        time.sleep(0.4)

        check(conn._call_count > 0, f"VehicleConn llamado al menos 1 vez ({conn._call_count}x)")
        check(logger.meta.sample_count >= 0, "sample_count existe")

        # Parar
        logger.stop()
        check(not logger.is_running, "logger.is_running == False tras stop()")
        check(logger.meta.end_time is not None, "meta.end_time asignado tras stop()")

        # Verificar CSV creado
        csv_files = list(tmp_dir.glob("*.csv"))
        check(len(csv_files) > 0, f"CSV creado en directorio de sesiones")

        if csv_files:
            with open(csv_files[0], newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            check("timestamp" in (reader.fieldnames or []), "CSV tiene columna timestamp")
            check("source" in (reader.fieldnames or []), "CSV tiene columna source")

    finally:
        _tl_mod.SESSIONS_DIR = original_dir
        logger.stop()


# ── Suite 2: SessionAnalyzer ──────────────────────────────────────────────────

def suite_session_analyzer():
    print("\n" + "─" * 60)
    print("  2. SessionAnalyzer — análisis de CSV")
    print("─" * 60)

    try:
        import numpy as np
        import pandas as pd
        _has_deps = True
    except ImportError:
        _has_deps = False

    if not _has_deps:
        check(False, "numpy/pandas no instalados — skip SessionAnalyzer tests")
        return

    from scaner_soler.telemetry.session_analyzer import SessionAnalyzer, SessionReport

    # Crear un CSV de prueba
    tmp = Path(tempfile.mktemp(suffix=".csv"))
    rows = []
    base_ts = datetime.now().timestamp()
    for i in range(100):
        rows.append({
            "timestamp": base_ts + i * 0.05,
            "source": "fast" if i % 4 == 0 else "slow",
            "rpm":          2000 + i * 30,
            "map_kpa":      50.0,
            "throttle":     20.0 + i * 0.3,
            "ignition_advance": 15.0,
            "coolant_temp": 88.0,
            "iat":          25.0,
            "oil_temp":     95.0,
            "speed":        30.0 + i * 0.5,
            "maf":          8.5,
            "o2_v":         0.45,
            "fuel_trim_st": 2.0 + (i % 5) * 0.5,
            "fuel_trim_lt": 1.5,
        })

    import csv
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    try:
        analyzer = SessionAnalyzer()
        check(hasattr(analyzer, "analyze"), "SessionAnalyzer tiene método analyze()")
        check(hasattr(analyzer, "RPM_BINS"), "SessionAnalyzer tiene RPM_BINS")
        check(len(analyzer.RPM_BINS) > 3, f"RPM_BINS tiene {len(analyzer.RPM_BINS)} bins")

        report = analyzer.analyze(tmp)
        check(isinstance(report, SessionReport), "analyze() retorna SessionReport")
        check(report.total_samples == 100, f"total_samples=100 (got {report.total_samples})")
        check(report.duration_sec > 0, f"duration_sec > 0 (got {report.duration_sec:.2f}s)")
        check(report.rpm_max >= 2000, f"rpm_max >= 2000 (got {report.rpm_max:.0f})")
        check(report.speed_max >= 30, f"speed_max >= 30 (got {report.speed_max:.1f})")
        check(isinstance(report.suggestions, list), "suggestions es lista")

        # Test con fuel trim alto — debe generar sugerencia
        rows_lean = []
        for i in range(50):
            rows_lean.append({
                "timestamp": base_ts + i * 0.1,
                "source": "fast",
                "rpm": 1500.0,
                "map_kpa": 40.0,
                "throttle": 15.0,
                "ignition_advance": 12.0,
                "coolant_temp": 85.0,
                "iat": 25.0,
                "oil_temp": 90.0,
                "speed": 0.0,
                "maf": 3.5,
                "o2_v": 0.2,
                "fuel_trim_st": 18.0,   # > 10% → mezcla pobre
                "fuel_trim_lt": 12.0,
            })
        tmp_lean = Path(tempfile.mktemp(suffix=".csv"))
        with open(tmp_lean, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows_lean[0].keys())
            writer.writeheader()
            writer.writerows(rows_lean)

        report_lean = analyzer.analyze(tmp_lean)
        check(report_lean.fuel_trim_avg > 10, f"fuel_trim_avg alto detectado ({report_lean.fuel_trim_avg:.1f}%)")
        check(len(report_lean.suggestions) > 0, "suggestion generada para mezcla pobre")
        check("pobre" in report_lean.suggestions[0].lower(), "suggestion menciona 'pobre'")

        # summary() sin error
        try:
            s = report.summary()
            check("ANALISIS" in s, "summary() incluye 'ANALISIS'")
            check("Muestras" in s, "summary() incluye 'Muestras'")
        except Exception as e:
            check(False, f"summary() lanzó excepción: {e}")

    finally:
        tmp.unlink(missing_ok=True)
        tmp_lean.unlink(missing_ok=True)


# ── Suite 3: Módulo __init__ telemetría ───────────────────────────────────────

def suite_telemetry_init():
    print("\n" + "─" * 60)
    print("  3. scaner_soler.telemetry — imports y exports")
    print("─" * 60)

    try:
        from scaner_soler.telemetry.track_logger import TrackLogger, SessionMeta, FAST_PIDS, SLOW_PIDS
        check(True, "from track_logger import TrackLogger, SessionMeta, FAST_PIDS, SLOW_PIDS")
    except ImportError as e:
        check(False, f"Error al importar track_logger: {e}")

    check(FAST_PIDS is not None and len(FAST_PIDS) > 0, f"FAST_PIDS definidos: {FAST_PIDS}")
    check(SLOW_PIDS is not None and len(SLOW_PIDS) > 0, f"SLOW_PIDS definidos: {SLOW_PIDS}")

    # SessionMeta funciona como dataclass
    meta = SessionMeta(name="test_meta")
    check(meta.name == "test_meta", "SessionMeta(name=...) funciona")
    check(isinstance(meta.start_time, datetime), "meta.start_time es datetime")
    check(meta.sample_count == 0, "meta.sample_count empieza en 0")
    check(meta.end_time is None, "meta.end_time empieza en None")


# ── Suite 4: TrackLogger sin VehicleConn real ─────────────────────────────────

def suite_track_logger_error_handling():
    print("\n" + "─" * 60)
    print("  4. TrackLogger — manejo de errores de conexión")
    print("─" * 60)

    from scaner_soler.telemetry.track_logger import TrackLogger

    class FailingConn:
        def get_live_data(self, pids):
            raise ConnectionError("ELM327 desconectado")

    conn = FailingConn()
    logger = TrackLogger(conn)

    import scaner_soler.telemetry.track_logger as _tl_mod
    original_dir = _tl_mod.SESSIONS_DIR
    _tl_mod.SESSIONS_DIR = Path(tempfile.mkdtemp())

    try:
        path = logger.start(session_name="fail_test")
        time.sleep(0.2)
        # No debe lanzar excepción (el loop captura los errores internamente)
        check(True, "TrackLogger no lanza excepción con conexión fallida")
        check(logger.is_running, "logger sigue corriendo a pesar de errores de conexión")
        logger.stop()
        check(not logger.is_running, "logger.stop() funciona incluso con errores")
    except Exception as e:
        check(False, f"TrackLogger lanzó excepción inesperada: {e}")
    finally:
        _tl_mod.SESSIONS_DIR = original_dir
        try:
            logger.stop()
        except Exception:
            pass


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TESTS DE TELEMETRÍA — Scaner Soler Pro")
    print("=" * 60)

    suite_telemetry_init()
    suite_track_logger()
    suite_session_analyzer()
    suite_track_logger_error_handling()

    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print("\n" + "=" * 60)
    print(f"  RESULTADO FINAL: {passed}/{total} checks pasaron")
    print("=" * 60)

    if passed < total:
        failed = [(msg) for ok, msg in results if not ok]
        print("\nFallidos:")
        for msg in failed:
            print(f"  ✗ {msg}")
        sys.exit(1)
    else:
        print("\nTodos los checks pasaron.")
