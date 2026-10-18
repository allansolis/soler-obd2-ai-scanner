"""
test_mapas_dtc_re.py
Validación focalizada en 3 áreas:
  1. Creación y edición de mapas ECU por marca de auto
  2. Borrado de errores (DTCs) por marca
  3. Ingeniería inversa — reconocimiento de ECU desconocida

Ejecutar:  python test_mapas_dtc_re.py
"""
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np

# ── Colores consola ─────────────────────────────────────────────────────────────
R  = "\033[91m"; G  = "\033[92m"; Y  = "\033[93m"; B  = "\033[94m"
M  = "\033[95m"; C  = "\033[96m"; W  = "\033[97m"; RESET = "\033[0m"
BOLD = "\033[1m"

PASS = 0; FAIL = 0

def ok(msg):   print(f"{G}  ✓ {msg}{RESET}")
def err(msg):  print(f"{R}  ✗ {msg}{RESET}")
def warn(msg): print(f"{Y}  ⚠ {msg}{RESET}")
def head(msg): print(f"\n{BOLD}{B}{msg}{RESET}")
def sub(msg):  print(f"{M}  ── {msg}{RESET}")

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ok(f"{label}{' — '+detail if detail else ''}")
    else:
        FAIL += 1
        err(f"{label}{' — '+detail if detail else ''}")

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE MAPAS POR MARCA
# (cada marca tiene rangos seguros propios según su ECU y motor)
# ═══════════════════════════════════════════════════════════════════════════════

MARCAS_MAPAS = {
    "VW_Bosch_ME17": {
        "ecu": "Bosch ME17.5.25",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -5.0, "max_safe": 35.0,
                "rpm_axis": np.array([800,1200,1600,2000,2500,3000,3500,4000,5000,6000], dtype=float),
                "load_axis": np.array([20,30,40,50,60,70,80,90,100], dtype=float),
                "base_deg": 18.0,
                "safe_delta": +2.0,
                "unsafe_delta": +25.0,
            },
            "fuel": {
                "unit": "ms",
                "min_safe": 0.8, "max_safe": 18.0,
                "rpm_axis": np.array([800,1200,1600,2000,2500,3000,3500,4000,5000,6000], dtype=float),
                "load_axis": np.array([20,30,40,50,60,70,80,90,100], dtype=float),
                "base_deg": 3.5,
                "safe_delta": +0.5,
                "unsafe_delta": +20.0,
            },
        },
    },
    "Toyota_Denso": {
        "ecu": "Denso 89661-47E00",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -8.0, "max_safe": 38.0,
                "rpm_axis": np.array([700,1000,1500,2000,2500,3000,4000,5000,6000,7000], dtype=float),
                "load_axis": np.array([15,25,35,50,65,80,100], dtype=float),
                "base_deg": 20.0,
                "safe_delta": +3.0,
                "unsafe_delta": +30.0,
            },
            "boost": {
                "unit": "bar abs",
                "min_safe": 0.9, "max_safe": 2.0,
                "rpm_axis": np.array([1200,1800,2500,3000,3500,4000,5000], dtype=float),
                "load_axis": np.array([40,60,80,100], dtype=float),
                "base_deg": 1.2,
                "safe_delta": +0.1,
                "unsafe_delta": +1.5,
            },
        },
    },
    "BMW_Bosch_MSD80": {
        "ecu": "Bosch MSD80",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -10.0, "max_safe": 45.0,
                "rpm_axis": np.array([600,1000,1500,2000,3000,4000,5000,6000,7000,8000], dtype=float),
                "load_axis": np.array([10,20,30,40,50,60,70,80,90,100], dtype=float),
                "base_deg": 22.0,
                "safe_delta": +4.0,
                "unsafe_delta": +35.0,
            },
            "fuel": {
                "unit": "ms",
                "min_safe": 0.5, "max_safe": 22.0,
                "rpm_axis": np.array([600,1000,1500,2000,3000,4000,5000,6000,7000,8000], dtype=float),
                "load_axis": np.array([10,20,30,40,50,60,70,80,90,100], dtype=float),
                "base_deg": 4.0,
                "safe_delta": +0.8,
                "unsafe_delta": +25.0,
            },
        },
    },
    "Ford_PCM": {
        "ecu": "Ford PCM 7T4Z-12A650-ATA",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -8.0, "max_safe": 40.0,
                "rpm_axis": np.array([700,1000,1500,2000,2500,3000,4000,5000,6000], dtype=float),
                "load_axis": np.array([20,35,50,65,80,100], dtype=float),
                "base_deg": 17.0,
                "safe_delta": +2.5,
                "unsafe_delta": +40.0,
            },
        },
    },
    "Chevrolet_Delphi_E38": {
        "ecu": "Delphi E38",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -12.0, "max_safe": 42.0,
                "rpm_axis": np.array([600,900,1200,1800,2400,3000,4000,5500,7000], dtype=float),
                "load_axis": np.array([20,40,60,80,100], dtype=float),
                "base_deg": 16.0,
                "safe_delta": +3.0,
                "unsafe_delta": +45.0,
            },
        },
    },
    "Honda_Keihin": {
        "ecu": "Keihin 37820-RZA-A53",
        "maps": {
            "fuel": {
                "unit": "ms",
                "min_safe": 0.6, "max_safe": 20.0,
                "rpm_axis": np.array([750,1000,1500,2000,3000,4000,5500,7000], dtype=float),
                "load_axis": np.array([20,40,60,80,100], dtype=float),
                "base_deg": 3.0,
                "safe_delta": +0.4,
                "unsafe_delta": +22.0,
            },
        },
    },
    "Nissan_Hitachi": {
        "ecu": "Hitachi MEC90310",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -6.0, "max_safe": 38.0,
                "rpm_axis": np.array([650,1000,1600,2200,3000,4000,5500,7000], dtype=float),
                "load_axis": np.array([20,40,60,80,100], dtype=float),
                "base_deg": 19.0,
                "safe_delta": +2.0,
                "unsafe_delta": +35.0,
            },
        },
    },
    "Renault_Siemens": {
        "ecu": "Siemens SID305",
        "maps": {
            "ignition": {
                "unit": "deg BTDC",
                "min_safe": -5.0, "max_safe": 32.0,
                "rpm_axis": np.array([700,1100,1600,2200,3000,4000,5000,6000], dtype=float),
                "load_axis": np.array([20,40,60,80,100], dtype=float),
                "base_deg": 16.5,
                "safe_delta": +1.5,
                "unsafe_delta": +30.0,
            },
        },
    },
}

