"""
extracted_group2.py — Funciones y PIDs extraídos de 4 repos OBD-II (Grupo 2)
=============================================================================

Fuentes revisadas y analizadas una a una:
  REPO 1: https://github.com/eltonvs/kotlin-obd-api
          → Parser DTC tri-protocolo (CAN one-frame / CAN multi-frame / ISO9141)
          → Decoder readiness monitors completo (spark + compression ignition)
          → Parser VIN dual-protocolo (CAN vs ISO9141/KWP2000)
          → Pipeline de limpieza de respuestas ELM327
          → Permanent DTCs (Mode 0A) con regex correctos
          → Detección de errores negativos (7F 0x 11/12)

  REPO 2: https://github.com/barracuda-fsh/pyobd
          → Tabla de sensores (cobertura general Mode 01)
          → Referencia para freeze frame display
          → No aporta parsing propio (delega a python-obd)

  REPO 3: https://github.com/MacFJA/OBD2
          → FrozeCommand (Mode 02): patrón elegante para freeze frame
          → Mode 09 extendido: VINMessageCount (PID 0x01), ECUName
          → PIDs Mode 01 faltantes: 0x12-0x1E, 0x24-0x2B, 0x32, 0x35-0x3B,
            0x41, 0x48, 0x4C, 0x4F, 0x50, 0x54-0x5B (17+ PIDs nuevos)

  REPO 4: https://github.com/begaz/OBDII
          → fMaf/fFuel: cálculo de MAF desde física (RPM + MAP + IAT)
          → Parser de frames de respuesta ELM327 genérico
          → Algoritmo DTC por bits (binario a código alfanumérico)

Integrar en el proyecto:
  from scaner_soler.comm.extracted_group2 import (
      clean_elm327_response,
      parse_dtcs_robust,
      parse_permanent_dtcs,
      decode_monitor_status,
      parse_vin_robust,
      build_freeze_frame_command,
      decode_freeze_frame_pid,
      EXTENDED_MODE01_PIDS,
      MODE09_EXTENDED_PIDS,
      detect_elm327_error,
      maf_from_physics,
      fuel_rate_from_physics,
  )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 1. CONSTANTES DE ERROR ELM327 (kotlin-obd-api → RegexPatterns.kt)
# ---------------------------------------------------------------------------

ELM_ERROR_PATTERNS = (
    "BUS INIT... ERROR",
    "UNABLE TO CONNECT",
    "NO DATA",
    "STOPPED",
    "ERROR",
    "?",
)

# Respuesta negativa ISO 15765: 7F <SID> 11 ó 12 (servicio no soportado / condición errónea)
_NEG_RESPONSE_RE = re.compile(r"7F\s*0[0-9A-Fa-f]\s*1[12]", re.IGNORECASE)

# Patrones de limpieza
_WHITESPACE_RE    = re.compile(r"\s")
_BUS_INIT_RE      = re.compile(r"(BUS INIT)|BUSINIT|\.")
_SEARCHING_RE     = re.compile(r"SEARCHING")
_CARRIAGE_RE      = re.compile(r"[\r\n]")
_CARRIAGE_COLON_RE = re.compile(r"[\r\n].:")
_COLON_RE         = re.compile(r":")


def detect_elm327_error(raw: str) -> str | None:
    """
    Detecta si la respuesta ELM327 contiene un error.
    Devuelve el tipo de error como string, o None si la respuesta es válida.

    Fuente: kotlin-obd-api RegexPatterns.kt + Exceptions.kt
    """
    upper = raw.upper().strip()
    if _NEG_RESPONSE_RE.search(upper):
        return "NEGATIVE_RESPONSE"  # 7F 0x 11/12 — servicio no soportado
    for pat in ELM_ERROR_PATTERNS:
        if pat in upper:
            return pat.replace("...", "").strip().replace(" ", "_")
    return None


def clean_elm327_response(raw: str) -> str:
    """
    Pipeline de limpieza de respuesta ELM327 en 4 pasos (orden importa).
    Fuente: kotlin-obd-api Response.kt → valueProcessorPipeline

    Pasos:
      1. Elimina todos los espacios en blanco
      2. Elimina prefijos de BUS INIT / puntos de eco
      3. Elimina separadores ':'  (CAN multi-frame)
      4. Elimina retornos de carro
    """
    s = raw
    s = _WHITESPACE_RE.sub("", s)
    s = _BUS_INIT_RE.sub("", s)
    s = _SEARCHING_RE.sub("", s)
    s = _COLON_RE.sub("", s)
    s = _CARRIAGE_RE.sub("", s)
    return s.upper()


def raw_to_int_list(cleaned: str) -> list[int]:
    """
    Convierte string hexadecimal limpio a lista de ints.
    Ejemplo: "41040F" → [0x41, 0x04, 0x0F]

    Fuente: kotlin-obd-api Response.kt → bufferedValue
    """
    try:
        return [int(cleaned[i:i+2], 16) for i in range(0, len(cleaned) - 1, 2)]
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# 2. PARSER DTC TRI-PROTOCOLO (kotlin-obd-api TroubleCodes.kt)
# ---------------------------------------------------------------------------

_DTC_LETTERS = ("P", "C", "B", "U")

# Constantes de frame CAN (de TroubleCodes.kt)
_CAN_ONE_FRAME_MAX_LEN = 16      # ≤ 16 chars → one-frame
_DTC_HEX_CHUNK         = 4       # cada DTC = 4 chars hex
_CAN_ONE_FRAME_HDR     = 4       # header "43yy"
_CAN_MULTI_FRAME_HDR   = 7       # header "xxx43yy"


def _decode_dtc_chunk(chunk: str) -> str:
    """Convierte 4 chars hex en un código DTC tipo P0100. Fuente: kotlin-obd-api"""
    if len(chunk) < 4:
        return ""
    b1 = int(chunk[0], 16)
    letter = _DTC_LETTERS[(b1 >> 2) & 0x03]
    digit2 = format(b1 & 0x03, "X")
    rest   = chunk[1:4].upper()
    return f"{letter}{digit2}{rest}".ljust(5, "0")[:5]


def parse_dtcs_robust(raw_response: str, mode: str = "03") -> list[str]:
    """
    Parser DTC robusto tri-protocolo.
    Soporta: CAN one-frame, CAN multi-frame, ISO9141-2 / KWP2000.

    Fuente: kotlin-obd-api BaseTroubleCodesCommand.parseTroubleCodesList()

    Args:
        raw_response: respuesta cruda del ELM327 (antes de limpiar)
        mode: "03" (stored), "07" (pending), "0A" (permanent)

    Returns:
        Lista de strings tipo ["P0300", "C0010", ...]
    """
    # Prefijos de respuesta según modo: 03→43, 07→47, 0A→4A
    mode_upper = mode.upper()
    resp_prefix = format(int(mode_upper, 16) + 0x40, "02X")  # 03→43, 07→47, 0A→4A

    # Limpieza básica de espacios
    clean_ws = _WHITESPACE_RE.sub("", raw_response.upper())

    # Detectar protocolo y extraer payload
    if len(clean_ws) <= _CAN_ONE_FRAME_MAX_LEN and len(clean_ws) % _DTC_HEX_CHUNK == 0:
        # CAN one-frame: "43yy[codes]"
        payload = clean_ws[_CAN_ONE_FRAME_HDR:]
    elif ":" in raw_response:
        # CAN multi-frame: "xxx43yy[codes]" con separadores ':'
        no_cr_colon = _CARRIAGE_COLON_RE.sub("", raw_response.upper())
        no_ws = _WHITESPACE_RE.sub("", no_cr_colon)
        payload = no_ws[_CAN_MULTI_FRAME_HDR:]
    else:
        # ISO9141-2, KWP2000 Fast/5Kbps: strip prefijos de línea "43" ó "47" ó "4A"
        stripped = re.sub(
            rf"^{resp_prefix}|[\r\n]{resp_prefix}|[\r\n]",
            "",
            raw_response.upper(),
        )
        payload = _WHITESPACE_RE.sub("", stripped)

    if not payload:
        return []

    # Decodificar chunks de 4 chars
    codes = [_decode_dtc_chunk(payload[i:i+4]) for i in range(0, len(payload), 4)]

    # Filtrar P0000 (padding) y cadenas vacías
    codes = [c for c in codes if c and c != "P0000"]

    return codes


def parse_permanent_dtcs(raw_response: str) -> list[str]:
    """
    Parser específico para Mode 0A (DTCs permanentes / confirmados).
    Los DTCs permanentes no se borran con AT FI ni con "04". Solo desaparecen
    cuando la ECU verifica que el fallo fue resuelto en un drive cycle completo.

    Fuente: kotlin-obd-api PermanentTroubleCodesCommand
    """
    return parse_dtcs_robust(raw_response, mode="0A")


# ---------------------------------------------------------------------------
# 3. DECODER MONITOR READINESS (kotlin-obd-api Monitor.kt)
# ---------------------------------------------------------------------------

@dataclass
class MonitorStatus:
    available: bool
    complete: bool

    def __str__(self) -> str:
        if not self.available:
            return "N/A"
        return "COMPLETE" if self.complete else "INCOMPLETE"


@dataclass
class ReadinessStatus:
    """
    Estado completo de readiness monitors decodificado de PID 0x01 ó 0x41.
    Fuente: kotlin-obd-api Monitor.kt y Enums.kt
    """
    mil_on:    bool = False
    dtc_count: int  = 0
    is_spark_ignition: bool = True  # True=gasolina, False=diesel/compresión

    # Monitores comunes (ambos tipos de motor)
    misfire:               MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    fuel_system:           MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    comprehensive_comp:    MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))

    # Monitores encendido por chispa (gasolina)
    catalyst:              MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    heated_catalyst:       MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    evap_system:           MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    secondary_air:         MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    ac_refrigerant:        MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    o2_sensor:             MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    o2_sensor_heater:      MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    egr_vvt:               MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))

    # Monitores compresión (diesel)
    nmhc_catalyst:         MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    nox_scr:               MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    boost_pressure:        MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    exhaust_gas_sensor:    MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))
    pm_filter:             MonitorStatus = field(default_factory=lambda: MonitorStatus(False, False))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "mil_on":    self.mil_on,
            "dtc_count": self.dtc_count,
            "engine_type": "SPARK" if self.is_spark_ignition else "COMPRESSION",
            "misfire":            str(self.misfire),
            "fuel_system":        str(self.fuel_system),
            "comprehensive_comp": str(self.comprehensive_comp),
        }
        if self.is_spark_ignition:
            d.update({
                "catalyst":         str(self.catalyst),
                "heated_catalyst":  str(self.heated_catalyst),
                "evap_system":      str(self.evap_system),
                "secondary_air":    str(self.secondary_air),
                "ac_refrigerant":   str(self.ac_refrigerant),
                "o2_sensor":        str(self.o2_sensor),
                "o2_sensor_heater": str(self.o2_sensor_heater),
                "egr_vvt":          str(self.egr_vvt),
            })
        else:
            d.update({
                "nmhc_catalyst":      str(self.nmhc_catalyst),
                "nox_scr":            str(self.nox_scr),
                "boost_pressure":     str(self.boost_pressure),
                "exhaust_gas_sensor": str(self.exhaust_gas_sensor),
                "pm_filter":          str(self.pm_filter),
                "egr_vvt":            str(self.egr_vvt),
            })
        return d

    def all_complete(self) -> bool:
        """True si todos los monitores soportados están completos."""
        monitors = [self.misfire, self.fuel_system, self.comprehensive_comp]
        if self.is_spark_ignition:
            monitors += [
                self.catalyst, self.heated_catalyst, self.evap_system,
                self.secondary_air, self.ac_refrigerant, self.o2_sensor,
                self.o2_sensor_heater, self.egr_vvt,
            ]
        else:
            monitors += [
                self.nmhc_catalyst, self.nox_scr, self.boost_pressure,
                self.exhaust_gas_sensor, self.pm_filter, self.egr_vvt,
            ]
        return all(not m.available or m.complete for m in monitors)


def decode_monitor_status(raw_bytes: list[int]) -> ReadinessStatus:
    """
    Decodifica PID 0x01 ó 0x41 (Monitor Status).
    Acepta 4 bytes de datos (sin el echo 41 01).

    Layout del estándar SAE J1979 (PID 0x01):
      Byte 0: [MIL|DTC count (7 bits)]
      Byte 1: [X|SPARK|Components sup|Fuel sup|Misfire sup|Components rdy|Fuel rdy|Misfire rdy]
      Byte 2: availability de monitores específicos (bits 7→0)
      Byte 3: completeness de monitores específicos (bit=0 → completo)

    Fuente: kotlin-obd-api Monitor.kt → parseData()
    """
    if len(raw_bytes) < 4:
        return ReadinessStatus()

    b0, b1, b2, b3 = raw_bytes[:4]

    mil_on    = bool(b0 & 0x80)
    dtc_count = b0 & 0x7F
    is_spark  = not bool((b1 >> 3) & 0x01)  # bit 3 = 0 → spark ignition

    def _common(byte_val: int, bit_support: int, bit_ready: int) -> MonitorStatus:
        available = bool((byte_val >> (7 - bit_support)) & 1)
        complete  = not bool((byte_val >> (7 - bit_ready)) & 1)
        return MonitorStatus(available, complete)

    def _specific_avail(bit: int) -> bool:
        return bool((b2 >> (7 - bit)) & 1)

    def _specific_complete(bit: int) -> bool:
        return not bool((b3 >> (7 - bit)) & 1)

    # Monitores comunes (byte 1): bits 4,5,6 → support; bits 0,1,2 → ready
    # Byte 1 layout: X SPARK Comp-sup Fuel-sup Misfire-sup Comp-rdy Fuel-rdy Misfire-rdy
    misfire_s   = MonitorStatus(bool((b1 >> 5) & 1), not bool((b1 >> 2) & 1))
    fuel_s      = MonitorStatus(bool((b1 >> 6) & 1), not bool((b1 >> 1) & 1))
    comp_s      = MonitorStatus(bool((b1 >> 7) & 1), not bool( b1        & 1))

    rs = ReadinessStatus(
        mil_on=mil_on,
        dtc_count=dtc_count,
        is_spark_ignition=is_spark,
        misfire=misfire_s,
        fuel_system=fuel_s,
        comprehensive_comp=comp_s,
    )

    # Monitores específicos (bytes 2 y 3) — posiciones de bits según SAE J1979
    if is_spark:
        rs.catalyst         = MonitorStatus(_specific_avail(0), _specific_complete(0))
        rs.heated_catalyst  = MonitorStatus(_specific_avail(1), _specific_complete(1))
        rs.evap_system      = MonitorStatus(_specific_avail(2), _specific_complete(2))
        rs.secondary_air    = MonitorStatus(_specific_avail(3), _specific_complete(3))
        rs.ac_refrigerant   = MonitorStatus(_specific_avail(4), _specific_complete(4))
        rs.o2_sensor        = MonitorStatus(_specific_avail(5), _specific_complete(5))
        rs.o2_sensor_heater = MonitorStatus(_specific_avail(6), _specific_complete(6))
        rs.egr_vvt          = MonitorStatus(_specific_avail(7), _specific_complete(7))
    else:
        rs.nmhc_catalyst      = MonitorStatus(_specific_avail(0), _specific_complete(0))
        rs.nox_scr            = MonitorStatus(_specific_avail(1), _specific_complete(1))
        rs.boost_pressure     = MonitorStatus(_specific_avail(3), _specific_complete(3))
        rs.exhaust_gas_sensor = MonitorStatus(_specific_avail(5), _specific_complete(5))
        rs.pm_filter          = MonitorStatus(_specific_avail(6), _specific_complete(6))
        rs.egr_vvt            = MonitorStatus(_specific_avail(7), _specific_complete(7))

    return rs


# ---------------------------------------------------------------------------
# 4. PARSER VIN DUAL-PROTOCOLO (kotlin-obd-api Control.kt → VINCommand)
# ---------------------------------------------------------------------------

_VIN_CAN_PREFIX_LEN = 9   # "xxx490201" antes del VIN en CAN multi-frame
_NON_PRINTABLE_RE   = re.compile(r"[\x00-\x1f]")
_STARTS_ALPHANUM_RE = re.compile(r"[^a-z0-9 ]", re.IGNORECASE)


def _hex_to_ascii(hex_str: str) -> str:
    """Convierte string hexadecimal a ASCII, ignorando chars no imprimibles."""
    try:
        result = "".join(
            chr(int(hex_str[i:i+2], 16)) for i in range(0, len(hex_str) - 1, 2)
        )
        return _NON_PRINTABLE_RE.sub("", result)
    except (ValueError, IndexError):
        return ""


def parse_vin_robust(raw_response: str) -> str:
    """
    Parser VIN robusto con soporte dual-protocolo.
    Maneja CAN (ISO-15765) y ISO9141-2 / KWP2000.

    Fuente: kotlin-obd-api VINCommand.parseVIN()

    El estándar requiere modo 09 PID 02. La respuesta puede venir como:
      CAN one-frame:    "490201[17 chars hex]"
      CAN multi-frame:  "0:490201[hex]\n1:[hex]\n2:[hex]"
      ISO9141/KWP2000:  "490201[hex]"
    """
    # Limpieza básica de espacios
    clean = _WHITESPACE_RE.sub("", raw_response.upper())
    clean_with_colons = raw_response.upper()  # versión sin strip de ':'

    if ":" in raw_response:
        # CAN multi-frame — eliminar "\n X:" separadores de frame
        no_colon = re.sub(r"[\r\n].:", "", clean_with_colons)
        no_colon = _WHITESPACE_RE.sub("", no_colon)
        payload = no_colon[_VIN_CAN_PREFIX_LEN:]

        # Si después de decodificar empieza con char no alfanumérico → usar path alternativo
        decoded_test = _hex_to_ascii(payload)
        if _STARTS_ALPHANUM_RE.search(decoded_test):
            alt = re.sub(r"0:49", "", clean_with_colons)
            alt = re.sub(r"[\r\n].:", "", alt)
            payload = _WHITESPACE_RE.sub("", alt)
    else:
        # ISO9141-2 / KWP2000: eliminar prefijo "490201" o similar "49020X"
        payload = re.sub(r"49020.", "", clean)

    vin = _hex_to_ascii(payload).strip()
    return vin if len(vin) >= 8 else ""  # VIN válido: 17 chars, mínimo tolerable 8


# ---------------------------------------------------------------------------
# 5. FREEZE FRAME DECODER (MacFJA/OBD2 FrozeCommand.java)
# ---------------------------------------------------------------------------

def build_freeze_frame_command(mode01_pid_hex: str) -> str:
    """
    Genera el comando Mode 02 (freeze frame) equivalente a cualquier comando Mode 01.
    Patrón: reemplazar prefijo "01" → "02".

    Fuente: MacFJA/OBD2 FrozeCommand.java → getRequest()

    Args:
        mode01_pid_hex: PID en hex, ej. "0C" para RPM

    Returns:
        String de comando, ej. "020C" (RPM en freeze frame)

    Nota: PID 0x01 (monitor status) NO está disponible en Mode 02.
    """
    pid = mode01_pid_hex.upper().strip()
    if pid == "01":
        raise ValueError("PID 01 (monitor status) no está disponible en Mode 02 (freeze frame)")
    return f"02{pid}"


def decode_freeze_frame_pid(
    pid: int,
    raw_bytes: list[int],
) -> dict[str, Any]:
    """
    Decodifica un PID de freeze frame (Mode 02) usando la misma fórmula que Mode 01.
    El freeze frame captura los datos del instante en que se encendió el MIL.

    Fuente: MacFJA/OBD2 FrozeCommand.java → getResponse() delega a service01Command
    Fuente: EXTENDED_MODE01_PIDS definido abajo (mismas fórmulas)

    Args:
        pid:       PID entero (ej. 0x0C para RPM)
        raw_bytes: bytes de datos (sin echo 42 0C)

    Returns:
        dict con name, value, unit, raw, source="freeze_frame"
    """
    # Misma fórmula que Mode 01
    all_pids = {**EXTENDED_MODE01_PIDS}
    # Importar también los de pid_registry si están disponibles
    try:
        from scaner_soler.ecu.pid_registry import OBD_COMMANDS
        all_pids.update(OBD_COMMANDS)
    except ImportError:
        pass

    if pid in all_pids:
        entry = all_pids[pid]
        name, _mode, pid_hex, unit = entry[0], entry[1], entry[2], entry[3]
        formula = entry[5] if len(entry) > 5 else entry[4] if callable(entry[4]) else None
        try:
            value = formula(raw_bytes) if formula else raw_bytes
            if isinstance(value, float):
                value = round(value, 3)
        except (IndexError, ZeroDivisionError, KeyError, TypeError):
            value = None
        return {
            "pid": pid, "pid_hex": f"{pid:02X}",
            "name": name, "value": value, "unit": unit,
            "raw": raw_bytes, "source": "freeze_frame",
        }
    return {
        "pid": pid, "pid_hex": f"{pid:02X}",
        "name": f"PID_{pid:02X}", "value": None, "unit": "",
        "raw": raw_bytes, "source": "freeze_frame",
    }


def get_freeze_frame_dtc(raw_bytes: list[int]) -> str:
    """
    Decodifica el DTC que causó el freeze frame (Mode 02 PID 0x02 → responde "42 02 XX YY").
    Fuente: MacFJA/OBD2 FreezeDiagnosticTroubleCode

    Args:
        raw_bytes: 2 bytes de datos

    Returns:
        Código DTC tipo "P0300" o "" si no hay
    """
    if len(raw_bytes) < 2:
        return ""
    chunk = f"{raw_bytes[0]:02X}{raw_bytes[1]:02X}"
    return _decode_dtc_chunk(chunk)


# ---------------------------------------------------------------------------
# 6. PIDs EXTENDIDOS MODE 01 (MacFJA/OBD2 Commands.md + kotlin-obd-api)
# ---------------------------------------------------------------------------
# Formato: pid_int → (nombre, modo, pid_hex, unidad, bytes_respuesta, formula)
# Solo incluye PIDs que NO están en pid_registry.py actual
#
# Fuentes:
#   MacFJA/OBD2 Commands.md (lista completa implementada en Java)
#   kotlin-obd-api Fuel.kt, Ratio.kt, Engine.kt, Control.kt

EXTENDED_MODE01_PIDS: dict[int, tuple] = {

    # ── PID 0x01: Monitor Status (no en OBD_COMMANDS, parseamos aparte) ──
    # 0x01 se parsea con decode_monitor_status(), no con formula lambda

    # ── PID 0x02: DTC causando freeze frame ──
    0x02: ("freeze_dtc",        "01", "02", "",   2,
           lambda b: get_freeze_frame_dtc(b)),

    # ── PID 0x03: Estado del sistema de combustible ──
    # Byte A: banco 1 (00=no usado, 01=open loop no condiciones, 02=closed loop,
    #          04=open loop condición conducción, 08=open loop fallo sistema,
    #          10=closed loop fallo O2 sensor)
    # Byte B: banco 2 (mismas definiciones)
    0x03: ("fuel_system_status", "01", "03", "",  2,
           lambda b: f"B1:{b[0]:02X} B2:{b[1]:02X}" if len(b) >= 2 else f"{b[0]:02X}"),

    # ── PIDs 0x12-0x1E: Presencia sensores / estado sistemas ──
    0x12: ("sec_air_status",    "01", "12", "",   1,
           lambda b: _SEC_AIR_STATUS.get(b[0], f"0x{b[0]:02X}")),

    0x13: ("o2_sensors_present_2bank", "01", "13", "", 1,
           lambda b: _decode_o2_present_2bank(b[0])),

    0x18: ("o2_b2s3_v",         "01", "18", "V",  2,
           lambda b: round(b[0] / 200, 3)),

    0x19: ("o2_b2s4_v",         "01", "19", "V",  2,
           lambda b: round(b[0] / 200, 3)),

    0x1A: ("o2_b3s1_v",         "01", "1A", "V",  2,
           lambda b: round(b[0] / 200, 3)),

    0x1B: ("o2_b3s2_v",         "01", "1B", "V",  2,
           lambda b: round(b[0] / 200, 3)),

    # OBD estándar de conformidad
    0x1C: ("obd_standard",      "01", "1C", "",   1,
           lambda b: _OBD_STANDARD.get(b[0], f"OBD-{b[0]}")),

    0x1D: ("o2_sensors_present_4bank", "01", "1D", "", 1,
           lambda b: _decode_o2_present_4bank(b[0])),

    0x1E: ("aux_input_status",  "01", "1E", "",   1,
           lambda b: "PTO_ACTIVE" if b[0] & 0x01 else "PTO_INACTIVE"),

    # ── PIDs 0x24-0x2B: Wideband O2 — Equivalence Ratio + Voltage ──
    # Bytes A,B: ratio = (A*256+B) * 2/65536  → [0, 2]
    # Bytes C,D: voltage = (C*256+D) * 8/65536 V → [0, 8 V]
    0x24: ("o2_wb_b1s1_ratio",  "01", "24", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x25: ("o2_wb_b1s2_ratio",  "01", "25", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x26: ("o2_wb_b2s1_ratio",  "01", "26", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x27: ("o2_wb_b2s2_ratio",  "01", "27", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x28: ("o2_wb_b3s1_ratio",  "01", "28", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x29: ("o2_wb_b3s2_ratio",  "01", "29", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x2A: ("o2_wb_b4s1_ratio",  "01", "2A", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),
    0x2B: ("o2_wb_b4s2_ratio",  "01", "2B", "",   4,
           lambda b: round((b[0]*256+b[1]) * 2/65536, 4)),

    # ── PID 0x32: Evap System Vapor Pressure (signed) ──
    # ((A*256)+B)/4  Pa, signed (Two's complement)
    0x32: ("evap_vapor_pres_signed", "01", "32", "Pa", 2,
           lambda b: round(_signed16(b[0], b[1]) / 4, 2)),

    # ── PIDs 0x35-0x3B: Wideband O2 — Equivalence Ratio + Current ──
    # Bytes A,B: ratio = (A*256+B) * 2/65536
    # Bytes C,D: current = (C*256+D) / 256 - 128  mA
    0x35: ("o2_wb_b1s2_curr",   "01", "35", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x36: ("o2_wb_b2s1_curr",   "01", "36", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x37: ("o2_wb_b2s2_curr",   "01", "37", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x38: ("o2_wb_b3s1_curr",   "01", "38", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x39: ("o2_wb_b3s2_curr",   "01", "39", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x3A: ("o2_wb_b4s1_curr",   "01", "3A", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),
    0x3B: ("o2_wb_b4s2_curr",   "01", "3B", "mA",  4,
           lambda b: round((b[2]*256+b[3]) / 256 - 128, 3)),

    # ── PID 0x41: Monitor Status Current Drive Cycle ──
    # Misma decodificación que 0x01 pero para el ciclo actual
    # Usar decode_monitor_status() con los 4 bytes de datos
    # Aquí retornamos raw dict summary
    0x41: ("monitor_status_drive_cycle", "01", "41", "", 4,
           lambda b: decode_monitor_status(b).to_dict()),

    # ── PID 0x48: Absolute Throttle Position C ──
    0x48: ("throttle_pos_c",    "01", "48", "%",  1,
           lambda b: round(b[0] * 100 / 255, 2)),

    # ── PID 0x4C: Commanded Throttle Actuator ──
    0x4C: ("throttle_actuator", "01", "4C", "%",  1,
           lambda b: round(b[0] * 100 / 255, 2)),

    # ── PID 0x4F: Maximum values ──
    # Byte A: max equiv ratio, Byte B: max O2 voltage (V), Byte C: max O2 current (mA), Byte D: max MAP (kPa)
    0x4F: ("max_values",        "01", "4F", "",   4,
           lambda b: {"max_equiv_ratio": b[0], "max_o2_v": b[1],
                      "max_o2_ma": b[2], "max_map_kpa": b[3] * 10}),

    # ── PID 0x50: Maximum MAF ──
    # Byte A * 10 = max g/s, bytes B,C,D reserved
    0x50: ("max_maf",           "01", "50", "g/s", 4,
           lambda b: b[0] * 10),

    # ── PID 0x54: Evap System Vapor Pressure (signed, 2-byte) ──
    # ((A*256)+B) - 32767   Pa
    0x54: ("evap_vapor_pres_b", "01", "54", "Pa", 2,
           lambda b: (b[0]*256 + b[1]) - 32767),

    # ── PIDs 0x55-0x58: Secondary O2 Sensor Trim ──
    # (A-128) * 100/128 %
    0x55: ("o2_trim_st_b1b3",   "01", "55", "%",  2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x56: ("o2_trim_lt_b1b3",   "01", "56", "%",  2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x57: ("o2_trim_st_b2b4",   "01", "57", "%",  2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),
    0x58: ("o2_trim_lt_b2b4",   "01", "58", "%",  2,
           lambda b: [round((b[0]-128)*100/128, 2), round((b[1]-128)*100/128, 2)]),

    # ── PID 0x59: Fuel Rail Absolute Pressure ──
    # (A*256+B) * 10 kPa
    0x59: ("fuel_rail_abs_pres", "01", "59", "kPa", 2,
           lambda b: (b[0]*256 + b[1]) * 10),

    # ── PID 0x5A: Relative Accelerator Pedal Position ──
    0x5A: ("accel_rel",         "01", "5A", "%",  1,
           lambda b: round(b[0] * 100 / 255, 2)),

    # ── PID 0x5B: Hybrid Battery Pack Remaining Life ──
    0x5B: ("hybrid_batt_life",  "01", "5B", "%",  1,
           lambda b: round(b[0] * 100 / 255, 2)),
}

# Lookups internos para decodificación
_SEC_AIR_STATUS = {
    0x01: "UPSTREAM",
    0x02: "DOWNSTREAM_CATALYST",
    0x04: "ATMOSPHERE_OFF",
    0x08: "PUMP_COMMANDED_ON",
}

_OBD_STANDARD = {
    0x01: "OBD-II (CARB)",
    0x02: "OBD (EPA)",
    0x03: "OBD and OBD-II",
    0x04: "OBD-I",
    0x05: "Not OBD compliant",
    0x06: "EOBD (Europe)",
    0x07: "EOBD and OBD-II",
    0x08: "EOBD and OBD",
    0x09: "EOBD, OBD and OBD-II",
    0x0A: "JOBD (Japan)",
    0x0B: "JOBD and OBD-II",
    0x0C: "JOBD and EOBD",
    0x0D: "JOBD, EOBD and OBD-II",
    0x11: "EMD (Engine Manufacturer Diagnostics)",
    0x12: "EMD+ (Enhanced EMD)",
    0x13: "HD OBD-C (Heavy Duty)",
    0x14: "HD OBD (Heavy Duty)",
    0x15: "WWH OBD (World Wide Harmonized)",
    0x17: "HD EOBD-I",
    0x18: "HD EOBD-II",
    0x19: "HD EOBD-I N",
    0x1A: "HD EOBD-II N",
    0x1C: "OBD BR1 (Brazil)",
    0x1D: "OBD BR2 (Brazil)",
    0x1E: "KOBD (Korea)",
    0x1F: "IOBD-I (India)",
    0x20: "IOBD-II (India)",
    0x21: "HD EOBD-IV",
}


def _decode_o2_present_2bank(byte: int) -> dict[str, list[bool]]:
    """Decodifica PID 0x13: sensores O2 presentes en configuración 2 bancos."""
    return {
        "bank1": [bool(byte & (1 << i)) for i in range(4)],
        "bank2": [bool(byte & (1 << (i+4))) for i in range(4)],
    }


def _decode_o2_present_4bank(byte: int) -> dict[str, list[bool]]:
    """Decodifica PID 0x1D: sensores O2 presentes en configuración 4 bancos."""
    return {
        "bank1": [bool(byte & 0x01), bool(byte & 0x02)],
        "bank2": [bool(byte & 0x04), bool(byte & 0x08)],
        "bank3": [bool(byte & 0x10), bool(byte & 0x20)],
        "bank4": [bool(byte & 0x40), bool(byte & 0x80)],
    }


def _signed16(msb: int, lsb: int) -> int:
    """Convierte 2 bytes a entero con signo (complemento a 2)."""
    val = (msb << 8) | lsb
    return val - 65536 if val >= 32768 else val


# ---------------------------------------------------------------------------
# 7. PIDs EXTENDIDOS MODE 09 (MacFJA/OBD2 + kotlin-obd-api)
# ---------------------------------------------------------------------------

MODE09_EXTENDED_PIDS: dict[int, tuple] = {
    # PID 0x01: VIN Message Count (previo al VIN real en ISO9141/KWP2000)
    0x01: ("vin_msg_count", "09", "01", "", 1,
           lambda b: b[0]),

    # PID 0x02: VIN — parsear con parse_vin_robust() para protocolo correcto
    0x02: ("vin", "09", "02", "", 20,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),

    # PID 0x04: Calibration ID (software calibration identifier)
    0x04: ("calibration_id", "09", "04", "", 16,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),

    # PID 0x06: CVN (Calibration Verification Number) — checksum del software ECU
    0x06: ("cvn", "09", "06", "", 4,
           lambda b: "".join(f"{x:02X}" for x in b)),

    # PID 0x08: In-use Performance Tracking (spark ignition)
    0x08: ("perf_tracking_spark", "09", "08", "", 4,
           lambda b: {"ignition_counter": b[0]*256+b[1], "catalyst_monitor": b[2]*256+b[3]}),

    # PID 0x09: In-use Performance Tracking (compression ignition)
    0x09: ("perf_tracking_compression", "09", "09", "", 4,
           lambda b: {"ignition_counter": b[0]*256+b[1], "nox_monitor": b[2]*256+b[3]}),

    # PID 0x0A: ECU Name (20 bytes ASCII)
    0x0A: ("ecu_name", "09", "0A", "", 20,
           lambda b: bytes(b).decode("ascii", errors="ignore").strip('\x00').strip()),
}


# ---------------------------------------------------------------------------
# 8. MAF Y CONSUMO DESDE FÍSICA (begaz/OBDII obd2_plugin.dart)
# ---------------------------------------------------------------------------
# Cálculo de MAF estimado a partir de RPM + MAP + IAT usando el modelo del
# volumen de desplazamiento del motor. Útil para diagnóstico cuando el sensor
# MAF real falla o para verificar consistencia de lecturas.

_VOL_EFF_DEFAULT = 0.85   # eficiencia volumétrica típica (0.75-0.95)
_AIR_DENSITY     = 1.293  # kg/m³ al nivel del mar
_MOLAR_MASS_AIR  = 28.97  # g/mol masa molar del aire
_GAS_CONSTANT    = 8.314  # J/(mol·K)
_STOICH_AFR      = 14.7   # relación aire-combustible estequiométrica gasolina
_FUEL_DENSITY_GL = 0.820  # kg/L gasolina (~820 g/L)


def maf_from_physics(
    rpm: float,
    map_kpa: float,
    iat_celsius: float,
    vol_eff: float = _VOL_EFF_DEFAULT,
) -> float:
    """
    Calcula MAF estimado (g/s) desde RPM, MAP e IAT usando modelo físico.
    Útil para: detectar fallas MAF, verificar sensor, sistemas sin sensor MAF.

    Fuente: begaz/OBDII obd2_plugin.dart fMaf()
    Fórmula: MAF = RPM/120 * (MAP/iat_kelvin/2) * vol_eff * M_air / R_gas

    Args:
        rpm:         Revoluciones por minuto
        map_kpa:     Presión absoluta del múltiple (kPa)
        iat_celsius: Temperatura de admisión (°C)
        vol_eff:     Eficiencia volumétrica [0.0-1.0], default 0.85

    Returns:
        MAF estimado en g/s
    """
    if rpm <= 0 or map_kpa <= 0:
        return 0.0
    iat_k     = iat_celsius + 273.15
    rps       = rpm / 60.0            # rev/s
    # IMAP (Intake Manifold Air Pressure normalized): kPa / (K * 2) * rps
    imap      = rps * (map_kpa / iat_k / 2.0)
    # MAF en g/s: IMAP * vol_eff * molar_mass / gas_constant
    maf_gs    = imap * vol_eff * _MOLAR_MASS_AIR * _AIR_DENSITY / _GAS_CONSTANT
    return round(maf_gs, 3)


def fuel_rate_from_physics(
    rpm: float,
    map_kpa: float,
    iat_celsius: float,
    vol_eff: float = _VOL_EFF_DEFAULT,
    afr: float = _STOICH_AFR,
) -> float:
    """
    Calcula consumo de combustible estimado (L/h) desde RPM, MAP e IAT.
    Asume combustión estequiométrica (lambda=1).

    Fuente: begaz/OBDII obd2_plugin.dart fFuel()

    Args:
        rpm:         Revoluciones por minuto
        map_kpa:     Presión absoluta del múltiple (kPa)
        iat_celsius: Temperatura de admisión (°C)
        vol_eff:     Eficiencia volumétrica
        afr:         Air-Fuel Ratio (default 14.7 gasolina estequiométrico)

    Returns:
        Consumo estimado en L/h
    """
    maf = maf_from_physics(rpm, map_kpa, iat_celsius, vol_eff)
    if maf <= 0:
        return 0.0
    # fuel_g/s = maf_g/s / AFR
    # fuel_L/h = (fuel_g/s * 3600) / (density_g/L)
    fuel_gs   = maf / afr
    fuel_lh   = (fuel_gs * 3600.0) / (_FUEL_DENSITY_GL * 1000.0)
    return round(fuel_lh, 3)


def maf_deviation_pct(maf_measured: float, maf_estimated: float) -> float:
    """
    Calcula la desviación porcentual entre MAF medido y estimado desde física.
    Una desviación > 20% puede indicar falla en el sensor MAF o en MAP/IAT.

    Returns:
        Porcentaje de desviación (positivo = sensor MAF alto, negativo = bajo)
    """
    if maf_estimated <= 0:
        return 0.0
    return round((maf_measured - maf_estimated) / maf_estimated * 100.0, 1)


# ---------------------------------------------------------------------------
# 9. PARSER DE FRAMES ELM327 GENÉRICO (begaz/OBDII _calculateParameterFrames)
# ---------------------------------------------------------------------------

def parse_elm327_frame(raw_response: str, mode_pid_hex: str) -> list[str]:
    """
    Extrae los bytes de datos de una respuesta ELM327 eliminando el echo de comando.
    Funciona para cualquier modo (01, 02, 03, 09...).

    Fuente: begaz/OBDII obd2_plugin.dart _calculateParameterFrames()

    El ELM327 responde con mode+0x40 como prefijo de confirmación:
      Modo 01 → 41, Modo 02 → 42, Modo 03 → 43, Modo 09 → 49

    Args:
        raw_response:  respuesta cruda del ELM327
        mode_pid_hex:  modo+PID enviado, ej. "010C" para RPM

    Returns:
        Lista de strings hex de 2 chars, ej. ["0F", "A2"]
    """
    # Eliminar espacios
    response  = raw_response.replace(" ", "").upper()
    mode_pid  = mode_pid_hex.replace(" ", "").upper()

    if response in ("NODATA", "NO DATA", ""):
        return []

    # Calcular prefijo de respuesta: primer dígito del modo + 4, resto igual
    mode_first = int(mode_pid[0], 16)
    resp_prefix = f"{mode_first + 4:X}{mode_pid[1:]}"  # ej. "010C" → "410C"

    # Dividir en el prefijo de respuesta y tomar todo lo que venga después
    parts = response.split(resp_prefix)
    payload = "".join(parts[1:]) if len(parts) > 1 else ""

    # Dividir en bytes de 2 chars
    bytes_list = [payload[i:i+2] for i in range(0, len(payload) - 1, 2)]

    # Filtrar bytes incompletos al final
    return [b for b in bytes_list if len(b) == 2]


# ---------------------------------------------------------------------------
# 10. UTILIDADES DE INTEGRACIÓN
# ---------------------------------------------------------------------------

def get_all_new_pids() -> dict[int, tuple]:
    """
    Devuelve todos los PIDs nuevos de este módulo combinados.
    Para integrar con OBD_COMMANDS del pid_registry.
    """
    return {**EXTENDED_MODE01_PIDS}


def describe_pid(pid: int) -> str:
    """
    Describe un PID dado, buscando en fuentes locales y de pid_registry.
    """
    if pid in EXTENDED_MODE01_PIDS:
        entry = EXTENDED_MODE01_PIDS[pid]
        return f"Mode {entry[1]} PID 0x{pid:02X}: {entry[0]} [{entry[3]}]"
    try:
        from scaner_soler.ecu.pid_registry import OBD_COMMANDS
        if pid in OBD_COMMANDS:
            entry = OBD_COMMANDS[pid]
            return f"Mode {entry[1]} PID 0x{pid:02X}: {entry[0]} [{entry[3]}]"
    except ImportError:
        pass
    return f"PID 0x{pid:02X}: desconocido"


# Lista de todos los PIDs nuevos (no en pid_registry original)
NEW_PIDS_LIST: list[int] = sorted(EXTENDED_MODE01_PIDS.keys())

# Resumen de lo que aporta cada repo
REPO_VERDICTS = {
    "REPO 1 - eltonvs/kotlin-obd-api": {
        "veredicto": "INTEGRAR — código fuente de alta calidad",
        "aportaciones": [
            "Parser DTC tri-protocolo (CAN one-frame, CAN multi-frame, ISO9141)",
            "Decoder readiness monitors completo con spark vs. compression ignition",
            "Parser VIN dual-protocolo robusto (CAN + ISO9141/KWP2000)",
            "Pipeline de limpieza de respuestas ELM327 (4 pasos)",
            "Permanent DTCs (Mode 0A) con patrón regex correcto",
            "Detección de error negativo 7F 0x 11/12",
            "Monitor status current drive cycle (PID 0x41)",
        ],
    },
    "REPO 2 - barracuda-fsh/pyobd": {
        "veredicto": "REFERENCIA — no aporta parsing propio",
        "aportaciones": [
            "Tabla de sensores Mode 01 (referencia de cobertura)",
            "Freeze frame display feature (delega a python-obd)",
            "No implementa parsing propio — todo delegado a librería obd",
        ],
    },
    "REPO 3 - MacFJA/OBD2": {
        "veredicto": "INTEGRAR — patrón freeze frame + 17 PIDs faltantes",
        "aportaciones": [
            "FrozeCommand (Mode 02): patrón elegante reemplaza 01→02 en cualquier PID",
            "17+ PIDs Mode 01 faltantes en nuestro registro (0x12-0x1E, 0x24-0x2B, etc.)",
            "Mode 09 extendido: VINMessageCount (PID 0x01), performance tracking (0x08, 0x09)",
            "OBD standard conformity codes (PID 0x1C) — 30+ estándares",
        ],
    },
    "REPO 4 - begaz/OBDII": {
        "veredicto": "INTEGRAR PARCIALMENTE — cálculo físico MAF único valor",
        "aportaciones": [
            "fMaf: calcula MAF desde RPM+MAP+IAT (diagnóstico de sensor MAF)",
            "fFuel: consumo de combustible desde física",
            "Parser genérico de frames ELM327 (stripea eco de comando)",
            "DTC parsing por bit-nibble (Python ya tiene algo mejor)",
        ],
    },
}
