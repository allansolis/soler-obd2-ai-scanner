"""
Registro de PIDs para vehículos eléctricos e híbridos.

Fuentes:
- SAE J1979-2: PIDs estándar OBD-II para EVs (Mode 0x01 extendido)
- ISO 14229 UDS Mode 0x22 ReadDataByIdentifier — por marca
- openVehicles.com / EVDash community DBC collections
- Nissan Leaf (ZE0/AZE0/ZE1): EV-SMART project
- Chevy Bolt EV (BEV): GM E-net community
- BMW i3/iX/i4: BIMMERCODE/bimmerpost
- VW ID.3/ID.4 (MEB): VCDS-compatible PIDs
- Renault Zoe (R240/R300): CAN logs (anabahena/CargadoresElectricos domain context)
- Hyundai IONIQ 5/6 / Kia EV6 (E-GMP): SoulEV-forums
"""
from __future__ import annotations


def _b2(b: list[int]) -> int:
    return (b[0] << 8) | b[1]


def _b4(b: list[int]) -> int:
    return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]


# ─── Mode 0x01 — PIDs OBD-II estándar específicos para EV/Híbrido ───────────
# Formato: pid_int -> (name, mode, pid_hex, unit, min_bytes, formula)

EV_MODE01_PIDS: dict[int, tuple] = {
    # SAE J1979-2 EVs adicionales al estándar ICE
    0x5B: ("hybrid_batt_soc",      "01", "5B", "%",      1,
           lambda b: round(b[0] * 100 / 255, 1)),
    0x7B: ("battery_temp",         "01", "7B", "°C",     3,
           lambda b: b[1] - 40),
    # SAE J1979-2 motor eléctrico
    0x9A: ("ev_motor_torque",      "01", "9A", "Nm",     2,
           lambda b: (_b2(b) / 4) - 8000),
    0x9C: ("ev_motor_rpm",         "01", "9C", "RPM",    2,
           lambda b: _b2(b) - 32767),
    # Potencia tren eléctrico (kW)
    0x9D: ("ev_power_kw",          "01", "9D", "kW",     2,
           lambda b: (_b2(b) - 32767) / 8),
    # Rango estimado restante
    0x9E: ("ev_range_km",          "01", "9E", "km",     2,
           lambda b: _b2(b) * 0.1),
    # Estado de carga activa
    0x9F: ("ev_charging_status",   "01", "9F", "",       1,
           lambda b: {
               0x00: "NOT_CHARGING",
               0x01: "AC_L1",
               0x02: "AC_L2",
               0x03: "AC_L3",
               0x04: "DC_CCS",
               0x05: "DC_CHADEMO",
               0x06: "DC_TESLA",
               0x07: "INDUCTIVE",
           }.get(b[0], f"UNKNOWN_0x{b[0]:02X}")),
    # Voltaje del pack de baterías (OBD estándar — algunos fabricantes)
    0xA0: ("ev_pack_voltage",      "01", "A0", "V",      2,
           lambda b: _b2(b) * 0.1),
    # Corriente del pack (con signo: + carga, - descarga)
    0xA1: ("ev_pack_current",      "01", "A1", "A",      2,
           lambda b: (_b2(b) - 32767) * 0.1),
}

# ─── Mode 0x22 UDS — PIDs por marca ─────────────────────────────────────────
# Formato: identifier_hex (2 bytes) -> (name, unit, min_bytes, formula)
# Cada entrada está bajo su clave de marca (EV_BRANDS)