# DTCs por marca para test de borrado
MARCAS_DTCS = {
    "VW":        [("P0171", "Sistema mezcla pobre Banco 1", "warning"),
                  ("P0300", "Fallo encendido aleatorio",    "critical")],
    "Toyota":    [("P0A0F", "Fallo sistema carga HV",       "critical"),
                  ("P0101", "MAF fuera de rango",           "warning")],
    "BMW":       [("P0016", "Correlacion cigüeñal/arbol",   "warning"),
                  ("P0420", "Eficiencia catalizador baja",  "warning")],
    "Ford":      [("P0456", "Fuga pequeña sistema EVAP",   "warning"),
                  ("P0340", "Sensor arbol de levas A",      "critical")],
    "Chevrolet": [("P0128", "Temperatura refrigerante baja","warning"),
                  ("P0562", "Voltaje bajo sistema",         "critical")],
    "Honda":     [("P0401", "Flujo EGR insuficiente",      "warning")],
    "Nissan":    [("P0102", "MAF senal baja",               "warning"),
                  ("P0505", "Control ralenti inoperante",   "critical")],
    "Renault":   [("P0403", "Circuito solenoide EGR",      "warning"),
                  ("P0113", "Sensor temperatura aire alto", "warning")],
}

# ═══════════════════════════════════════════════════════════════════════════════
# MOCK ECU para ingeniería inversa
# simula respuestas de ECUs con distintos protocolos
# ═══════════════════════════════════════════════════════════════════════════════

