"""
Registro completo de comandos OBD-II con fórmulas de conversión.

Integrado de: kotlin-obd-api (eltonvs), python-OBD (barracuda-fsh/pyobd),
shchers/ecu-simulator, rzetterberg/elmobd.

Cada entrada: (nombre, modo, pid_hex, unidad, bytes_respuesta, formula)
La formula recibe list[int] de bytes raw y devuelve el valor decodificado.
"""
from __future__ import annotations

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
}

# ── Modo 09 — Información del vehículo ──────────────────────────────────────
VEHICLE_INFO_PIDS: dict[int, tuple] = {
    0x02: ("vin",              "09", "02", "",  20,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
    0x04: ("calibration_id",   "09", "04", "",  16,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
    0x06: ("cvn",              "09", "06", "",   4,
           lambda b: "".join(f"{x:02X}" for x in b)),
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


ALL_MODE01_PIDS = sorted(OBD_COMMANDS.keys())