EV_UDS_PIDS: dict[str, dict[str, tuple]] = {

    # ── Nissan Leaf ZE0 / AZE0 / ZE1 ────────────────────────────────────────
    "Nissan_Leaf": {
        "0105": ("bms_batt_temp_max",   "°C",  1, lambda b: b[0] - 40),
        "0106": ("bms_batt_temp_min",   "°C",  1, lambda b: b[0] - 40),
        "0104": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "010D": ("bms_hx",              "%",   2, lambda b: round(_b2(b) / 100, 2)),
        "0101": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.005, 2)),
        "010B": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.1, 2)),
        "0102": ("bms_max_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.002, 4)),
        "0103": ("bms_min_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.002, 4)),
        "0120": ("motor_temp",          "°C",  1, lambda b: b[0] - 40),
        "0121": ("inverter_temp",       "°C",  1, lambda b: b[0] - 40),
        "030B": ("odometer_km",         "km",  4, lambda b: _b4(b)),
    },

    # ── Chevrolet Bolt EV / Volt (GM E-net, ECU 0x7E4) ───────────────────────
    "Chevrolet_Bolt": {
        "D0C0": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "D002": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.0625, 2)),
        "D004": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.125, 2)),
        "D005": ("bms_temp_max",        "°C",  1, lambda b: b[0] - 40),
        "D006": ("bms_temp_min",        "°C",  1, lambda b: b[0] - 40),
        "D003": ("bms_max_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.0002, 4)),
        "D007": ("bms_soh",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "D008": ("bms_charge_power",    "kW",  2, lambda b: round(_b2(b) * 0.1, 2)),
        "D009": ("motor_temp",          "°C",  1, lambda b: b[0] - 40),
    },

    # ── BMW i3 / i4 / iX (SME: Speicher-Managementsystem-Elektronik) ─────────
    "BMW_i3": {
        "DD03": ("bms_soc",             "%",   1, lambda b: round(b[0] * 100 / 255, 1)),
        "DD01": ("bms_temp",            "°C",  1, lambda b: b[0] - 40),
        "DD57": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.0625, 2)),
        "DD04": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32767) * 0.1, 2)),
        "DD11": ("bms_soh",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "DD12": ("bms_max_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "DD13": ("bms_min_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "DD30": ("motor_temp",          "°C",  1, lambda b: b[0] - 40),
        "DD31": ("inverter_temp",       "°C",  1, lambda b: b[0] - 40),
        "DD21": ("charge_session_kwh",  "kWh", 2, lambda b: round(_b2(b) * 0.1, 2)),
        "DD22": ("charge_power_kw",     "kW",  2, lambda b: round(_b2(b) * 0.1, 2)),
        "DD40": ("range_km",            "km",  2, lambda b: round(_b2(b) * 0.1, 1)),
    },

    # ── VW ID.3 / ID.4 / ID.5 / Cupra Born (MEB platform) ───────────────────
    "VW_MEB": {
        "030A": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "0307": ("bms_temp_max",        "°C",  1, lambda b: b[0] - 40),
        "0308": ("bms_temp_min",        "°C",  1, lambda b: b[0] - 40),
        "0301": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.1, 2)),
        "0302": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.1, 2)),
        "0309": ("bms_soh",             "%",   2, lambda b: round(_b2(b) / 256, 1)),
        "030C": ("bms_max_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "030D": ("bms_min_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "0412": ("motor_temp",          "°C",  1, lambda b: b[0] - 40),
        "0413": ("inverter_temp",       "°C",  1, lambda b: b[0] - 40),
        "0320": ("charge_power_kw",     "kW",  2, lambda b: round(_b2(b) * 0.1, 2)),
        "0321": ("charge_session_kwh",  "kWh", 2, lambda b: round(_b2(b) * 0.1, 2)),
        "0325": ("dc_inlet_voltage",    "V",   2, lambda b: round(_b2(b) * 0.5, 2)),
        "0326": ("dc_inlet_current",    "A",   2, lambda b: round(_b2(b) * 0.25, 2)),
    },

    # ── Renault Zoe R240 / R300 / ZE50 ───────────────────────────────────────
    "Renault_Zoe": {
        "920A": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "920C": ("bms_usable_soc",      "%",   1, lambda b: round(b[0] / 2, 1)),
        "9201": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.001, 3)),
        "9204": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.001, 3)),
        "9203": ("bms_temp_max",        "°C",  1, lambda b: b[0] - 40),
        "9206": ("bms_soh",             "%",   2, lambda b: round(_b2(b) / 100, 2)),
        "9301": ("motor_speed",         "RPM", 2, lambda b: (_b2(b) - 32768) * 2),
        "9302": ("motor_torque",        "Nm",  2, lambda b: (_b2(b) - 32768) * 0.1),
        "8005": ("charger_power_kw",    "kW",  2, lambda b: round(_b2(b) * 0.1, 2)),
    },

    # ── Hyundai IONIQ 5 / IONIQ 6 / Kia EV6 (E-GMP platform) ────────────────
    "Hyundai_EGMP": {
        "0101": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "0105": ("bms_max_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "0106": ("bms_min_cell_v",      "V",   2, lambda b: round(_b2(b) * 0.001, 4)),
        "0102": ("bms_temp_max",        "°C",  1, lambda b: b[0] - 40),
        "0103": ("bms_temp_min",        "°C",  1, lambda b: b[0] - 40),
        "0104": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.1, 2)),
        "010B": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.1, 2)),
        "0112": ("bms_soh",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "0201": ("motor_temp",          "°C",  1, lambda b: b[0] - 40),
        "0205": ("inverter_temp",       "°C",  1, lambda b: b[0] - 40),
        "0501": ("charge_power_kw",     "kW",  2, lambda b: round(_b2(b) * 0.1, 2)),
        "0502": ("charge_session_kwh",  "kWh", 2, lambda b: round(_b2(b) * 0.1, 2)),
        "0503": ("dc_inlet_voltage",    "V",   2, lambda b: round(_b2(b) * 0.5, 2)),
        "0504": ("dc_inlet_current",    "A",   2, lambda b: round(_b2(b) * 0.25, 2)),
        "0505": ("charge_time_min",     "min", 2, lambda b: _b2(b)),
    },

    # ── Tesla Model 3/Y/S/X (vía CAN OBD gateway — acceso limitado) ──────────
    "Tesla_OBD": {
        "0132": ("bms_soc",             "%",   1, lambda b: round(b[0] / 2, 1)),
        "0131": ("bms_pack_voltage",    "V",   2, lambda b: round(_b2(b) * 0.01, 2)),
        "0133": ("bms_current",         "A",   2, lambda b: round((_b2(b) - 32768) * 0.1, 2)),
        "0134": ("bms_temp",            "°C",  1, lambda b: b[0] - 40),
        "0135": ("motor_rpm",           "RPM", 2, lambda b: _b2(b) * 2),
        "0141": ("range_km",            "km",  2, lambda b: round(_b2(b) * 0.1, 1)),
    },
}