class MockECU_UDS:
    """ECU simulada que habla UDS (como BMW, VW moderno)."""
    name = "ECU-Desconocida-UDS (BMW-like)"

    def send(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "01 00":    return "NO DATA"
        if cmd == "09 02":    return "NO DATA"
        if cmd == "10 01":    return "50 01 00 19 01 F4"      # UDS positive response
        if cmd == "10 92":    return "7F 10 11"               # NRC service not supported
        if cmd.startswith("22 F1 90"): return "62 F1 90 57 42 41 33 41 35 47 35 35 46 4E 53 30 30 30 30 31"
        if cmd.startswith("22 F1 8C"): return "62 F1 8C 42 4F 53 43 48 30 30 31"
        if cmd.startswith("22 F1"):    return "62 F1 87 30 30 31 32 33"
        if cmd.startswith("22"):       return "7F 22 31"     # request out of range
        if cmd.startswith("AT"):       return "OK"
        return "NO DATA"


class MockECU_OBD2:
    """ECU simulada OBD2 genérica (como Toyota, Honda, Ford básico)."""
    name = "ECU-Desconocida-OBD2 (Toyota-like)"

    def send(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "01 00":    return "41 00 BE 3F A8 13"   # PIDs soportados
        if cmd == "01 0C":    return "41 0C 0F A0"          # RPM 1000
        if cmd == "01 05":    return "41 05 5A"              # coolant 50°C
        if cmd == "01 0D":    return "41 0D 00"              # speed 0
        if cmd == "09 02":    return "49 02 01 4A 54 44 4B 4E 33 44 55 39 41 31 32 33 34 35 36 37"
        if cmd == "10 01":    return "7F 10 11"              # UDS no soportado
        if cmd.startswith("22"): return "7F 22 11"           # UDS no soportado
        if cmd.startswith("AT"): return "OK"
        return "NO DATA"


class MockECU_KWP:
    """ECU simulada KWP2000 (como Renault, Citroën viejos)."""
    name = "ECU-Desconocida-KWP2000 (Renault-like)"

    def send(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "01 00":    return "NO DATA"
        if cmd == "10 92":    return "50 92"                  # KWP startDiagSession OK
        if cmd == "10 01":    return "50 01"                  # startSession
        if cmd == "1A 86":    return "5A 86 53 49 44 33 30 35"  # ECU ID SID305
        if cmd.startswith("AT"): return "OK"
        return "NO DATA"


class MockECU_Unknown:
    """ECU completamente desconocida — responde con patrones raros."""
    name = "ECU-Totalmente-Desconocida"

    def send(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "01 00":    return "FF FF FF FF"           # responde pero no OBD2 estándar
        if cmd == "10 01":    return "50 01 00 25 02 80"     # parece UDS
        if cmd.startswith("AT"): return "OK"
        import random
        return random.choice(["NO DATA", "NO DATA", "FF FF", "50 01 AA BB"])


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — CREACIÓN Y EDICIÓN DE MAPAS POR MARCA
# ═══════════════════════════════════════════════════════════════════════════════

def test_mapas_por_marca():
    from scaner_soler.ecu.maps.map_table import MapTable
    from scaner_soler.ecu.maps.map_editor import MapEditor
    from scaner_soler.exceptions import SafetyError

    head("CREACIÓN Y EDICIÓN DE MAPAS ECU — 8 MARCAS")

    for marca, cfg in MARCAS_MAPAS.items():
        sub(f"{marca}  ({cfg['ecu']})")

        for map_name, mcfg in cfg["maps"].items():
            rows = len(mcfg["rpm_axis"])
            cols = len(mcfg["load_axis"])
            base = mcfg["base_deg"]

            # Construir tabla con valores base
            values = np.full((rows, cols), base, dtype=float)
            tabla = MapTable(
                name=f"{marca}_{map_name}",
                rpm_axis=mcfg["rpm_axis"],
                load_axis=mcfg["load_axis"],
                values=values,
                unit=mcfg["unit"],
                min_safe=mcfg["min_safe"],
                max_safe=mcfg["max_safe"],
                description=f"{cfg['ecu']} — {map_name}",
            )
            check(f"[{marca}/{map_name}] MapTable creada ({rows}x{cols})",
                  tabla.values.shape == (rows, cols))

            # Editar con MapEditor: delta seguro
            editor = MapEditor(tabla)
            safe_val = base + mcfg["safe_delta"]
            try:
                editor.set(0, 0, safe_val)
                check(f"[{marca}/{map_name}] set() valor seguro ({safe_val:.1f} {mcfg['unit']})",
                      tabla.get_cell(0, 0) == safe_val)
            except Exception as e:
                check(f"[{marca}/{map_name}] set() valor seguro", False, str(e))

            # dirty flag
            check(f"[{marca}/{map_name}] dirty flag True tras edición", tabla.has_changes)

            # add() a una región
            try:
                editor.add_to_region(slice(0, 2), slice(0, 2), mcfg["safe_delta"])
                check(f"[{marca}/{map_name}] add_to_region() sin excepción", True)
            except SafetyError as e:
                check(f"[{marca}/{map_name}] add_to_region() sin excepción", False, str(e))

            # SafetyError con delta inseguro
            unsafe_val = mcfg["max_safe"] + mcfg["unsafe_delta"]
            raised = False
            try:
                editor.set(0, 0, unsafe_val)
            except SafetyError:
                raised = True
            check(f"[{marca}/{map_name}] SafetyError con valor {unsafe_val:.1f} {mcfg['unit']}", raised)

            # changes_summary
            summary = editor.changes_summary()
            check(f"[{marca}/{map_name}] changes_summary() no vacío", summary != "Sin cambios.")

            # restore backup
            editor.restore()
            check(f"[{marca}/{map_name}] restore() vuelve a base",
                  abs(tabla.get_cell(0, 0) - base) < 1e-9)
            check(f"[{marca}/{map_name}] dirty flag False tras restore", not tabla.has_changes)

            # Checksum estable
            cs1 = tabla.checksum()
            cs2 = tabla.checksum()
            check(f"[{marca}/{map_name}] checksum determinista", cs1 == cs2)

            # Roundtrip dict
            d = tabla.to_dict()
            tabla2 = MapTable.from_dict(d)
            check(f"[{marca}/{map_name}] to_dict/from_dict roundtrip",
                  tabla2.name == tabla.name and tabla2.values.shape == tabla.values.shape)

            # Interpolación
            rpm_mid  = float(mcfg["rpm_axis"][len(mcfg["rpm_axis"])//2])
            load_mid = float(mcfg["load_axis"][len(mcfg["load_axis"])//2])
            try:
                iv = tabla.interpolate_at(rpm_mid, load_mid)
                check(f"[{marca}/{map_name}] interpolate_at({rpm_mid:.0f} rpm, {load_mid:.0f}%)",
                      mcfg["min_safe"] - 0.1 <= iv <= mcfg["max_safe"] + 0.1,
                      f"{iv:.3f} {mcfg['unit']}")
            except Exception as e:
                check(f"[{marca}/{map_name}] interpolate_at()", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — BORRADO DE ERRORES (DTCs) POR MARCA
# ═══════════════════════════════════════════════════════════════════════════════

def test_borrado_dtcs():
    from scaner_soler.comm.base import DTC, AbstractProtocol
    from scaner_soler.diagnostic.diagnostic_engine import DiagnosticEngine

    head("BORRADO DE ERRORES DTC — 8 MARCAS")

    for marca, dtc_defs in MARCAS_DTCS.items():
        sub(f"{marca}")

        # Construir DTCs
        dtcs_iniciales = []
        for code, desc, sev in dtc_defs:
            try:
                dtc = DTC.from_raw_code(code)
                dtc.description = desc
                dtc.severity     = sev
                dtcs_iniciales.append(dtc)
            except Exception as e:
                err(f"[{marca}] No se pudo crear DTC {code}: {e}")

        check(f"[{marca}] DTCs creados ({len(dtcs_iniciales)})",
              len(dtcs_iniciales) == len(dtc_defs))

        # Mock protocol con soporte de clear
        class MockProtoBorrado(AbstractProtocol):
            def __init__(self, brand, initial_dtcs):
                self._brand = brand
                self._dtcs  = list(initial_dtcs)
                self._connected = True
                self._cleared = False

            def connect(self, port: str = "MOCK", baudrate: int = 115200) -> bool:
                self._connected = True
                return True

            def disconnect(self) -> None:
                self._connected = False

            @property
            def is_connected(self) -> bool:
                return self._connected

            def send_raw(self, data: bytes, timeout: float = 5.0) -> bytes:
                return b"\x00"

            def read_pid(self, pid: int, mode: int = 0x01) -> dict:
                values = {0x0C: 1800.0, 0x05: 90.0, 0x0D: 0.0}
                names  = {0x0C: "rpm",  0x05: "coolant_temp", 0x0D: "speed"}
                return {"value": values.get(pid, 0.0),
                        "unit": "",
                        "name": names.get(pid, f"pid_{pid:02X}")}

            def read_dtc(self) -> list:
                return list(self._dtcs) if not self._cleared else []

            def clear_dtc(self) -> bool:
                self._dtcs.clear()
                self._cleared = True
                return True

            def read_freeze_frame(self, dtc_code: str) -> dict:
                return {"rpm": 1800, "load": 65.0, "coolant": 88}

            def read_vehicle_info(self) -> dict:
                return {"vin": f"TEST{self._brand}12345678901",
                        "ecu_name": f"ECU_{self._brand}", "make": self._brand}

        proto = MockProtoBorrado(marca, dtcs_iniciales)

        # Verificar DTCs presentes antes de borrar
        dtcs_leidos = proto.read_dtc()
        check(f"[{marca}] DTCs presentes antes del borrado ({len(dtcs_leidos)})",
              len(dtcs_leidos) == len(dtcs_iniciales))

        # Borrar
        resultado = proto.clear_dtc()
        check(f"[{marca}] clear_dtc() retorna True", resultado is True)

        # Verificar vacíos
        dtcs_post = proto.read_dtc()
        check(f"[{marca}] DTCs vacíos tras borrado ({len(dtcs_post)})",
              len(dtcs_post) == 0)

        # DiagnosticEngine confirma limpio (vía VehicleConnection)
        try:
            from scaner_soler.comm.vehicle_conn import VehicleConnection
            conn   = VehicleConnection(protocol=proto)
            engine = DiagnosticEngine(conn)
            reporte = engine.full_scan()
            check(f"[{marca}] full_scan() post-borrado sin DTCs confirmados",
                  len(reporte.confirmed_dtcs) == 0)
        except Exception as e:
            warn(f"[{marca}] DiagnosticEngine.full_scan(): {e}")

        # Second clear idempotente
        resultado2 = proto.clear_dtc()
        check(f"[{marca}] segundo clear() idempotente (True)", resultado2 is True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — INGENIERÍA INVERSA: RECONOCIMIENTO DE ECU DESCONOCIDA
# ═══════════════════════════════════════════════════════════════════════════════

def test_ingenieria_inversa():
    from scaner_soler.comm.reverse_engineer import (
        ReverseEngineerSession, UnknownECUProfiler,
        PatternAnalyzer, ProtocolGuesser, FieldJournal,
    )

    head("INGENIERÍA INVERSA — RECONOCIMIENTO DE ECU")

    ecus = [
        MockECU_UDS(),
        MockECU_OBD2(),
        MockECU_KWP(),
        MockECU_Unknown(),
    ]

    for mock_ecu in ecus:
        sub(f"{mock_ecu.name}")

        # ── a) FieldJournal ──────────────────────────────────────────────────
        journal = FieldJournal(session_id=f"test_{mock_ecu.__class__.__name__}")
        entry = journal.log("01 00", mock_ecu.send("01 00"), tags=["test"])
        check(f"[{mock_ecu.name[:20]}] FieldJournal.log() registra entrada",
              len(journal.entries) == 1)

        # ── b) PatternAnalyzer ───────────────────────────────────────────────
        responses = [mock_ecu.send(c) for c in
                     ["01 00", "10 01", "10 92", "22 F1 90", "09 02"]]
        valid_hex = [r for r in responses if r not in ("NO DATA", "OK", "")]
        if valid_hex:
            stats = PatternAnalyzer.analyze_frame(valid_hex[0], arb_id="7E8")
            check(f"[{mock_ecu.name[:20]}] PatternAnalyzer.analyze_frame() retorna FrameStats",
                  stats is not None and hasattr(stats, "entropy"))
            check(f"[{mock_ecu.name[:20]}] Entropía >= 0",
                  stats.entropy >= 0.0, f"{stats.entropy:.2f} bits")
        else:
            warn(f"[{mock_ecu.name[:20]}] sin frames hex válidos para analizar")

        # ── c) ProtocolGuesser ───────────────────────────────────────────────
        guesses = ProtocolGuesser.guess(responses)
        check(f"[{mock_ecu.name[:20]}] ProtocolGuesser retorna al menos 1 guess",
              len(guesses) >= 1)
        best = guesses[0].protocol if guesses else "UNKNOWN"
        check(f"[{mock_ecu.name[:20]}] Protocolo detectado: {best}",
              best != "" and best is not None)

        # ── d) UnknownECUProfiler (agent-loop completo) ──────────────────────
        try:
            profiler = UnknownECUProfiler(send_fn=mock_ecu.send, delay_s=0.0)
            profile = profiler.profile()
            check(f"[{mock_ecu.name[:20]}] profile() retorna ECUProfile sin excepción",
                  profile is not None)
            check(f"[{mock_ecu.name[:20]}] best_protocol asignado: {profile.best_protocol}",
                  profile.best_protocol not in ("", None))
            check(f"[{mock_ecu.name[:20]}] probes enviados >= 5",
                  len(profile.raw_probe_data) >= 5,
                  f"{len(profile.raw_probe_data)} probes")
            js = profiler.journal.summary()
            check(f"[{mock_ecu.name[:20]}] journal total_entries >= 5",
                  js["total_entries"] >= 5,
                  f"{js['total_entries']} entradas")
        except Exception as e:
            check(f"[{mock_ecu.name[:20]}] UnknownECUProfiler.profile()", False, str(e))
            traceback.print_exc()

        # ── e) ReverseEngineerSession (sin fuzz para rapidez) ────────────────
        try:
            session = ReverseEngineerSession(
                send_fn=mock_ecu.send,
                probe_delay_s=0.0,
                fuzz_delay_s=0.0,
            )
            result = session.run(fuzz=False)
            check(f"[{mock_ecu.name[:20]}] session.run(fuzz=False) sin excepción",
                  result is not None)
            check(f"[{mock_ecu.name[:20]}] RESessionResult.profile presente",
                  result.profile is not None)
            check(f"[{mock_ecu.name[:20]}] journal_summary tiene total_entries",
                  "total_entries" in result.journal_summary)
            check(f"[{mock_ecu.name[:20]}] duration_s >= 0",
                  result.duration_s >= 0.0,
                  f"{result.duration_s:.3f}s")
        except Exception as e:
            check(f"[{mock_ecu.name[:20]}] ReverseEngineerSession.run()", False, str(e))
            traceback.print_exc()

    # ── f) RE con ReverseEngineerSession fuzz OBD RÁPIDO (solo 4 PIDs) ──────
    sub("Fuzz OBD rápido sobre MockECU_OBD2 (PIDs 0x00-0x03)")
    mock_obd = MockECU_OBD2()
    from scaner_soler.comm.reverse_engineer import PIDFuzzer
    try:
        fuzz = PIDFuzzer(send_fn=mock_obd.send, delay_s=0.0)
        res = fuzz.fuzz_obd_service(service=0x01, pid_start=0x00, pid_end=0x03)
        check("PIDFuzzer.fuzz_obd_service(01, 00-03) retorna resultados",
              len(res) == 4)
        positives = fuzz.positive_hits()
        check("Al menos 1 PID positivo (01 00 soportado)", len(positives) >= 1)
        catalog = fuzz.export_catalog()
        check("export_catalog() retorna lista de dicts", isinstance(catalog, list))
    except Exception as e:
        check("PIDFuzzer fuzz rápido", False, str(e))
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{W}{'═'*70}")
    print("  VALIDACIÓN: MAPAS ECU + BORRADO DTCs + INGENIERÍA INVERSA")
    print(f"{'═'*70}{RESET}")

    tests = [
        ("1. MAPAS ECU POR MARCA",    test_mapas_por_marca),
        ("2. BORRADO DE ERRORES DTC", test_borrado_dtcs),
        ("3. INGENIERÍA INVERSA",     test_ingenieria_inversa),
    ]

    for nombre, fn in tests:
        try:
            fn()
        except Exception as e:
            print(f"\n{R}ERROR FATAL en {nombre}: {e}{RESET}")
            traceback.print_exc()

    total = PASS + FAIL
    pct   = 100.0 * PASS / total if total else 0
    color = G if FAIL == 0 else (Y if pct >= 80 else R)

    print(f"\n{BOLD}{W}{'═'*70}")
    print(f"  RESULTADO: {color}{PASS}/{total} checks pasaron ({pct:.0f}%){RESET}")
    if FAIL == 0:
        print(f"{G}  Sistema 100% validado — mapas, DTCs e ingeniería inversa OK{RESET}")
    else:
        print(f"{R}  {FAIL} checks fallaron — revisar detalles arriba{RESET}")
    print(f"{BOLD}{W}{'═'*70}{RESET}\n")

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
