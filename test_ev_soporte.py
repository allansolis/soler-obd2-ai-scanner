"""
Validación del módulo EV — vehículos eléctricos e híbridos.

Suite completa:
  1. EV PID Registry — Mode 01 + UDS Mode 22 por marca
  2. BMSReader — aggregación y alertas de seguridad
  3. ChargingSession — ciclo completo de sesión de carga
  4. DTC EV Database — clasificación y búsqueda de fallos

Corre sin conexión real (todo offline / simulado).
"""
from __future__ import annotations

import sys

OK  = "✓"
FAIL = "✗"
_checks: list[bool] = []


def chk(condition: bool, msg: str) -> None:
    _checks.append(condition)
    sym = OK if condition else FAIL
    if not condition:
        print(f"  {sym} FALLO: {msg}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EV PID REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════
print("\n── 1. EV PID Registry ──")

from scaner_soler.ev.ev_pid_registry import (
    EV_MODE01_PIDS, EV_UDS_PIDS, EV_BRANDS, decode_ev
)

# 1.1 PIDs Mode 01 presentes
for pid_int, expected_name in [
    (0x5B, "hybrid_batt_soc"),
    (0x7B, "battery_temp"),
    (0x9A, "ev_motor_torque"),
    (0x9C, "ev_motor_rpm"),
    (0x9D, "ev_power_kw"),
    (0x9E, "ev_range_km"),
    (0x9F, "ev_charging_status"),
    (0xA0, "ev_pack_voltage"),
    (0xA1, "ev_pack_current"),
]:
    entry = EV_MODE01_PIDS.get(pid_int)
    chk(entry is not None, f"PID 0x{pid_int:02X} existe")
    if entry:
        chk(entry[0] == expected_name, f"PID 0x{pid_int:02X} nombre = {expected_name}")

# 1.2 Decodificación Mode 01
name, mode, pid_hex, unit, min_b, formula = EV_MODE01_PIDS[0x5B]
soc = formula([128])
chk(abs(soc - 50.2) < 0.5, f"SOC 0x5B decode ~ 50% (got {soc})")

name_rpm, *_, formula_rpm = EV_MODE01_PIDS[0x9C]
rpm = formula_rpm([0x80, 0x00])   # 0x8000 = 32768 → 0 RPM
chk(abs(rpm) < 10, f"Motor RPM decode = 0 (got {rpm})")

# 1.3 Charging status decode
_, _, _, _, _, f_cs = EV_MODE01_PIDS[0x9F]
chk(f_cs([0x04]) == "DC_CCS",  "ChargingStatus 0x04 = DC_CCS")
chk(f_cs([0x05]) == "DC_CHADEMO", "ChargingStatus 0x05 = DC_CHADEMO")
chk(f_cs([0x00]) == "NOT_CHARGING", "ChargingStatus 0x00 = NOT_CHARGING")

# 1.4 Marcas presentes en EV_BRANDS
expected_brands = ["Nissan_Leaf", "Chevrolet_Bolt", "BMW_i3", "VW_MEB",
                   "Renault_Zoe", "Hyundai_EGMP", "Tesla_OBD"]
for brand in expected_brands:
    chk(brand in EV_BRANDS, f"Marca {brand} en EV_BRANDS")
    chk(brand in EV_UDS_PIDS, f"Marca {brand} en EV_UDS_PIDS")
    chk("ecu_addr" in EV_BRANDS[brand], f"{brand} tiene ecu_addr")

# 1.5 UDS PIDs por marca — conteo mínimo
min_pids = {
    "Nissan_Leaf":   11,
    "Chevrolet_Bolt": 9,
    "BMW_i3":        12,
    "VW_MEB":        14,
    "Renault_Zoe":    9,
    "Hyundai_EGMP":  15,
    "Tesla_OBD":      6,
}
for brand, min_n in min_pids.items():
    n = len(EV_UDS_PIDS[brand])
    chk(n >= min_n, f"{brand}: {n} PIDs (mín {min_n})")

# 1.6 decode_ev — valores correctos
result = decode_ev("Nissan_Leaf", "0104", [150])   # SOC: 150/2 = 75%
chk(result["name"] == "bms_soc",  "Nissan 0104 name = bms_soc")
chk(abs(result["value"] - 75.0) < 0.5, f"Nissan SOC = 75% (got {result['value']})")
chk(result["unit"] == "%",        "Nissan SOC unit = %")

result_v = decode_ev("Chevrolet_Bolt", "D002", [0x0C, 0x80])  # 3200 * 0.0625 = 200V
chk(result_v["name"] == "bms_pack_voltage", "Bolt D002 = pack_voltage")
chk(abs(result_v["value"] - 200.0) < 1.0, f"Bolt voltage ~200V (got {result_v['value']})")

result_unknown = decode_ev("BMW_i3", "FFFF", [0x00])
chk(result_unknown["name"].startswith("UNKNOWN"), "PID desconocido retorna UNKNOWN_")

# 1.7 UDS PIDs con signo (corriente pack — con signo)
result_curr = decode_ev("VW_MEB", "0302", [0x80, 0x00])  # 0x8000 = 32768 - 32768 = 0 A
chk(result_curr["name"] == "bms_current", "VW 0302 = bms_current")
chk(abs(result_curr["value"]) < 0.5, f"VW current = 0A (got {result_curr['value']})")

result_curr2 = decode_ev("VW_MEB", "0302", [0x80, 0x64])  # 32868 - 32768 = 100 * 0.1 = 10A
chk(abs(result_curr2["value"] - 10.0) < 0.5, f"VW current = 10A carga (got {result_curr2['value']})")

# 1.8 PIDs de temperatura
result_temp = decode_ev("BMW_i3", "DD01", [72])  # 72 - 40 = 32°C
chk(result_temp["name"] == "bms_temp",  "BMW DD01 = bms_temp")
chk(result_temp["value"] == 32.0,       f"BMW temp = 32°C (got {result_temp['value']})")

# 1.9 Hyundai E-GMP — PIDs de carga
result_chpwr = decode_ev("Hyundai_EGMP", "0501", [0x00, 0xF0])  # 240 * 0.1 = 24 kW
chk(result_chpwr["name"] == "charge_power_kw", "Hyundai 0501 = charge_power_kw")
chk(abs(result_chpwr["value"] - 24.0) < 0.5, f"Hyundai charge 24kW (got {result_chpwr['value']})")

print(f"  → {sum(_checks[-50:])} / {len(_checks[-50:])} checks")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. BMS READER
# ═══════════════════════════════════════════════════════════════════════════════
print("\n── 2. BMSReader ──")
from scaner_soler.ev.bms_reader import BMSReader, BMSData, CellStats

# 2.1 Build básico — VW MEB
reader_vw = BMSReader("VW_MEB")
readings_vw = {
    "bms_soc":          78.5,
    "bms_temp_max":     32.0,
    "bms_temp_min":     28.0,
    "bms_pack_voltage": 380.0,
    "bms_current":      -55.0,  # descargando
    "bms_max_cell_v":   4.10,
    "bms_min_cell_v":   4.05,
    "motor_temp":       65.0,
    "inverter_temp":    55.0,
    "bms_soh":          95.0,
    "charge_power_kw":   0.0,
}
bms_vw = reader_vw.build(readings_vw)
chk(isinstance(bms_vw, BMSData),         "BMSData instanciado")
chk(bms_vw.brand == "VW_MEB",           "brand = VW_MEB")
chk(abs(bms_vw.soc_pct - 78.5) < 0.1,  f"SOC = 78.5% (got {bms_vw.soc_pct})")
chk(abs(bms_vw.temp_max - 32.0) < 0.1, f"temp_max = 32°C (got {bms_vw.temp_max})")
chk(bms_vw.temp_delta == 4.0,          f"temp_delta = 4°C (got {bms_vw.temp_delta})")
chk(abs(bms_vw.cells.delta_v - 0.05) < 0.001, f"cell delta_v = 0.05V (got {bms_vw.cells.delta_v})")

# 2.2 pack_power calculado si falta
chk(bms_vw.pack_power_kw is not None, "pack_power derivado de V*A")
expected_kw = round(380.0 * -55.0 / 1000, 2)
chk(abs(bms_vw.pack_power_kw - expected_kw) < 0.5,
    f"pack_power = {expected_kw} kW (got {bms_vw.pack_power_kw})")

# 2.3 is_charging
chk(not bms_vw.is_charging, "is_charging = False (corriente negativa = descargando)")

readings_cargando = dict(readings_vw, bms_current=80.0, charge_power_kw=22.0)
bms_cargando = reader_vw.build(readings_cargando)
chk(bms_cargando.is_charging, "is_charging = True cuando current > 1A")

# 2.4 Rango estimado
rango = bms_vw.estimated_range_km
chk(rango is not None, "estimated_range_km calculado")
chk(rango > 50,        f"Rango VW_MEB al 78.5% SOC > 50km (got {rango})")
print(f"    Rango estimado VW_MEB 78.5% SOC: {rango} km")

# 2.5 Alertas — ninguna en condición normal
chk(len(bms_vw.alerts) == 0,
    f"Sin alertas en condición normal (hay {bms_vw.alerts})")

# 2.6 Alertas — sobrecalentamiento
readings_hot = dict(readings_vw, bms_temp_max=65.0, motor_temp=190.0)
bms_hot = reader_vw.build(readings_hot)
chk(any("ALTO temp_max" in a for a in bms_hot.alerts),
    f"Alerta por temp_max > 60°C (alerts={bms_hot.alerts})")
chk(any("ALTO motor_temp" in a for a in bms_hot.alerts),
    f"Alerta por motor_temp > 180°C")

# 2.7 Alerta SOH crítico
readings_old = dict(readings_vw, bms_soh=65.0)
bms_old = reader_vw.build(readings_old)
chk(any("SOH" in a for a in bms_old.alerts),
    f"Alerta SOH < 70% (alerts={bms_old.alerts})")

# 2.8 summary() produce string
summary = bms_vw.summary()
chk("VW_MEB" in summary, "summary contiene marca")
chk("SOC" in summary,    "summary contiene SOC")

# 2.9 BMSReader para Nissan Leaf
reader_leaf = BMSReader("Nissan_Leaf")
readings_leaf = {
    "bms_soc":          45.0,
    "bms_batt_temp_max": 25.0,
    "bms_batt_temp_min": 22.0,
    "bms_pack_voltage":  360.0,
    "bms_current":       30.0,
    "bms_hx":            88.5,   # campo específico Nissan (no en _FIELD_MAP → ignorado)
    "bms_max_cell_v":    3.95,
    "bms_min_cell_v":    3.90,
}
bms_leaf = reader_leaf.build(readings_leaf)
chk(bms_leaf.brand == "Nissan_Leaf", "BMSReader Nissan_Leaf")
chk(abs(bms_leaf.soc_pct - 45.0) < 0.1, "Nissan SOC = 45%")
chk(bms_leaf.temp_max == 25.0,          "Nissan temp_max (bms_batt_temp_max) = 25°C")

# 2.10 Desbalanceo celular — alerta
readings_unbal = dict(readings_vw, **{"bms_max_cell_v": 4.20, "bms_min_cell_v": 4.08})
bms_unbal = reader_vw.build(readings_unbal)
chk(any("delta_v" in a for a in bms_unbal.alerts),
    f"Alerta desbalanceo celular >50mV (alerts={bms_unbal.alerts})")

print(f"  → {sum(_checks[-40:])} / {len(_checks[-40:])} checks")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. CHARGING SESSION
# ═══════════════════════════════════════════════════════════════════════════════
print("\n── 3. ChargingSession ──")
from scaner_soler.ev.charging_session import (
    ChargingSession, ChargingState, ChargingConnectorType, ChargingProtocol
)

# 3.1 Ciclo completo AC
session = ChargingSession(session_id="TEST-001", brand="VW_MEB")
chk(session.state == ChargingState.DISCONNECTED, "Estado inicial = DISCONNECTED")
chk(not session.is_active, "No activa al inicio")

session.connect(ChargingConnectorType.AC_TYPE2, soc_pct=30.0)
chk(session.state == ChargingState.CONNECTED, "Estado tras connect = CONNECTED")
chk(session.soc_start_pct == 30.0, "soc_start = 30%")

session.start_handshake(ChargingProtocol.ISO15118_2)
chk(session.state == ChargingState.PROTOCOL_HANDSHAKE, "Handshake state")
chk(session.protocol == ChargingProtocol.ISO15118_2, "Protocolo ISO 15118-2")

session.start_auth()
chk(session.state == ChargingState.AUTHENTICATING, "Auth state")
chk(not session.pnc_enabled, "Plug&Charge desactivado (sin contract_id)")

session.start_charging(max_v=230.0, max_a=32.0)
chk(session.state == ChargingState.CHARGING, "Estado CHARGING")
chk(session.max_power_kw is not None, "max_power_kw calculado")
chk(abs(session.max_power_kw - 7.36) < 0.1,
    f"max_power = 7.36kW (got {session.max_power_kw})")
chk(session.start_time is not None, "start_time establecido")

# 3.2 Actualizaciones de telemetría (energy_kwh explícito para evitar dt≈0)
for i in range(5):
    session.update(voltage_v=228.0, current_a=30.0,
                   soc_pct=30.0 + i * 0.5, energy_kwh=0.5 + i * 0.1)

chk(len(session.power_history) == 5, "5 entradas en power_history")
chk(session.power_kw > 0, f"Potencia instantánea > 0 (got {session.power_kw})")
chk(session.energy_kwh > 0, "Energia acumulada > 0")
chk(session.power_kw_max > 0, "Pico de potencia registrado")
chk(session.avg_power_kw is not None, "avg_power_kw calculado")

# 3.3 is_dc / is_active
chk(not session.is_dc, "AC_TYPE2 → is_dc = False")
chk(session.is_active, "CHARGING → is_active = True")

# 3.4 Plug&Charge (ISO 15118-20)
session_pnc = ChargingSession(session_id="PNC-001", brand="BMW_i3")
session_pnc.connect(ChargingConnectorType.DC_CCS2, soc_pct=20.0)
session_pnc.start_handshake(ChargingProtocol.ISO15118_20)
session_pnc.start_auth(contract_id="DEBMWEV12345678X")
chk(session_pnc.pnc_enabled, "Plug&Charge habilitado")
chk(session_pnc.pnc_contract_id == "DEBMWEV12345678X", "contract_id guardado")
chk(session_pnc.is_dc, "DC_CCS2 → is_dc = True")

# 3.5 Ciclo completo DC rápido
session_dc = ChargingSession(session_id="DC-001", brand="Hyundai_EGMP")
session_dc.connect(ChargingConnectorType.DC_CCS2, soc_pct=15.0)
session_dc.start_handshake(ChargingProtocol.ISO15118_2)
session_dc.start_auth()
session_dc.start_charging(max_v=800.0, max_a=220.0)
chk(abs(session_dc.max_power_kw - 176.0) < 1.0,
    f"DC max_power ~ 176 kW (got {session_dc.max_power_kw})")

# Simular carga hasta 80% — 66 pasos para alcanzar soc=80 exacto
for i in range(66):
    session_dc.update(voltage_v=780.0, current_a=200.0, soc_pct=15.0 + i * 1.0)

# Al llegar a ~80% SOC, debe pasar a FINISHING
chk(session_dc.state == ChargingState.FINISHING,
    f"Estado FINISHING al llegar a 80% SOC (got {session_dc.state})")
chk(session_dc.soc_current_pct >= 79.0, f"SOC ≥ 79% (got {session_dc.soc_current_pct})")

session_dc.stop()
chk(session_dc.state == ChargingState.FINISHED, "Estado FINISHED tras stop()")
chk(session_dc.end_time is not None, "end_time establecido")
chk(session_dc.duration_min is not None and session_dc.duration_min >= 0,
    "duration_min >= 0")
soc_add = session_dc.soc_added_pct
chk(soc_add is not None and soc_add > 60.0,
    f"SOC añadido > 60% (got {soc_add})")

# 3.6 Fallos
session_fault = ChargingSession(session_id="FAULT-001", brand="Nissan_Leaf")
session_fault.connect(ChargingConnectorType.DC_CHADEMO, soc_pct=50.0)
session_fault.fault("P0B01", "HV contactor failure")
chk(session_fault.state == ChargingState.FAULTED, "Estado FAULTED tras fault()")
chk("P0B01" in session_fault.fault_codes, "fault_code P0B01 registrado")

# 3.7 Suspensión
session_susp = ChargingSession(session_id="SUSP-001", brand="Renault_Zoe")
session_susp.connect(ChargingConnectorType.AC_TYPE2, soc_pct=60.0)
session_susp.start_handshake(ChargingProtocol.IEC61851)
session_susp.start_auth()
session_susp.start_charging(max_v=230.0, max_a=16.0)
session_susp.suspend_ev()
chk(session_susp.state == ChargingState.SUSPENDED_EV, "SUSPENDED_EV")
chk(session_susp.is_active, "Suspendida pero is_active = True")

# 3.8 Events log
chk(len(session.events) > 0, "Events log poblado")
chk(any("Carga iniciada" in e for e in session.events), "Evento de inicio en log")

# 3.9 summary() completo
summary_dc = session_dc.summary()
chk("Hyundai_EGMP" in summary_dc, "summary contiene marca")
chk("FINISHED" in summary_dc,     "summary contiene estado FINISHED")

# 3.10 CHAdeMO
session_chd = ChargingSession(session_id="CHD-001", brand="Nissan_Leaf")
session_chd.connect(ChargingConnectorType.DC_CHADEMO, soc_pct=25.0)
session_chd.start_handshake(ChargingProtocol.CHADEMO_1)
chk(session_chd.protocol == ChargingProtocol.CHADEMO_1, "Protocolo CHAdeMO")
chk(session_chd.is_dc, "CHAdeMO → is_dc = True")

print(f"  → {sum(_checks[-45:])} / {len(_checks[-45:])} checks")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. DTC EV DATABASE
# ═══════════════════════════════════════════════════════════════════════════════
print("\n── 4. DTC EV Database ──")
from scaner_soler.ev.dtc_ev_codes import (
    EV_DTC_DB, classify_ev_dtc, is_ev_dtc, EVDTCEntry
)

# 4.1 Base de datos no vacía
chk(len(EV_DTC_DB) >= 30, f"DB tiene ≥30 entradas (hay {len(EV_DTC_DB)})")

# 4.2 Rangos presentes
ranges = {
    "P0A": ["P0A00", "P0A80", "P0A81"],
    "P0B": ["P0B00", "P0B30", "P0B50"],
    "P0C": ["P0C00", "P0C10"],
    "P1":  ["P1A00", "P1B00", "P1C00"],
    "B3":  ["B3010", "B3012"],
    "U0":  ["U0100", "U0110"],
}
for prefix, codes in ranges.items():
    for code in codes:
        chk(code in EV_DTC_DB, f"DTC {code} en base de datos")

# 4.3 classify_ev_dtc
entry = classify_ev_dtc("P0A81")
chk(entry is not None,               "P0A81 encontrado")
chk(isinstance(entry, EVDTCEntry),   "P0A81 retorna EVDTCEntry")
chk(entry.severity == "critical",    f"P0A81 severity = critical (got {entry.severity})")
chk(entry.system   == "battery",     f"P0A81 system = battery (got {entry.system})")
chk("Temperatura" in entry.action,   "P0A81 action menciona temperatura")

entry_none = classify_ev_dtc("P0100")  # código ICE estándar
chk(entry_none is None, "P0100 (ICE) retorna None")

# 4.4 is_ev_dtc
ev_codes = ["P0A00", "P0B01", "P0C10", "B3010", "U0110", "P1A00"]
for code in ev_codes:
    chk(is_ev_dtc(code), f"is_ev_dtc({code}) = True")

ice_codes = ["P0100", "P0301", "P0401", "C0031"]
for code in ice_codes:
    chk(not is_ev_dtc(code), f"is_ev_dtc({code}) = False (ICE)")

# 4.5 Campos obligatorios en todos los entries
for code, entry in EV_DTC_DB.items():
    chk(bool(entry.description),  f"{code}: description no vacío")
    chk(entry.system in ("battery", "motor", "charger", "cooling", "comm", "body"),
        f"{code}: system válido ({entry.system})")
    chk(entry.severity in ("critical", "warning", "info"),
        f"{code}: severity válido ({entry.severity})")
    chk(bool(entry.action),        f"{code}: action no vacío")

# 4.6 Severidades críticas
critical = [c for c, e in EV_DTC_DB.items() if e.severity == "critical"]
chk(len(critical) >= 10, f"Al menos 10 DTCs críticos (hay {len(critical)})")

# 4.7 Búsqueda case-insensitive
chk(classify_ev_dtc("p0a80") is not None, "classify_ev_dtc case-insensitive")
chk(classify_ev_dtc("P0A80") is not None, "classify_ev_dtc upper case")

# 4.8 Código fabricante específico
entry_chevy = classify_ev_dtc("P1E00")
chk(entry_chevy is not None,       "P1E00 (Chevy Bolt) en DB")
chk("Bolt" in entry_chevy.description or "Chevy" in entry_chevy.description,
    "P1E00 menciona Bolt o Chevy")

entry_vw = classify_ev_dtc("P1D30")
chk(entry_vw is not None,          "P1D30 (VW MEB) en DB")
chk(entry_vw.system == "charger",  "P1D30 system = charger")

entry_hyu = classify_ev_dtc("P1F00")
chk(entry_hyu is not None,         "P1F00 (Hyundai EGMP) en DB")
chk(entry_hyu.system == "comm",    "P1F00 system = comm")

# 4.9 DTC por sistema
systems = {}
for e in EV_DTC_DB.values():
    systems[e.system] = systems.get(e.system, 0) + 1

for sys_name in ("battery", "motor", "charger", "cooling", "comm"):
    chk(systems.get(sys_name, 0) >= 1, f"Sistema '{sys_name}' representado en DB")

print(f"  → {sum(_checks[-50:])} / {len(_checks[-50:])} checks")

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════════════════
total = len(_checks)
passed = sum(_checks)
failed = total - passed

print(f"\n{'='*60}")
print(f"RESULTADO: {passed}/{total} checks ({100*passed//total}%)")
if failed:
    print(f"  {failed} FALLOS — ver líneas con ✗ arriba")
    sys.exit(1)
else:
    print("  Todos los checks pasaron ✓")
