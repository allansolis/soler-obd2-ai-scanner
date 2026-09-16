import re
import time
import serial
from .base import AbstractProtocol, DTC

# OBD-II PID decode table: pid -> (name, unit, min, max, formula)
# Expandida de 21 a 60+ PIDs con metadata de rango (de shchers/ecu-simulator y kotlin-obd-api)
PID_TABLE = {
    # Carga y temperatura del motor
    0x04: ("engine_load",        "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x05: ("coolant_temp",       "C",    -40, 215,   lambda v: v[0] - 40),
    # Fuel trim Banco 1
    0x06: ("fuel_trim_st_b1",    "%",    -100, 99.2, lambda v: (v[0] - 128) * 100 / 128),
    0x07: ("fuel_trim_lt_b1",    "%",    -100, 99.2, lambda v: (v[0] - 128) * 100 / 128),
    # Fuel trim Banco 2
    0x08: ("fuel_trim_st_b2",    "%",    -100, 99.2, lambda v: (v[0] - 128) * 100 / 128),
    0x09: ("fuel_trim_lt_b2",    "%",    -100, 99.2, lambda v: (v[0] - 128) * 100 / 128),
    # Presion de combustible y MAP
    0x0A: ("fuel_pressure",      "kPa",  0,   765,   lambda v: v[0] * 3),
    0x0B: ("map_kpa",            "kPa",  0,   255,   lambda v: v[0]),
    # RPM y velocidad
    0x0C: ("rpm",                "rpm",  0,   16383, lambda v: ((v[0] * 256) + v[1]) / 4),
    0x0D: ("speed",              "km/h", 0,   255,   lambda v: v[0]),
    # Avance de encendido y temperatura de admision
    0x0E: ("ignition_advance",   "deg",  -64, 63.5,  lambda v: v[0] / 2 - 64),
    0x0F: ("iat",                "C",    -40, 215,   lambda v: v[0] - 40),
    # MAF y posicion mariposa
    0x10: ("maf",                "g/s",  0,   655,   lambda v: ((v[0] * 256) + v[1]) / 100),
    0x11: ("throttle",           "%",    0,   100,   lambda v: v[0] * 100 / 255),
    # Estado de sistemas secundarios
    0x12: ("sec_air_status",     "",     0,   255,   lambda v: v[0]),
    # Sensores O2
    0x14: ("o2_b1s1_v",         "V",     0,   1.275, lambda v: v[0] / 200),
    0x15: ("o2_b1s2_v",         "V",     0,   1.275, lambda v: v[0] / 200),
    0x16: ("o2_b2s1_v",         "V",     0,   1.275, lambda v: v[0] / 200),
    0x17: ("o2_b2s2_v",         "V",     0,   1.275, lambda v: v[0] / 200),
    # Tiempo de funcionamiento
    0x1F: ("runtime",            "s",    0,   65535, lambda v: (v[0] * 256) + v[1]),
    # Distancia con MIL encendida y desde limpieza DTCs
    0x21: ("mil_distance",       "km",   0,   65535, lambda v: (v[0] * 256) + v[1]),
    # Evap y EGR
    0x2C: ("egr_cmd",            "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x2D: ("egr_error",          "%",    -100, 99.2, lambda v: (v[0] - 128) * 100 / 128),
    0x2E: ("evap_purge",         "%",    0,   100,   lambda v: v[0] * 100 / 255),
    # Nivel de combustible
    0x2F: ("fuel_level",         "%",    0,   100,   lambda v: v[0] * 100 / 255),
    # Calentamientos y distancia desde DTCs limpiados
    0x30: ("warmups_since_clr",  "cnt",  0,   255,   lambda v: v[0]),
    0x31: ("dist_dtc_clear",     "km",   0,   65535, lambda v: (v[0] * 256) + v[1]),
    # Presion barometrica
    0x33: ("baro_kpa",           "kPa",  0,   255,   lambda v: v[0]),
    # Sensores O2 wideband (ecuacion SAE)
    0x34: ("o2_wb_b1s1_eq",     "",     0,   2,     lambda v: (v[0] * 256 + v[1]) / 32768),
    0x3C: ("catalyst_temp_b1s1", "C",   -40, 6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3D: ("catalyst_temp_b2s1", "C",   -40, 6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3E: ("catalyst_temp_b1s2", "C",   -40, 6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3F: ("catalyst_temp_b2s2", "C",   -40, 6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    # Voltaje ECU
    0x42: ("ctrl_voltage",       "V",    0,   65.535,lambda v: ((v[0] * 256) + v[1]) / 1000),
    # Carga absoluta y ratio lambda
    0x43: ("abs_load",           "%",    0,   25700, lambda v: (v[0] * 256 + v[1]) * 100 / 255),
    0x44: ("lambda_eq_ratio",    "",     0,   2,     lambda v: (v[0] * 256 + v[1]) / 32768),
    # Posicion mariposa relativa y acelerador
    0x45: ("rel_throttle",       "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x46: ("ambient_temp",       "C",    -40, 215,   lambda v: v[0] - 40),
    0x47: ("throttle_pos_b",     "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x49: ("accel_pos_d",        "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x4A: ("accel_pos_e",        "%",    0,   100,   lambda v: v[0] * 100 / 255),
    0x4B: ("throttle_act",       "%",    0,   100,   lambda v: v[0] * 100 / 255),
    # Tiempo y distancia desde DTCs limpiados
    0x4D: ("time_mil_on",        "min",  0,   65535, lambda v: (v[0] * 256) + v[1]),
    0x4E: ("time_dtc_clear",     "min",  0,   65535, lambda v: (v[0] * 256) + v[1]),
    # Tipo de combustible y etanol
    0x51: ("fuel_type",          "",     0,   255,   lambda v: v[0]),
    0x52: ("ethanol_pct",        "%",    0,   100,   lambda v: v[0] * 100 / 255),
    # Presion absoluta de evap
    0x53: ("evap_vapor_pres",    "Pa",   0,   65535, lambda v: (v[0] * 256 + v[1]) / 200),
    # Temperatura aceite motor
    0x5C: ("oil_temp",           "C",    -40, 210,   lambda v: v[0] - 40),
    # Timing inyeccion combustible
    0x5D: ("fuel_inj_timing",    "deg",  -210, 301,  lambda v: (v[0] * 256 + v[1]) / 128 - 210),
    # Tasa de combustible
    0x5E: ("fuel_rate",          "L/h",  0,   3276,  lambda v: (v[0] * 256 + v[1]) * 0.05),
    # Temperatura refrigerante sensor 2
    0x67: ("coolant_temp2",      "C",    -40, 215,   lambda v: v[1] - 40),
    # Presion de aceite de motor
    0x6D: ("oil_pressure",       "kPa",  0,   765,   lambda v: v[2]),
}

FUEL_TYPE_MAP = {
    0x01: "Gasoline", 0x02: "Methanol", 0x03: "Ethanol",
    0x04: "Diesel",   0x05: "GPL/LPG",  0x06: "Natural Gas",
    0x08: "Electric", 0x09: "Bifuel Gasoline", 0x0A: "Bifuel Methanol",
    0x11: "Hybrid Gasoline", 0x13: "Hybrid Diesel", 0x14: "Hybrid Electric",
}

# Baudrates a probar en orden de probabilidad (de pyobd/python-OBD)
_TRY_BAUDS = [38400, 115200, 9600, 57600, 19200, 230400, 500000]

INIT_CMDS = ["ATZ", "ATE0", "ATH1", "ATL0", "ATSP0", "ATAT1"]

DTC_LETTERS = ['P', 'C', 'B', 'U']


class ELM327Protocol(AbstractProtocol):

    def __init__(self):
        self._serial: serial.Serial | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    def connect(self, port: str = "COM3", baudrate: int = 0) -> bool:
        """Conecta al ELM327. baudrate=0 activa auto-detección (de pyobd)."""
        try:
            if baudrate == 0:
                bauds_to_try = _TRY_BAUDS
            else:
                bauds_to_try = [baudrate]
            self._serial = serial.Serial(port, bauds_to_try[0], timeout=1.0)
            time.sleep(0.3)
            found = False
            for baud in bauds_to_try:
                self._serial.baudrate = baud
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                self._serial.write(b"ATZ\r")
                time.sleep(0.5)
                resp = self._serial.read(256).decode("ascii", errors="ignore").lower()
                if "elm" in resp or ">" in resp:
                    found = True
                    break
            if not found and baudrate == 0:
                raise ConnectionError(f"No ELM327 found on {port} at any baudrate")
            self._serial.timeout = 5.0
            for cmd in INIT_CMDS[1:]:
                self._send_command(cmd, delay=0.4)
            self._connected = True
            return True
        except serial.SerialException as e:
            raise ConnectionError(f"ELM327 connect failed on {port}: {e}") from e

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False

    def send_raw(self, data: bytes, timeout: float = 5.0) -> bytes:
        self._serial.timeout = timeout
        self._serial.write(data + b"\r")
        return self._read_response()

    def _send_command(self, cmd: str, delay: float = 0.1) -> str:
        self._serial.reset_input_buffer()
        self._serial.write((cmd + "\r").encode())
        time.sleep(delay)
        raw = b""
        while self._serial.in_waiting:
            raw += self._serial.read(self._serial.in_waiting)
            time.sleep(0.02)
        return raw.decode("ascii", errors="ignore").strip()

    def _read_response(self) -> bytes:
        buf = b""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            chunk = self._serial.read(256)
            buf += chunk
            if b">" in buf:
                break
        return buf

    def read_pid(self, pid: int, mode: int = 0x01) -> dict:
        cmd = f"{mode:02X}{pid:02X}"
        raw = self._send_command(cmd, delay=0.15)
        return self._decode_pid(pid, mode, raw)

    def _decode_pid(self, pid: int, mode: int, raw: str) -> dict:
        lines = [l.strip() for l in raw.splitlines() if l.strip() and ">" not in l]
        data_bytes = []
        expected_prefix = f"{(mode + 0x40):02X}{pid:02X}".upper()
        for line in lines:
            clean = line.replace(" ", "").upper()
            if clean.startswith(expected_prefix):
                hex_data = clean[len(expected_prefix):]
                try:
                    data_bytes = [int(hex_data[i:i+2], 16) for i in range(0, len(hex_data), 2)]
                except ValueError:
                    pass
                break
        if pid in PID_TABLE and data_bytes:
            name, unit, vmin, vmax, formula = PID_TABLE[pid]
            try:
                value = formula(data_bytes)
                if vmax > vmin and not (vmin <= value <= vmax * 1.05):
                    value = None
                else:
                    value = round(value, 3)
                if pid == 0x51:
                    value = FUEL_TYPE_MAP.get(data_bytes[0], f"type_{data_bytes[0]}")
                return {"pid": pid, "name": name, "value": value, "unit": unit, "raw": data_bytes}
            except (IndexError, ZeroDivisionError):
                pass
        return {"pid": pid, "name": f"PID_{pid:02X}", "value": None, "unit": "", "raw": data_bytes}

    def read_dtc(self) -> list[DTC]:
        raw = self._send_command("03", delay=0.5)
        return self._parse_dtc_response(raw, status="confirmed")

    def read_pending_dtc(self) -> list[DTC]:
        """Mode 07 — DTCs pendientes (detectados en ciclo actual, no confirmados)."""
        raw = self._send_command("07", delay=0.5)
        return self._parse_dtc_response(raw, status="pending")

    def read_permanent_dtc(self) -> list[DTC]:
        """Mode 0A — DTCs permanentes (no se borran con modo 04)."""
        raw = self._send_command("0A", delay=0.5)
        return self._parse_dtc_response(raw, status="permanent")

    def _parse_dtc_response(self, raw: str, status: str) -> list[DTC]:
        """Parser mejorado: soporta CAN one-frame, multi-frame y ISO 9141/KWP."""
        clean_all = raw.replace('\r', '').replace('\n', '').replace(' ', '').upper()

        # Detectar formato de respuesta y extraer payload de DTCs
        if len(clean_all) <= 16 and len(clean_all) % 4 == 0:
            # CAN one-frame: "43XX[codigos]"
            working = clean_all[4:] if clean_all.startswith("43") or clean_all.startswith("47") or clean_all.startswith("4A") else clean_all
        elif ":" in raw:
            # CAN multi-frame: "0:43XX 1:YYYY ..."
            working = re.sub(r'[\r\n:]', '', raw)[7:].replace(' ', '').upper()
        else:
            # ISO 9141 / KWP2000: una línea por respuesta
            working = re.sub(r'^43|[\r\n]43|^47|[\r\n]47|^4A|[\r\n]4A|[\r\n]', '', clean_all)

        dtcs = []
        for i in range(0, len(working) - 3, 4):
            chunk = working[i:i+4]
            if len(chunk) < 4 or chunk == "0000":
                continue
            try:
                b1 = int(chunk[0], 16)
                code = f"{DTC_LETTERS[(b1 >> 2) & 0x3]}{b1 & 0x3:01X}{chunk[1:]}"
                if len(code) == 5 and code != "P0000":
                    dtc = DTC.from_raw_code(code)
                    dtc.status = status
                    dtcs.append(dtc)
            except (ValueError, IndexError):
                continue
        return dtcs

    def _decode_dtc_bytes(self, b1: int, b2: int) -> str:
        prefix_idx = (b1 >> 6) * 4 + ((b1 >> 4) & 0x03)
        type_ch = DTC_LETTERS[prefix_idx >> 2] if (prefix_idx >> 2) < 4 else 'P'
        sub = prefix_idx & 0x3
        digits = f"{(b1 & 0x0F):01X}{b2:02X}"
        code = f"{type_ch}{sub}{digits}"
        return code if len(code) == 5 else ""

    def clear_dtc(self) -> bool:
        raw = self._send_command("04", delay=0.5)
        return "44" in raw.upper() or "OK" in raw.upper()

    def read_freeze_frame(self, dtc_code: str) -> dict:
        raw = self._send_command("02" + "02", delay=0.3)
        return {"raw": raw, "dtc": dtc_code}

    def read_vehicle_info(self) -> dict:
        vin_raw = self._send_command("0902", delay=0.5)
        cal_raw = self._send_command("0904", delay=0.3)
        ecu_raw = self._send_command("090A", delay=0.3)
        return {
            "vin": self._extract_string(vin_raw, "49 02"),
            "calibration_id": self._extract_string(cal_raw, "49 04"),
            "ecu_name": self._extract_string(ecu_raw, "49 0A"),
        }

    def _extract_string(self, raw: str, prefix: str) -> str:
        try:
            start = raw.upper().index(prefix.replace(" ", "").upper())
            hex_str = raw.replace(" ", "").upper()[start + len(prefix.replace(" ", "")):start + 50]
            chars = [chr(int(hex_str[i:i+2], 16)) for i in range(0, len(hex_str), 2)
                     if hex_str[i:i+2] not in ("00", "")]
            return "".join(c for c in chars if c.isprintable()).strip()
        except (ValueError, IndexError):
            return ""
