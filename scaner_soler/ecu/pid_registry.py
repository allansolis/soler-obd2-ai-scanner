"""
Registro completo de comandos OBD-II con fórmulas de conversión.

Integrado de: kotlin-obd-api (eltonvs), python-OBD (barracuda-fsh/pyobd),
shchers/ecu-simulator, rzetterberg/elmobd.
extracted_group2.py (kotlin-obd-api, MacFJA/OBD2, begaz/OBDII).

Cada entrada: (nombre, modo, pid_hex, unidad, bytes_respuesta, formula)
La formula recibe list[int] de bytes raw y devuelve el valor decodificado.
"""
from __future__ import annotations

# ── Helpers integrados desde extracted_group2.py ────────────────────────────

def _signed16(msb: int, lsb: int) -> int:
    """Convierte 2 bytes a entero con signo (complemento a 2)."""
    val = (msb << 8) | lsb
    return val - 65536 if val >= 32768 else val


_SEC_AIR_STATUS = {
    0x01: "UPSTREAM",
    0x02: "DOWNSTREAM_CATALYST",
    0x04: "ATMOSPHERE_OFF",
    0x08: "PUMP_COMMANDED_ON",
}

_OBD_STANDARD = {
    0x01: "OBD-II (CARB)",        0x02: "OBD (EPA)",
    0x03: "OBD and OBD-II",       0x04: "OBD-I",
    0x05: "Not OBD compliant",    0x06: "EOBD (Europe)",
    0x07: "EOBD and OBD-II",      0x08: "EOBD and OBD",
    0x09: "EOBD, OBD and OBD-II", 0x0A: "JOBD (Japan)",
    0x0B: "JOBD and OBD-II",      0x0C: "JOBD and EOBD",
    0x0D: "JOBD, EOBD and OBD-II",
    0x11: "EMD (Engine Manufacturer Diagnostics)",
    0x12: "EMD+ (Enhanced EMD)",  0x13: "HD OBD-C (Heavy Duty)",
    0x14: "HD OBD (Heavy Duty)",  0x15: "WWH OBD (World Wide Harmonized)",
    0x17: "HD EOBD-I",            0x18: "HD EOBD-II",
    0x19: "HD EOBD-I N",          0x1A: "HD EOBD-II N",
    0x1C: "OBD BR1 (Brazil)",     0x1D: "OBD BR2 (Brazil)",
    0x1E: "KOBD (Korea)",         0x1F: "IOBD-I (India)",
    0x20: "IOBD-II (India)",      0x21: "HD EOBD-IV",
}

# ─────────────────────────────────────────────────────────────────────────────

FUEL_TYPE_MAP = {
    0x01: "Gasoline",         0x02: "Methanol",
    0x03: "Ethanol",          0x04: "Diesel",
    0x05: "GPL/LPG",          0x06: "Natural Gas",
    0x07: "Propane",          0x08: "Electric",
    0x09: "Bifuel Gasoline",  0x0A: "Bifuel Methanol",
    0x0B: "Bifuel Ethanol",   0x0C: "Bifuel LPG",
    0x0D: "Bifuel Natural Gas", 0x0E: "Bifuel Propane",
    0x0F: "Bifuel Electric",  0x10: "Bifuel Gasoline/Electric",
    0x11: "Hybrid Gasoline",  0x12: "Hybrid Ethanol",
    0x13: "Hybrid Diesel",    0x14: "Hybrid Electric",
    0x15: "Hybrid Mixed",     0x16: "Hybrid Regenerative",
}

