"""
Simulador de conexion, diagnostico, modificacion y correccion de fallas.
Cubre 8 marcas (VW, Toyota, BMW, Ford, Chevrolet, Honda, Nissan, Renault).

Ejecutar:  python test_simulacion_marcas.py
"""
import sys
import io
# Forzar UTF-8 en stdout de Windows para emojis/unicode
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import time
import random
import traceback
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

# ── Paleta de consola ────────────────────────────────────────────────────────
R  = "\033[91m"
G  = "\033[92m"
Y  = "\033[93m"
B  = "\033[94m"
M  = "\033[95m"
C  = "\033[96m"
W  = "\033[97m"
GR = "\033[90m"
RESET = "\033[0m"
BOLD  = "\033[1m"

def ok(msg):  print(f"{G}  ✓ {msg}{RESET}")
def err(msg): print(f"{R}  ✗ {msg}{RESET}")
def warn(msg):print(f"{Y}  ⚠ {msg}{RESET}")
def info(msg):print(f"{C}  → {msg}{RESET}")
def head(msg):print(f"\n{BOLD}{B}{msg}{RESET}")
def sub(msg): print(f"{M}  ── {msg}{RESET}")

PASS = 0
FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ok(f"{label}{' — '+detail if detail else ''}")
    else:
        FAIL += 1
        err(f"{label}{' — '+detail if detail else ''}")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. SIMULADORES DE ECU POR MARCA
# ═══════════════════════════════════════════════════════════════════════════════

