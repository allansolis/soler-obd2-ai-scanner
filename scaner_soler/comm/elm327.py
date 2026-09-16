import time
import serial
from .base import AbstractProtocol, DTC

# OBD-II PID decode table: pid -> (name, unit, formula)
PID_TABLE = {
    0x04: ("engine_load",       "%",   lambda v: v[0] * 100 / 255),
    0x05: ("coolant_temp",      "C",   lambda v: v[0] - 40),
    0x06: ("fuel_trim_st_b1",   "%",   lambda v: (v[0] - 128) * 100 / 128),
    0x07: ("fuel_trim_lt_b1",   "%",   lambda v: (v[0] - 128) * 100 / 128),
    0x0B: ("map_kpa",           "kPa", lambda v: v[0]),
    0x0C: ("rpm",               "rpm", lambda v: ((v[0] * 256) + v[1]) / 4),
    0x0D: ("speed",             "km/h",lambda v: v[0]),
    0x0E: ("ignition_advance",  "deg", lambda v: v[0] / 2 - 64),
    0x0F: ("iat",               "C",   lambda v: v[0] - 40),
    0x10: ("maf",               "g/s", lambda v: ((v[0] * 256) + v[1]) / 100),
    0x11: ("throttle",          "%",   lambda v: v[0] * 100 / 255),
    0x14: ("o2_b1s1_v",        "V",    lambda v: v[0] / 200),
    0x1F: ("runtime",           "s",   lambda v: (v[0] * 256) + v[1]),
    0x21: ("mil_distance",      "km",  lambda v: (v[0] * 256) + v[1]),
    0x2F: ("fuel_level",        "%",   lambda v: v[0] * 100 / 255),
    0x33: ("baro_kpa",          "kPa", lambda v: v[0]),
    0x42: ("ctrl_voltage",      "V",   lambda v: ((v[0] * 256) + v[1]) / 1000),
    0x46: ("ambient_temp",      "C",   lambda v: v[0] - 40),
    0x5C: ("oil_temp",          "C",   lambda v: v[0] - 40),
    0x67: ("coolant_temp2",     "C",   lambda v: v[1] - 40),
}

INIT_CMDS = ["ATZ", "ATE0", "ATH1", "ATL0", "ATSP0", "ATAT1"]


class ELM327Protocol(AbstractProtocol):

    def __init__(self):
        self._serial: serial.Serial | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    def connect(self, port: str = "COM3", baudrate: int = 115200) -> bool:
        try:
            self._serial = serial.Serial(port, baudrate, timeout=5.0)
            time.sleep(0.5)
            for cmd in INIT_CMDS:
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
            name, unit, formula = PID_TABLE[pid]
            try:
                value = formula(data_bytes)
                return {"pid": pid, "name": name, "value": round(value, 3), "unit": unit, "raw": data_bytes}
            except (IndexError, ZeroDivisionError):
                pass
        return {"pid": pid, "name": f"PID_{pid:02X}", "value": None, "unit": "", "raw": data_bytes}

    def read_dtc(self) -> list[DTC]:
        raw = self._send_command("03", delay=0.5)
        return self._parse_dtc_response(raw, status="confirmed")

    def _parse_dtc_response(self, raw: str, status: str) -> list[DTC]:
        dtcs = []
        for line in raw.splitlines():
            clean = line.strip().replace(" ", "").upper()
            if not clean or ">" in clean or "NO" in clean:
                continue
            if clean.startswith("43") or clean.startswith("47"):
                clean = clean[2:]
            while len(clean) >= 4:
                pair = clean[:4]
                clean = clean[4:]
                if pair == "0000":
                    continue
                code = self._decode_dtc_bytes(int(pair[:2], 16), int(pair[2:], 16))
                if code:
                    dtcs.append(DTC.from_raw_code(code))
                    dtcs[-1].status = status
        return dtcs

    def _decode_dtc_bytes(self, b1: int, b2: int) -> str:
        prefix_map = {0: "P0", 1: "P1", 2: "P2", 3: "P3",
                      4: "C0", 5: "C1", 6: "B0", 7: "B1",
                      8: "U0", 9: "U1", 10: "U2", 11: "U3"}
        prefix_idx = (b1 >> 6) * 4 + ((b1 >> 4) & 0x03)
        prefix = prefix_map.get(prefix_idx, "P0")
        digits = f"{(b1 & 0x0F):01X}{b2:02X}"
        code = f"{prefix}{digits}"
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