# Tabla principal: pid_int -> (nombre, modo, pid_hex, unidad, bytes_min, formula)
OBD_COMMANDS: dict[int, tuple] = {
    # ── Modo 01 — Datos en tiempo real ──────────────────────────────────────
    0x04: ("engine_load",          "01", "04", "%",    1, lambda b: b[0] * 100 / 255),
    0x05: ("coolant_temp",         "01", "05", "°C",   1, lambda b: b[0] - 40),
    0x06: ("fuel_trim_st_b1",      "01", "06", "%",    1, lambda b: (b[0] - 128) * 100 / 128),
    0x07: ("fuel_trim_lt_b1",      "01", "07", "%",    1, lambda b: (b[0] - 128) * 100 / 128),
    0x08: ("fuel_trim_st_b2",      "01", "08", "%",    1, lambda b: (b[0] - 128) * 100 / 128),
    0x09: ("fuel_trim_lt_b2",      "01", "09", "%",    1, lambda b: (b[0] - 128) * 100 / 128),
    0x0A: ("fuel_pressure",        "01", "0A", "kPa",  1, lambda b: b[0] * 3),
    0x0B: ("map_kpa",              "01", "0B", "kPa",  1, lambda b: b[0]),
    0x0C: ("rpm",                  "01", "0C", "RPM",  2, lambda b: (b[0] * 256 + b[1]) / 4),
    0x0D: ("speed",                "01", "0D", "km/h", 1, lambda b: b[0]),
    0x0E: ("ignition_advance",     "01", "0E", "°",    1, lambda b: b[0] / 2 - 64),
    0x0F: ("iat",                  "01", "0F", "°C",   1, lambda b: b[0] - 40),
    0x10: ("maf",                  "01", "10", "g/s",  2, lambda b: (b[0] * 256 + b[1]) / 100),
    0x11: ("throttle",             "01", "11", "%",    1, lambda b: b[0] * 100 / 255),
    0x14: ("o2_b1s1_v",            "01", "14", "V",    2, lambda b: b[0] / 200),
    0x15: ("o2_b1s2_v",            "01", "15", "V",    2, lambda b: b[0] / 200),
    0x16: ("o2_b2s1_v",            "01", "16", "V",    2, lambda b: b[0] / 200),
    0x17: ("o2_b2s2_v",            "01", "17", "V",    2, lambda b: b[0] / 200),
    0x1F: ("runtime",              "01", "1F", "s",    2, lambda b: b[0] * 256 + b[1]),
    0x21: ("mil_distance",         "01", "21", "km",   2, lambda b: b[0] * 256 + b[1]),
    0x22: ("fuel_rail_p_vac",      "01", "22", "kPa",  2, lambda b: (b[0] * 256 + b[1]) * 0.079),
    0x23: ("fuel_rail_p_dir",      "01", "23", "kPa",  2, lambda b: (b[0] * 256 + b[1]) * 10),
    0x2C: ("egr_cmd",              "01", "2C", "%",    1, lambda b: b[0] * 100 / 255),
    0x2D: ("egr_error",            "01", "2D", "%",    1, lambda b: (b[0] - 128) * 100 / 128),
    0x2E: ("evap_purge",           "01", "2E", "%",    1, lambda b: b[0] * 100 / 255),
    0x2F: ("fuel_level",           "01", "2F", "%",    1, lambda b: b[0] * 100 / 255),
    0x30: ("warmups_since_clr",    "01", "30", "cnt",  1, lambda b: b[0]),
    0x31: ("dist_dtc_clear",       "01", "31", "km",   2, lambda b: b[0] * 256 + b[1]),
    0x33: ("baro_kpa",             "01", "33", "kPa",  1, lambda b: b[0]),
    0x3C: ("catalyst_temp_b1s1",   "01", "3C", "°C",   2, lambda b: (b[0] * 256 + b[1]) / 10 - 40),
    0x3D: ("catalyst_temp_b2s1",   "01", "3D", "°C",   2, lambda b: (b[0] * 256 + b[1]) / 10 - 40),
    0x3E: ("catalyst_temp_b1s2",   "01", "3E", "°C",   2, lambda b: (b[0] * 256 + b[1]) / 10 - 40),
    0x3F: ("catalyst_temp_b2s2",   "01", "3F", "°C",   2, lambda b: (b[0] * 256 + b[1]) / 10 - 40),
    0x42: ("ctrl_voltage",         "01", "42", "V",    2, lambda b: (b[0] * 256 + b[1]) / 1000),
    0x43: ("abs_load",             "01", "43", "%",    2, lambda b: (b[0] * 256 + b[1]) * 100 / 255),
    0x44: ("lambda_eq_ratio",      "01", "44", "",     2, lambda b: (b[0] * 256 + b[1]) / 32768),
    0x45: ("rel_throttle",         "01", "45", "%",    1, lambda b: b[0] * 100 / 255),
    0x46: ("ambient_temp",         "01", "46", "°C",   1, lambda b: b[0] - 40),
    0x47: ("throttle_pos_b",       "01", "47", "%",    1, lambda b: b[0] * 100 / 255),
    0x49: ("accel_pos_d",          "01", "49", "%",    1, lambda b: b[0] * 100 / 255),
    0x4A: ("accel_pos_e",          "01", "4A", "%",    1, lambda b: b[0] * 100 / 255),
    0x4B: ("throttle_act",         "01", "4B", "%",    1, lambda b: b[0] * 100 / 255),
    0x4D: ("time_mil_on",          "01", "4D", "min",  2, lambda b: b[0] * 256 + b[1]),
    0x4E: ("time_dtc_clear",       "01", "4E", "min",  2, lambda b: b[0] * 256 + b[1]),
    0x51: ("fuel_type",            "01", "51", "",     1, lambda b: FUEL_TYPE_MAP.get(b[0], f"type_{b[0]}")),
    0x52: ("ethanol_pct",          "01", "52", "%",    1, lambda b: b[0] * 100 / 255),
    0x5C: ("oil_temp",             "01", "5C", "°C",   1, lambda b: b[0] - 40),
    0x5D: ("fuel_inj_timing",      "01", "5D", "°",    2, lambda b: (b[0] * 256 + b[1]) / 128 - 210),
    0x5E: ("fuel_rate",            "01", "5E", "L/h",  2, lambda b: (b[0] * 256 + b[1]) * 0.05),
    0x5F: ("emission_req",         "01", "5F", "",     1, lambda b: b[0]),
    0x61: ("torque_demand",        "01", "61", "%",    1, lambda b: b[0] - 125),
    0x62: ("torque_actual",        "01", "62", "%",    1, lambda b: b[0] - 125),
    0x63: ("torque_ref",           "01", "63", "Nm",   2, lambda b: b[0] * 256 + b[1]),
    0x67: ("coolant_temp2",        "01", "67", "°C",   3, lambda b: b[1] - 40),
    0x6D: ("oil_pressure",         "01", "6D", "kPa",  5, lambda b: b[2]),
    # Modo extendido (ISO 15765 extended PIDs)
    0xA6: ("odometer",             "01", "A6", "km",   4, lambda b: (b[0]<<24|b[1]<<16|b[2]<<8|b[3]) / 10),

    # ── PIDs integrados desde extracted_group2.py ────────────────────────────
    # Fuentes: kotlin-obd-api, MacFJA/OBD2, begaz/OBDII
    # PID 0x02: DTC que causó el freeze frame (Mode 02 PID 0x02 reporta esto)
    0x02: ("freeze_dtc",            "01", "02", "",    2,
           lambda b: f"{b[0]:02X}{b[1]:02X}" if len(b) >= 2 else ""),
    # PID 0x03: Estado del sistema de combustible (banco 1 y banco 2)
    0x03: ("fuel_system_status",    "01", "03", "",    2,
           lambda b: f"B1:{b[0]:02X} B2:{b[1]:02X}" if len(b) >= 2 else f"{b[0]:02X}"),
    # PID 0x12: Estado del aire secundario
    0x12: ("sec_air_status",        "01", "12", "",    1,
           lambda b: _SEC_AIR_STATUS.get(b[0], f"0x{b[0]:02X}")),
    # PID 0x13: Sensores O2 presentes (configuración 2 bancos)
    0x13: ("o2_sensors_2bank",      "01", "13", "",    1,
           lambda b: b[0]),
    # PIDs 0x18-0x1B: Voltaje O2 — sensores adicionales banco 2 y banco 3
    0x18: ("o2_b2s3_v",             "01", "18", "V",   2,
           lambda b: round(b[0] / 200, 3)),
    0x19: ("o2_b2s4_v",             "01", "19", "V",   2,
           lambda b: round(b[0] / 200, 3)),
    0x1A: ("o2_b3s1_v",             "01", "1A", "V",   2,
           lambda b: round(b[0] / 200, 3)),
    0x1B: ("o2_b3s2_v",             "01", "1B", "V",   2,
           lambda b: round(b[0] / 200, 3)),
    # PID 0x1C: Estándar OBD de conformidad del vehículo
    0x1C: ("obd_standard",          "01", "1C", "",    1,
           lambda b: _OBD_STANDARD.get(b[0], f"OBD-{b[0]}")),
    # PID 0x1D: Sensores O2 presentes (configuración 4 bancos)
    0x1D: ("o2_sensors_4bank",      "01", "1D", "",    1,
           lambda b: b[0]),
    # PID 0x1E: Estado de la entrada auxiliar (PTO activo/inactivo)
    0x1E: ("aux_input_status",      "01", "1E", "",    1,
           lambda b: "PTO_ACTIVE" if b[0] & 0x01 else "PTO_INACTIVE"),
    # PIDs 0x24-0x2B: Wideband O2 — Equivalence Ratio (todos los bancos/sensores)
    0x24: ("o2_wb_b1s1_ratio",      "01", "24", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x25: ("o2_wb_b1s2_ratio",      "01", "25", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x26: ("o2_wb_b2s1_ratio",      "01", "26", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x27: ("o2_wb_b2s2_ratio",      "01", "27", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x28: ("o2_wb_b3s1_ratio",      "01", "28", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x29: ("o2_wb_b3s2_ratio",      "01", "29", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x2A: ("o2_wb_b4s1_ratio",      "01", "2A", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x2B: ("o2_wb_b4s2_ratio",      "01", "2B", "",    4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    # PID 0x32: Evap System Vapor Pressure con signo (Pa)
    0x32: ("evap_vapor_pres_signed","01", "32", "Pa",  2,
           lambda b: round(_signed16(b[0], b[1]) / 4, 2)),
    # PID 0x34: Wideband O2 B1S1 con corriente (mA) — precede a 0x35-0x3B
    0x34: ("o2_wb_b1s1_curr",       "01", "34", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    # PIDs 0x35-0x3B: Wideband O2 con corriente — todos los bancos/sensores
    0x35: ("o2_wb_b1s2_curr",       "01", "35", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x36: ("o2_wb_b2s1_curr",       "01", "36", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x37: ("o2_wb_b2s2_curr",       "01", "37", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x38: ("o2_wb_b3s1_curr",       "01", "38", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x39: ("o2_wb_b3s2_curr",       "01", "39", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x3A: ("o2_wb_b4s1_curr",       "01", "3A", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x3B: ("o2_wb_b4s2_curr",       "01", "3B", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    # PID 0x41: Monitor Status Ciclo de Conducción Actual (raw — usar decode_monitor_status)
    0x41: ("monitor_status_drv",    "01", "41", "",    4,
           lambda b: b),
    # PID 0x48: Posición Acelerador C (absoluta)
    0x48: ("throttle_pos_c",        "01", "48", "%",   1,
           lambda b: round(b[0] * 100 / 255, 2)),
    # PID 0x4C: Actuador de Acelerador Comandado
    0x4C: ("throttle_actuator",     "01", "4C", "%",   1,
           lambda b: round(b[0] * 100 / 255, 2)),
    # PID 0x4F: Valores máximos de equivalencia, O2 voltaje, corriente y MAP
    0x4F: ("max_values",            "01", "4F", "",    4,
           lambda b: {"max_equiv_ratio": b[0], "max_o2_v": b[1],
                      "max_o2_ma": b[2], "max_map_kpa": b[3] * 10}),
    # PID 0x50: MAF máximo soportado por el sensor
    0x50: ("max_maf",               "01", "50", "g/s", 4,
           lambda b: b[0] * 10),
    # PID 0x53: Evap System Vapor Pressure (sin signo)
    0x53: ("evap_vapor_pres",       "01", "53", "Pa",  2,
           lambda b: round((b[0]*256+b[1]) / 200, 2)),
    # PID 0x54: Evap System Vapor Pressure (con signo, versión 2)
    0x54: ("evap_vapor_pres_b",     "01", "54", "Pa",  2,
           lambda b: (b[0]*256 + b[1]) - 32767),
    # PIDs 0x55-0x58: Secondary O2 Sensor Trim (banks 1-4)
    0x55: ("o2_trim_st_b1b3",       "01", "55", "%",   2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x56: ("o2_trim_lt_b1b3",       "01", "56", "%",   2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x57: ("o2_trim_st_b2b4",       "01", "57", "%",   2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x58: ("o2_trim_lt_b2b4",       "01", "58", "%",   2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    # PID 0x59: Fuel Rail Absolute Pressure
    0x59: ("fuel_rail_abs_pres",    "01", "59", "kPa", 2,
           lambda b: (b[0]*256 + b[1]) * 10),
    # PID 0x5A: Posición Acelerador Relativa
    0x5A: ("accel_rel",             "01", "5A", "%",   1,
           lambda b: round(b[0] * 100 / 255, 2)),
    # PID 0x5B: Vida útil restante de la batería híbrida
    0x5B: ("hybrid_batt_life",      "01", "5B", "%",   1,
           lambda b: round(b[0] * 100 / 255, 2)),
}

# ── Modo 09 — Información del vehículo ──────────────────────────────────────
VEHICLE_INFO_PIDS: dict[int, tuple] = {
    # PID 0x01: VIN Message Count (sólo ISO9141/KWP2000, previo al VIN real)
    0x01: ("vin_msg_count",    "09", "01", "",   1,
           lambda b: b[0]),
    0x02: ("vin",              "09", "02", "",  20,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
    0x04: ("calibration_id",   "09", "04", "",  16,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
    0x06: ("cvn",              "09", "06", "",   4,
           lambda b: "".join(f"{x:02X}" for x in b)),
    # PID 0x08: In-use Performance Tracking (motores gasolina)
    0x08: ("perf_tracking_spark", "09", "08", "", 4,
           lambda b: {"ignition_counter": b[0]*256+b[1], "catalyst_monitor": b[2]*256+b[3]}),
    # PID 0x09: In-use Performance Tracking (motores diesel/compresión)
    0x09: ("perf_tracking_compression", "09", "09", "", 4,
           lambda b: {"ignition_counter": b[0]*256+b[1], "nox_monitor": b[2]*256+b[3]}),
    0x0A: ("ecu_name",         "09", "0A", "",  20,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
}


def decode(pid: int, raw_bytes: list[int]) -> dict:
    """Decodifica raw bytes para un PID dado. Devuelve dict con name/value/unit."""
    if pid in OBD_COMMANDS:
        name, mode, pid_hex, unit, _, formula = OBD_COMMANDS[pid]
        try:
            value = formula(raw_bytes)
            if isinstance(value, float):
                value = round(value, 3)
        except (IndexError, ZeroDivisionError, KeyError):
            value = None
        return {"pid": pid, "name": name, "value": value, "unit": unit, "raw": raw_bytes}
    return {"pid": pid, "name": f"PID_{pid:02X}", "value": None, "unit": "", "raw": raw_bytes}


def get_command_str(pid: int, mode: int = 1) -> str:
    """Devuelve el string de comando a enviar al ELM327."""
    if pid in OBD_COMMANDS:
        _, m, p, *_ = OBD_COMMANDS[pid]
        return f"{m}{p}"
    return f"{mode:02X}{pid:02X}"


ALL_MODE01_PIDS   = sorted(OBD_COMMANDS.keys())
ALL_MODE09_PIDS   = sorted(VEHICLE_INFO_PIDS.keys())