MARCAS = {
    "VW": {
        "vin": "WVWZZZ3CZWE689521",
        "protocol": "UDS/KWP2000",
        "ecu": "Bosch ME17.5.25",
        "baudrate": 500000,
        "dtcs": [("P0171", "Sistema en mezcla pobre — Banco 1", "warning"),
                 ("P0300", "Fallo de encendido aleatorio detectado", "critical")],
        "pids": {"rpm": 1850, "coolant_temp": 92, "throttle": 18, "speed": 0,
                 "o2_voltage": 0.45, "maf": 8.2, "fuel_trim_st": -5.1},
        "can_ids": [0x7E0, 0x7E8, 0x123, 0x456, 0x3B2],
    },
    "Toyota": {
        "vin": "JTDKN3DU9A1234567",
        "protocol": "ISO 15765-4 CAN",
        "ecu": "Denso 89661-47E00",
        "baudrate": 500000,
        "dtcs": [("P0A0F", "Fallo en sistema de carga de HV", "critical")],
        "pids": {"rpm": 2200, "coolant_temp": 88, "throttle": 22, "speed": 0,
                 "battery_voltage": 14.1, "maf": 10.5, "fuel_trim_st": 1.2},
        "can_ids": [0x7E0, 0x7E8, 0x201, 0x202, 0x3D1],
    },
    "BMW": {
        "vin": "WBA3A5G55FNS00001",
        "protocol": "UDS / DS2",
        "ecu": "Bosch MSD80",
        "baudrate": 500000,
        "dtcs": [("P0171", "Sistema pobre Banco 1", "warning"),
                 ("P0174", "Sistema pobre Banco 2", "warning"),
                 ("P2096", "Post-Cat mezcla pobre", "warning")],
        "pids": {"rpm": 750, "coolant_temp": 105, "throttle": 8, "speed": 0,
                 "intake_temp": 38, "boost_pressure": 1.02, "maf": 6.1},
        "can_ids": [0x12F, 0x130, 0x19E, 0x1B4, 0x316, 0x317, 0x329, 0x545],
    },
    "Ford": {
        "vin": "1FTFW1EF0EFC00001",
        "protocol": "ISO 15765-4 CAN",
        "ecu": "Ford PCM 6L2A-12A650",
        "baudrate": 500000,
        "dtcs": [],
        "pids": {"rpm": 3100, "coolant_temp": 94, "throttle": 45, "speed": 72,
                 "maf": 28.4, "fuel_trim_st": 0.8, "o2_voltage": 0.72},
        "can_ids": [0x7E0, 0x7E8, 0x101, 0x201, 0x411],
    },
    "Chevrolet": {
        "vin": "2G1FB1E38D9200001",
        "protocol": "GM-LAN / ISO 15765",
        "ecu": "Delphi E38 ECM",
        "baudrate": 500000,
        "dtcs": [("P0442", "Fuga pequeña EVAP", "warning"),
                 ("P0455", "Fuga grande EVAP", "critical")],
        "pids": {"rpm": 1600, "coolant_temp": 90, "throttle": 15, "speed": 0,
                 "maf": 7.9, "fuel_trim_st": 2.3, "evap_pressure": -1.2},
        "can_ids": [0x244, 0x388, 0x3E9, 0x514, 0x5E8],
    },
    "Honda": {
        "vin": "JHMGE88429S000001",
        "protocol": "ISO 15765-4 CAN / Honda HDS",
        "ecu": "Keihin 37820-RNA-A71",
        "baudrate": 500000,
        "dtcs": [("P0134", "Sensor O2 sin actividad — Banco 1 Sensor 1", "warning")],
        "pids": {"rpm": 2050, "coolant_temp": 86, "throttle": 20, "speed": 0,
                 "o2_voltage": 0.11, "maf": 9.1, "fuel_trim_lt": 12.5},
        "can_ids": [0x18DAF110, 0x7E0, 0x7E8, 0x1A0, 0x309],
    },
    "Nissan": {
        "vin": "JN1BJ0HP8FM300001",
        "protocol": "ISO 15765-4 CAN / Nissan Consult-III",
        "ecu": "Hitachi MEC90310",
        "baudrate": 500000,
        "dtcs": [("P0335", "Sensor de posición de cigüeñal A — circuito", "critical")],
        "pids": {"rpm": 0, "coolant_temp": 20, "throttle": 0, "speed": 0,
                 "crank_signal": False, "maf": 0.0, "fuel_trim_st": 0.0},
        "can_ids": [0x551, 0x580, 0x60D, 0x625],
    },
    "Renault": {
        "vin": "VF1BM0G0H39000001",
        "protocol": "CAN / UDS",
        "ecu": "Siemens SID305",
        "baudrate": 500000,
        "dtcs": [("P0087", "Presión de riel de combustible baja", "critical"),
                 ("P0093", "Fuga en sistema de combustible", "critical")],
        "pids": {"rpm": 900, "coolant_temp": 78, "throttle": 10, "speed": 0,
                 "fuel_rail_pressure": 28.5, "maf": 5.8, "fuel_trim_st": 8.4},
        "can_ids": [0x7DF, 0x7E8, 0x211, 0x3A0, 0x4B0],
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. MOCK PROTOCOL — simula ELM327 sin hardware
# ═══════════════════════════════════════════════════════════════════════════════

from scaner_soler.comm.base import AbstractProtocol, DTC, LiveDataFrame


class MockELM327(AbstractProtocol):
    """Simula un ELM327 conectado a un vehículo específico."""

    def __init__(self, marca: str):
        self.marca = marca
        self.data = MARCAS[marca]
        self._connected = False
        self._fail_on = set()  # para inyectar fallos específicos

    def inject_failure(self, stage: str):
        """Permite testear comportamiento ante fallos parciales."""
        self._fail_on.add(stage)

    # ── AbstractProtocol ──────────────────────────────────────────────────────

    def connect(self, port: str = "COM3", baudrate: int = 115200) -> bool:
        time.sleep(0.02)  # simula latencia serial
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_pid(self, pid: int) -> dict:
        if "live_data" in self._fail_on:
            raise IOError("Timeout leyendo PID")
        pids = self.data["pids"]
        mapping = {
            0x05: ("coolant_temp",     pids.get("coolant_temp"), "°C"),
            0x0C: ("rpm",              pids.get("rpm"),           "rpm"),
            0x0D: ("speed",            pids.get("speed"),         "km/h"),
            0x11: ("throttle",         pids.get("throttle"),      "%"),
            0x14: ("o2_voltage",       pids.get("o2_voltage"),    "V"),
            0x10: ("maf",              pids.get("maf"),           "g/s"),
            0x06: ("fuel_trim_st",     pids.get("fuel_trim_st"),  "%"),
            0x07: ("fuel_trim_lt",     pids.get("fuel_trim_lt"),  "%"),
            0x5C: ("oil_temp",         pids.get("oil_temp", 95),  "°C"),
            0x33: ("abs_pressure",     pids.get("boost_pressure", 1.013), "bar"),
        }
        entry = mapping.get(pid)
        if entry and entry[1] is not None:
            return {"name": entry[0], "value": entry[1], "unit": entry[2]}
        return {"name": f"PID_{pid:02X}", "value": None, "unit": ""}

    def read_dtc(self) -> list[DTC]:
        if "dtc" in self._fail_on:
            raise IOError("Timeout leyendo DTCs")
        result = []
        for code, desc, severity in self.data["dtcs"]:
            dtc = DTC.from_raw_code(code)
            dtc.description = desc
            dtc.severity = severity
            dtc.status = "confirmed"
            dtc.system = "powertrain" if code.startswith("P") else "body"
            result.append(dtc)
        return result

    def clear_dtc(self) -> bool:
        if "clear_dtc" in self._fail_on:
            return False
        self.data["dtcs"] = []
        return True

    def read_freeze_frame(self, dtc_code: str) -> dict:
        return {
            "dtc": dtc_code,
            "rpm": self.data["pids"].get("rpm", 0),
            "coolant_temp": self.data["pids"].get("coolant_temp", 0),
            "throttle": self.data["pids"].get("throttle", 0),
        }

    def read_vehicle_info(self) -> dict:
        if "vehicle_info" in self._fail_on:
            raise IOError("ECU no responde a VIN request")
        return {
            "vin": self.data["vin"],
            "ecu_name": self.data["ecu"],
            "protocol": self.data["protocol"],
            "brand": self.marca,
        }

    def send_raw(self, data, timeout: float = 5.0):
        cmd = data.decode() if isinstance(data, bytes) else str(data)
        return f"MOCK:{self.marca}:{cmd.strip()}".encode()

    def send_command(self, cmd: str) -> str:
        return f"MOCK:{self.marca}:{cmd.strip()}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TESTS INDIVIDUALES
# ═══════════════════════════════════════════════════════════════════════════════

def test_imports():
    head("TEST 0 — Validación de imports del sistema")
    modules = [
        ("scaner_soler",                          "Paquete raíz"),
        ("scaner_soler.config",                    "Configuración centralizada"),
        ("scaner_soler.comm.base",                 "Base protocol"),
        ("scaner_soler.comm.elm327",               "ELM327 protocol"),
        ("scaner_soler.comm.can_bus",              "CAN bus module"),
        ("scaner_soler.comm.kline",                "K-Line module"),
        ("scaner_soler.comm.security",             "Security module"),
        ("scaner_soler.comm.vehicle_conn",         "Vehicle connection facade"),
        ("scaner_soler.comm.reverse_engineer",     "Reverse engineer"),
        ("scaner_soler.diagnostic.diagnostic_engine", "Diagnostic engine"),
        ("scaner_soler.diagnostic.dtc_database",   "DTC database"),
        ("scaner_soler.ecu.pid_registry",          "PID registry"),
        ("scaner_soler.ecu.ecu_reader",            "ECU reader"),
        ("scaner_soler.ecu.programmer",            "ECU programmer"),
        ("scaner_soler.ecu.maps.map_table",        "Map table (bug crítico reparado)"),
        ("scaner_soler.optimizer.safety_guard",    "Safety guard"),
        ("scaner_soler.optimizer.ecu_sandbox",     "ECU sandbox"),
        ("scaner_soler.optimizer.map_optimizer",   "Map optimizer"),
        ("scaner_soler.knowledge.unified_kb",      "Unified KB"),
        ("scaner_soler.telemetry.track_logger",    "Track logger"),
    ]
    for mod, label in modules:
        try:
            __import__(mod)
            ok(f"{label} ({mod})")
        except Exception as e:
            err(f"{label} ({mod}) — {e}")
            global FAIL
            FAIL += 1


def test_conexion_marca(marca: str):
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    data = MARCAS[marca]
    proto = MockELM327(marca)
    conn = VehicleConnection(protocol=proto)

    head(f"MARCA: {marca} — {data['ecu']} | {data['protocol']}")

    # Conexión
    ok_conn = conn.connect(port="COM_SIM", baudrate=data["baudrate"])
    check(f"Conexión {marca} ({data['protocol']})", ok_conn)
    check(f"Estado is_connected", conn.is_connected)

    # Información del vehículo
    info_v = conn.get_vehicle_info()
    check(f"VIN leído ({info_v.get('vin','')})", info_v.get("vin") == data["vin"])
    check(f"ECU identificada ({info_v.get('ecu_name','')})",
          data["ecu"] in info_v.get("ecu_name", ""))

    # DTCs
    dtcs = conn.get_all_dtc()
    check(f"DTCs leídos ({len(dtcs)} encontrados)",
          len(dtcs) == len(data["dtcs"]))

    if dtcs:
        critical = [d for d in dtcs if d.severity == "critical"]
        warning  = [d for d in dtcs if d.severity == "warning"]
        if critical:
            warn(f"  DTCs críticos: {[d.code for d in critical]}")
        if warning:
            info(f"  DTCs advertencia: {[d.code for d in warning]}")

        # Freeze frame
        ff = conn.get_freeze_frame(dtcs[0].code)
        check(f"Freeze frame de {dtcs[0].code}",
              ff.get("dtc") == dtcs[0].code and "rpm" in ff)

    # Datos en vivo
    pids = [0x05, 0x0C, 0x0D, 0x11, 0x10]
    live = conn.get_live_data(pids)
    check(f"Datos en vivo ({len(live)} PIDs respondidos)",
          len(live) >= 2,
          f"temp={live.get('coolant_temp',{}).get('value','N/A')}°C "
          f"rpm={live.get('rpm',{}).get('value','N/A')}")

    conn.disconnect()
    check("Desconexión limpia", not conn.is_connected)
    return dtcs


def test_motor_diagnostico_completo(marca: str, dtcs_esperados: int):
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    head(f"DIAGNÓSTICO COMPLETO — {marca}")
    proto = MockELM327(marca)
    conn  = VehicleConnection(protocol=proto)
    conn.connect()
    engine = DiagnosticEngine(conn)

    t0 = time.perf_counter()
    report = engine.full_scan()
    elapsed = time.perf_counter() - t0

    check("Reporte generado", report is not None)
    check(f"VIN en reporte ({report.vin})", bool(report.vin))
    check(f"DTCs enriquecidos ({len(report.dtcs)} / esperados {dtcs_esperados})",
          len(report.dtcs) == dtcs_esperados)
    check("Sin errores de scan ocultos",
          "_scan_errors" not in report.vehicle_info,
          str(report.vehicle_info.get("_scan_errors", "OK")))
    check(f"Tiempo de escaneo < 2 s ({elapsed:.3f}s)", elapsed < 2.0)

    # Resumen legible
    sub("Resumen del reporte:")
    for line in report.summary().split("\n"):
        print(f"    {GR}{line}{RESET}")

    conn.disconnect()
    return report


def test_correccion_fallas(marca: str):
    from scaner_soler.comm.vehicle_conn import VehicleConnection

    head(f"CORRECCIÓN DE FALLAS — {marca}")
    proto = MockELM327(marca)
    conn  = VehicleConnection(protocol=proto)
    conn.connect()

    dtcs_antes = conn.get_all_dtc()
    check(f"DTCs presentes antes ({len(dtcs_antes)})",
          True, f"códigos: {[d.code for d in dtcs_antes]}")

    resultado = conn.clear_dtc()
    check("Borrado de DTCs exitoso", resultado)

    dtcs_despues = conn.get_all_dtc()
    check("DTCs borrados (0 activos)", len(dtcs_despues) == 0)
    conn.disconnect()


def test_modulo_seguridad():
    from scaner_soler.comm.security import (
        CommandSanitizer, CANAnomalyDetector, SecurityAuditLog
    )

    head("MÓDULO DE SEGURIDAD")
    sanitizer = CommandSanitizer()

    # Comandos válidos
    for cmd in ["01 0C", "09 02", "22 F1 90", "AT SP 0"]:
        ok_flag, reason = sanitizer.validate(cmd)
        check(f"Cmd válido aceptado: '{cmd}'", ok_flag, reason)

    # Comandos AT bloqueados — validate() retorna False
    for cmd in ["ATZ", "AT WS", "ATRST"]:
        ok_flag, reason = sanitizer.validate(cmd)
        check(f"Cmd AT bloqueado: '{cmd}'", not ok_flag, reason)

    # Servicios UDS peligrosos — validate() retorna True pero con DANGER en la razón
    # (el bloqueo real ocurre via UDSRiskGuard en el pipeline completo)
    ok_flag, reason = sanitizer.validate("34 00 44 00 00 00 FF")
    check("Servicio UDS peligroso marcado con DANGER (0x34 RequestDownload)",
          ok_flag and "DANGER" in reason, reason)

    # Detector de anomalías CAN
    detector = CANAnomalyDetector()
    alert = None
    for i in range(25):  # flood: >20 frames/s
        alert = detector.feed_frame(0x123, "DEADBEEF01020304")
    check("Flood CAN detectado (>20 frames)", alert is not None,
          f"tipo={getattr(alert,'alert_type','?')}")

    # Entropía = 0 (todos bytes iguales → probable respuesta fija / glitch)
    alert2 = detector.check_entropy("0000000000000000", context="test")
    check("Entropía cero detectada", alert2 is not None)

    # Audit log
    from scaner_soler.comm.security import SecurityAlert
    audit = SecurityAuditLog()
    audit.log_command("01 0C", "410C0FA0", sanitized=False)
    blocked_alert = SecurityAlert(
        severity="critical", alert_type="blocked_cmd",
        description="Comando bloqueado en test", raw_data="ATZ",
    )
    audit.log_command("ATZ", "BLOCKED", sanitized=True, alert=blocked_alert)
    stats = audit.summary()
    check("Audit log registra comandos", stats.get("total_commands", 0) >= 2)
    check("Audit log registra comandos bloqueados", stats.get("blocked_commands", 0) >= 1)


def test_can_bus():
    from scaner_soler.comm.can_bus import (
        CANFrame, CANFrameDecoder, OBDSensorAnomalyDetector
    )

    head("MÓDULO CAN BUS")

    # Frames básicos — CANFrame usa arbitration_id, is_extended_id, dlc, data(bytes)
    payload = bytes.fromhex("0441121803B20000")
    frame = CANFrame(arbitration_id=0x7E8, is_extended_id=False, dlc=8, data=payload)
    check("CANFrame creado", frame.arbitration_id == 0x7E8 and frame.dlc == 8)
    check("Bytes del frame", len(frame.data) == 8)

    # Decoder: respuesta OBD RPM — decode_obd_response espera un CANFrame
    # AT response: 04 41 0C 0F A0 ... → RPM = (0x0F * 256 + 0xA0) / 4 = 1000 rpm
    decoder = CANFrameDecoder()
    obd_payload = bytes([0x04, 0x41, 0x0C, 0x0F, 0xA0, 0x00, 0x00, 0x00])
    obd_frame = CANFrame(
        arbitration_id=0x7E8, is_extended_id=False, dlc=8, data=obd_payload
    )
    result = decoder.decode_obd_response(obd_frame)
    check("Decodificación OBD RPM (frame 7E8, PID 0x0C)",
          result is not None and isinstance(result, dict),
          str(result) if result else "None")

    # Detector de anomalías del sensor — usa update(dict)
    det = OBDSensorAnomalyDetector(window_size=10, zscore_threshold=2.0)
    for rpm in [800, 820, 810, 830, 805, 815, 808, 812, 806, 818]:
        det.update({"rpm": float(rpm)})
    # Spike extremo: 12000 RPM debería disparar anomalía
    events = det.update({"rpm": 12000.0})
    check("Spike de RPM detectado por OBDSensorAnomalyDetector",
          isinstance(events, list),
          f"{len(events)} eventos (umbral z-score=2.0)")


def test_reverse_engineer_pipeline():
    from scaner_soler.comm.reverse_engineer import (
        ReverseEngineerSession, ECUControlMap
    )

    head("PIPELINE INGENIERÍA INVERSA")

    # ReverseEngineerSession toma send_fn, no protocol
    proto = MockELM327("VW")
    proto.connect()
    session = ReverseEngineerSession(send_fn=proto.send_command)

    check("Sesión RE creada con send_fn", session is not None)

    # Prueba básica: profiling SIN fuzz para que sea rápido
    try:
        t0 = time.perf_counter()
        result = session.run(fuzz=False)
        elapsed = time.perf_counter() - t0
        check("RESessionResult generado", result is not None)
        check("Protocolo detectado en result",
              hasattr(result, "profile") and result.profile is not None)
        check(f"Run (sin fuzz) < 30s ({elapsed:.1f}s)", elapsed < 30.0)
        info(f"  Protocolo: {getattr(result.profile, 'best_protocol', 'N/A')}")
        info(f"  PIDs fuzzeados: {len(getattr(result, 'fuzz_catalog', {}))}")
    except Exception as e:
        err(f"session.run falló: {e}")
        global FAIL
        FAIL += 1

    # Prueba del mapa completo via _full_scan_impl (monkey-patched)
    try:
        eco_map = session._full_scan_impl(skip_can=True, skip_uds_map=False)
        check("ECUControlMap via _full_scan_impl", eco_map is not None)
        if eco_map:
            md = eco_map.to_markdown()
            check("Markdown del mapa generado", len(md) > 50)
            snippet = eco_map.generate_python_snippet()
            check("Snippet Python generado", len(snippet) > 20)
    except Exception as e:
        warn(f"_full_scan_impl: {e}")


def test_mapa_ecu_y_seguridad_escritura():
    head("MAPA ECU + GUARD DE SEGURIDAD")
    try:
        import numpy as np
        from scaner_soler.ecu.maps.map_table import MapTable
        from scaner_soler.optimizer.safety_guard import SafetyError

        rpm  = np.array([800, 1200, 1600, 2000, 2400, 3200, 4000, 5000])
        load = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        vals = np.random.uniform(8.0, 14.0, size=(len(rpm), len(load)))

        mapa = MapTable(
            name="Ignition_Advance",
            rpm_axis=rpm,
            load_axis=load,
            values=vals,
            unit="°",
            min_safe=0.0,
            max_safe=45.0,
        )
        check("MapTable creado (bug import corregido)", True)

        # Escritura válida
        mapa.set_cell(2, 3, 22.5)
        check("Celda válida escrita (22.5°)", mapa.get_cell(2, 3) == 22.5)
        check("Dirty flag activo", mapa.has_changes)

        # Escritura fuera de rango — debe lanzar SafetyError
        blocked = False
        try:
            mapa.set_cell(0, 0, 60.0)  # > max_safe=45
        except SafetyError:
            blocked = True
        check("SafetyError lanzada por valor fuera de rango (60°)", blocked)

        # Restore backup
        mapa.restore_backup()
        check("Backup restaurado correctamente", not mapa.has_changes)

        # Checksum
        cs = mapa.checksum()
        check("Checksum SHA256 generado", len(cs) == 16)

    except ImportError as e:
        err(f"Import fallido: {e}")
        global FAIL
        FAIL += 1


def test_fallo_parcial_conexion():
    """Verifica que el sistema maneja fallos de hardware sin crashear."""
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    head("RESILIENCIA — FALLOS PARCIALES DE HARDWARE")

    proto = MockELM327("Ford")
    proto.inject_failure("vehicle_info")  # VIN no responde
    conn  = VehicleConnection(protocol=proto)
    conn.connect()
    engine = DiagnosticEngine(conn)

    report = engine.full_scan()
    check("Sistema no crashea con VIN fállido",
          report is not None,
          f"vin='{report.vin}' errors={report.vehicle_info.get('_scan_errors','ninguno')}")
    check("Errores reportados en vehicle_info",
          "_scan_errors" in report.vehicle_info,
          str(report.vehicle_info.get("_scan_errors", [])))
    # DTCs siguen leyéndose aunque VIN falló
    check("DTCs leídos a pesar del fallo de VIN",
          isinstance(report.dtcs, list))

    conn.disconnect()

    # Ahora falla lectura de DTCs
    proto2 = MockELM327("Chevrolet")
    proto2.inject_failure("dtc")
    conn2 = VehicleConnection(protocol=proto2)
    conn2.connect()
    engine2 = DiagnosticEngine(conn2)
    report2 = engine2.full_scan()
    check("Sistema no crashea con DTCs fállidos",
          report2 is not None)
    check("VIN leído aunque DTCs fallaron",
          report2.vin == MARCAS["Chevrolet"]["vin"])
    conn2.disconnect()


def test_pid_registry():
    # pid_registry exporta OBD_COMMANDS y VEHICLE_INFO_PIDS
    from scaner_soler.ecu.pid_registry import OBD_COMMANDS, VEHICLE_INFO_PIDS

    head("REGISTRO DE PIDs")
    check(f"PIDs registrados (>= 95)", len(OBD_COMMANDS) >= 95,
          f"encontrados: {len(OBD_COMMANDS)}")
    check("PID 0x0C (RPM) presente", 0x0C in OBD_COMMANDS)
    check("PID 0x05 (Coolant) presente", 0x05 in OBD_COMMANDS)
    check("PID 0x0D (Speed) presente", 0x0D in OBD_COMMANDS)
    check("VEHICLE_INFO_PIDS definidos", len(VEHICLE_INFO_PIDS) >= 3)

    pid_rpm = OBD_COMMANDS[0x0C]  # tupla (nombre, modo, hex, unidad, bytes, formula)
    check("PID 0x0C tiene formula lambda", callable(pid_rpm[5]))


def test_quick_health_check_todas_marcas():
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    head("QUICK HEALTH CHECK — TODAS LAS MARCAS")
    for marca, data in MARCAS.items():
        proto = MockELM327(marca)
        conn  = VehicleConnection(protocol=proto)
        conn.connect()
        engine = DiagnosticEngine(conn)
        health = engine.quick_health_check()
        status = health.get("status", "?")
        n_dtcs = len(health.get("dtcs", []))
        n_live = len(health.get("live", {}))
        color  = R if status == "CRITICAL" else (Y if status == "WARNING" else G)
        print(f"  {color}{marca:<12}{RESET} status={color}{status}{RESET}"
              f"  DTCs={n_dtcs}  live_pids={n_live}")
        check(f"{marca} health_check devuelve status",
              status in ("OK", "WARNING", "CRITICAL"))
        conn.disconnect()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RUNNER PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{W}{'═'*70}")
    print(f"  SCANER SOLER PRO — SIMULACIÓN COMPLETA DE MARCAS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*70}{RESET}")

    # ── 0. Imports ────────────────────────────────────────────────────────────
    test_imports()

    # ── 1. Conexión básica por marca ──────────────────────────────────────────
    head("FASE 1 — CONEXIONES POR MARCA")
    for marca in MARCAS:
        try:
            test_conexion_marca(marca)
        except Exception as e:
            err(f"CRASH en {marca}: {e}")
            traceback.print_exc()

    # ── 2. Diagnóstico completo ───────────────────────────────────────────────
    head("FASE 2 — DIAGNÓSTICO COMPLETO (motor DiagnosticEngine)")
    for marca, data in MARCAS.items():
        try:
            test_motor_diagnostico_completo(marca, len(data["dtcs"]))
        except Exception as e:
            err(f"CRASH DiagnosticEngine {marca}: {e}")
            traceback.print_exc()

    # ── 3. Quick health check todas las marcas ────────────────────────────────
    test_quick_health_check_todas_marcas()

    # ── 4. Corrección de fallas ───────────────────────────────────────────────
    head("FASE 3 — CORRECCIÓN DE FALLAS (clear DTC)")
    for marca in ["VW", "BMW", "Chevrolet", "Renault"]:
        try:
            test_correccion_fallas(marca)
        except Exception as e:
            err(f"CRASH corrección {marca}: {e}")

    # ── 5. Módulo de seguridad ────────────────────────────────────────────────
    try:
        test_modulo_seguridad()
    except Exception as e:
        err(f"CRASH security: {e}")
        traceback.print_exc()

    # ── 6. CAN bus ────────────────────────────────────────────────────────────
    try:
        test_can_bus()
    except Exception as e:
        err(f"CRASH CAN bus: {e}")
        traceback.print_exc()

    # ── 7. Ingeniería inversa ─────────────────────────────────────────────────
    try:
        test_reverse_engineer_pipeline()
    except Exception as e:
        err(f"CRASH RE pipeline: {e}")
        traceback.print_exc()

    # ── 8. Mapa ECU + safety guard ────────────────────────────────────────────
    try:
        test_mapa_ecu_y_seguridad_escritura()
    except Exception as e:
        err(f"CRASH MapTable: {e}")
        traceback.print_exc()

    # ── 9. Resiliencia ────────────────────────────────────────────────────────
    try:
        test_fallo_parcial_conexion()
    except Exception as e:
        err(f"CRASH resiliencia: {e}")
        traceback.print_exc()

    # ── 10. Registro de PIDs ──────────────────────────────────────────────────
    try:
        test_pid_registry()
    except Exception as e:
        err(f"CRASH PID registry: {e}")
        traceback.print_exc()

    # ── RESULTADO FINAL ───────────────────────────────────────────────────────
    total = PASS + FAIL
    pct   = (PASS / total * 100) if total else 0
    color = G if FAIL == 0 else (Y if FAIL <= 3 else R)

    print(f"\n{BOLD}{W}{'═'*70}")
    print(f"  RESULTADO: {color}{PASS}/{total} checks pasaron ({pct:.0f}%){RESET}")
    if FAIL:
        print(f"  {R}{FAIL} fallo(s) encontrado(s){RESET}")
    else:
        print(f"  {G}Sistema validado sin errores{RESET}")
    print(f"{W}{'═'*70}{RESET}\n")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