# Catálogo de marcas con metadatos
EV_BRANDS: dict[str, dict] = {
    "Nissan_Leaf":      {"ecu_addr": 0x79B, "protocol": "ISO15765", "platform": "ZE0/AZE0/ZE1"},
    "Chevrolet_Bolt":   {"ecu_addr": 0x7E4, "protocol": "ISO15765", "platform": "BOLT_EV/VOLT"},
    "BMW_i3":           {"ecu_addr": 0x7E3, "protocol": "ISO15765", "platform": "i3/i4/iX"},
    "VW_MEB":           {"ecu_addr": 0x7E4, "protocol": "ISO15765", "platform": "ID.3/ID.4/ID.5"},
    "Renault_Zoe":      {"ecu_addr": 0x7EC, "protocol": "ISO15765", "platform": "R240/R300/ZE50"},
    "Hyundai_EGMP":     {"ecu_addr": 0x7E4, "protocol": "ISO15765", "platform": "IONIQ5/6/EV6"},
    "Tesla_OBD":        {"ecu_addr": 0x7E1, "protocol": "ISO15765", "platform": "Model3/Y/S/X"},
}


def decode_ev(brand: str, identifier_hex: str, raw_bytes: list[int]) -> dict:
    """
    Decodifica una respuesta UDS Mode 0x22 para un EV.

    Args:
        brand:          clave en EV_BRANDS / EV_UDS_PIDS
        identifier_hex: 4 caracteres hex (p.ej. "0104")
        raw_bytes:      bytes de respuesta sin el header UDS

    Returns:
        dict con name, value, unit, brand, identifier
    """
    pid_map = EV_UDS_PIDS.get(brand, {})
    key = identifier_hex.upper()
    if key in pid_map:
        name, unit, min_bytes, formula = pid_map[key]
        try:
            value = formula(raw_bytes) if len(raw_bytes) >= min_bytes else None
        except (IndexError, ZeroDivisionError, ValueError):
            value = None
        return {
            "brand": brand, "identifier": key,
            "name": name, "value": value, "unit": unit, "raw": raw_bytes,
        }
    return {
        "brand": brand, "identifier": key,
        "name": f"UNKNOWN_{key}", "value": None, "unit": "", "raw": raw_bytes,
    }
