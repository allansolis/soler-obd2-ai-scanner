"""
SOLER OBD2 AI Scanner - ELM327 Emulator for Testing

Simulates an ELM327 OBD-II adapter so the full stack can be tested
without a real vehicle.  Supports:

  - AT commands (ATZ, ATI, ATRV, ATSP, ATDP, etc.)
  - Mode 01 (current data) - realistic sensor values
  - Mode 03 (stored DTCs)
  - Mode 04 (clear DTCs)
  - Mode 07 (pending DTCs)
  - Mode 09 (vehicle information - VIN)

Usage:
    emulator = ELM327Emulator()
    response = emulator.send("010C")  # RPM
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simulated vehicle state
# ---------------------------------------------------------------------------

@dataclass
class VehicleState:
    """Mutable state representing a running engine."""

    rpm: float = 850.0
    speed_kmh: float = 0.0
    coolant_temp_c: float = 88.0
    intake_temp_c: float = 32.0
    throttle_pct: float = 14.0
    engine_load_pct: float = 22.0
    fuel_pressure_kpa: float = 35.0
    map_kpa: float = 101.3  # manifold absolute pressure
    timing_advance_deg: float = 12.0
    maf_gs: float = 3.8  # mass air flow g/s
    o2_voltage: float = 0.45
    fuel_level_pct: float = 72.0
    battery_voltage: float = 13.8
    runtime_seconds: int = 0
    mil_on: bool = True  # MIL light for simulated DTCs

    # Simulated DTCs
    stored_dtcs: list[str] = field(
        default_factory=lambda: ["P0420", "P0171", "P0300"]
    )
    pending_dtcs: list[str] = field(
        default_factory=lambda: ["P0300"]
    )

    # VIN: 2020 Honda Civic 2.0L (example)
    vin: str = "2HGFC2F69LH500001"

    _start_time: float = field(default_factory=time.monotonic)

    def tick(self) -> None:
        """Advance simulation by one step with realistic drift."""
        elapsed = time.monotonic() - self._start_time
        self.runtime_seconds = int(elapsed)

        # Slight idle fluctuation
        self.rpm = 850 + 30 * math.sin(elapsed * 0.5) + random.gauss(0, 5)
        self.rpm = max(600, min(self.rpm, 7000))

        # Coolant temp stabilizes around 90C
        self.coolant_temp_c += (90.0 - self.coolant_temp_c) * 0.01
        self.coolant_temp_c += random.gauss(0, 0.2)

        self.intake_temp_c = 32 + 3 * math.sin(elapsed * 0.1) + random.gauss(0, 0.3)

        self.throttle_pct = 14 + 5 * math.sin(elapsed * 0.3) + random.gauss(0, 0.5)
        self.throttle_pct = max(0, min(self.throttle_pct, 100))

        self.engine_load_pct = 18 + 8 * math.sin(elapsed * 0.2)
        self.engine_load_pct = max(0, min(self.engine_load_pct, 100))

        self.map_kpa = 30 + 10 * math.sin(elapsed * 0.4) + random.gauss(0, 1)
        self.maf_gs = 3.5 + 1.5 * math.sin(elapsed * 0.3) + random.gauss(0, 0.1)

        self.o2_voltage = 0.45 + 0.4 * math.sin(elapsed * 2.0)
        self.o2_voltage = max(0.0, min(self.o2_voltage, 1.0))

        self.fuel_level_pct = max(0, self.fuel_level_pct - 0.0001)
        self.battery_voltage = 13.8 + random.gauss(0, 0.05)


# ---------------------------------------------------------------------------
# DTC encoding helpers
# ---------------------------------------------------------------------------

_DTC_TYPE_MAP = {"P": 0, "C": 1, "B": 2, "U": 3}


def _encode_dtc_pair(code: str) -> tuple[int, int]:
    """Encode a DTC like 'P0420' into two OBD bytes."""
    prefix = _DTC_TYPE_MAP.get(code[0], 0)
    digits = code[1:]
    raw = (prefix << 14) | int(digits, 16)
    return (raw >> 8) & 0xFF, raw & 0xFF


def _encode_dtc_response(mode_byte: int, dtcs: list[str], mil: bool) -> str:
    """Build a full Mode 03/07 response string."""
    count = len(dtcs)
    a_byte = (0x80 if mil else 0x00) | (count & 0x7F)

    parts = [f"{mode_byte + 0x40:02X}", f"{a_byte:02X}"]
    for code in dtcs:
        hi, lo = _encode_dtc_pair(code)
        parts.append(f"{hi:02X}")
        parts.append(f"{lo:02X}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Freeze-frame data (Mode 02 approximation stored for convenience)
# ---------------------------------------------------------------------------

_FREEZE_FRAMES: dict[str, dict[str, float]] = {
    "P0420": {
        "rpm": 2200,
        "speed_kmh": 65,
        "coolant_temp_c": 92,
        "engine_load_pct": 38,
        "throttle_pct": 28,
    },
    "P0171": {
        "rpm": 1500,
        "speed_kmh": 45,
        "coolant_temp_c": 85,
        "engine_load_pct": 25,
        "maf_gs": 2.1,
    },
    "P0300": {
        "rpm": 3200,
        "speed_kmh": 80,
        "coolant_temp_c": 94,
        "engine_load_pct": 55,
        "throttle_pct": 42,
    },
}


# ---------------------------------------------------------------------------
# DTC descriptions
# ---------------------------------------------------------------------------

DTC_DESCRIPTIONS: dict[str, dict] = {
    "P0420": {
        "description": "Catalyst System Efficiency Below Threshold (Bank 1)",
        "severity": "medium",
        "system": "Emissions",
        "possible_causes": [
            "Worn catalytic converter",
            "Faulty O2 sensor (downstream)",
            "Exhaust leak near catalytic converter",
            "Engine misfire damaging catalyst",
        ],
    },
    "P0171": {
        "description": "System Too Lean (Bank 1)",
        "severity": "medium",
        "system": "Fuel System",
        "possible_causes": [
            "Vacuum leak in intake manifold",
            "Faulty MAF sensor",
            "Clogged fuel injector",
            "Weak fuel pump",
            "Faulty PCV valve",
        ],
    },
    "P0300": {
        "description": "Random/Multiple Cylinder Misfire Detected",
        "severity": "high",
        "system": "Ignition",
        "possible_causes": [
            "Worn spark plugs or ignition coils",
            "Low fuel pressure",
            "Vacuum leak",
            "Faulty crankshaft position sensor",
            "EGR valve stuck open",
        ],
    },
}


# ---------------------------------------------------------------------------
# Main Emulator
# ---------------------------------------------------------------------------

class ELM327Emulator:
    """
    In-memory ELM327 simulator.  Feed it OBD command strings and receive
    responses exactly as a real adapter would return.
    """

    SUPPORTED_PIDS_01 = {
        "00", "01", "03", "04", "05", "06", "0B", "0C", "0D",
        "0E", "0F", "10", "11", "1C", "1F", "2F", "42",
    }

    def __init__(self) -> None:
        self.state = VehicleState()
        self.connected = False
        self.protocol: str = "auto"
        self.echo: bool = True
        self.linefeed: bool = True
        self.headers: bool = False
        self._init_time = time.monotonic()
        logger.info("ELM327 Emulator initialized (simulated vehicle ready)")

    # -- public API --

    def connect(self) -> None:
        self.connected = True
        logger.info("Emulator: connected")

    def disconnect(self) -> None:
        self.connected = False
        logger.info("Emulator: disconnected")

    def send(self, command: str) -> str:
        """Process a command and return the response string."""
        command = command.strip().upper()
        self.state.tick()

        if command.startswith("AT"):
            return self._handle_at(command)

        if not self.connected:
            return "NO DATA"

        # OBD mode commands
        if len(command) >= 2:
            mode = command[:2]
            pid = command[2:4] if len(command) >= 4 else ""
            handler = {
                "01": self._handle_mode01,
                "03": self._handle_mode03,
                "04": self._handle_mode04,
                "07": self._handle_mode07,
                "09": self._handle_mode09,
            }.get(mode)
            if handler:
                if mode in ("03", "04", "07"):
                    return handler()
                return handler(pid)

        return "?"

    def get_freeze_frame(self, dtc_code: str) -> Optional[dict[str, float]]:
        """Return freeze-frame data for a specific DTC."""
        return _FREEZE_FRAMES.get(dtc_code)

    def get_dtc_info(self, dtc_code: str) -> Optional[dict]:
        """Return description / severity / causes for a DTC."""
        return DTC_DESCRIPTIONS.get(dtc_code)

    def get_all_stored_dtcs(self) -> list[str]:
        return list(self.state.stored_dtcs)

    def get_all_pending_dtcs(self) -> list[str]:
        return list(self.state.pending_dtcs)

    def get_vehicle_info(self) -> dict:
        return {
            "vin": self.state.vin,
            "make": "Honda",
            "model": "Civic",
            "year": 2020,
            "engine": "2.0L I4 DOHC",
            "fuel_type": "Gasoline",
            "protocol": self.protocol,
            "ecu_name": "SOLER-EMU-ECU",
        }

    def get_sensor_snapshot(self) -> dict[str, dict]:
        """Return a dict of all current sensor values."""
        self.state.tick()
        s = self.state
        return {
            "010C": {"name": "RPM", "value": round(s.rpm, 1), "unit": "rpm"},
            "010D": {"name": "Vehicle Speed", "value": round(s.speed_kmh, 1), "unit": "km/h"},
            "0105": {"name": "Coolant Temperature", "value": round(s.coolant_temp_c, 1), "unit": "C"},
            "010F": {"name": "Intake Air Temperature", "value": round(s.intake_temp_c, 1), "unit": "C"},
            "0111": {"name": "Throttle Position", "value": round(s.throttle_pct, 1), "unit": "%"},
            "0104": {"name": "Engine Load", "value": round(s.engine_load_pct, 1), "unit": "%"},
            "010B": {"name": "Intake MAP", "value": round(s.map_kpa, 1), "unit": "kPa"},
            "010E": {"name": "Timing Advance", "value": round(s.timing_advance_deg, 1), "unit": "deg"},
            "0110": {"name": "MAF Air Flow", "value": round(s.maf_gs, 2), "unit": "g/s"},
            "0106": {"name": "Short Fuel Trim B1", "value": round(random.uniform(-5, 5), 1), "unit": "%"},
            "012F": {"name": "Fuel Level", "value": round(s.fuel_level_pct, 1), "unit": "%"},
            "0142": {"name": "Control Module Voltage", "value": round(s.battery_voltage, 2), "unit": "V"},
            "011F": {"name": "Run Time", "value": s.runtime_seconds, "unit": "sec"},
        }

    # -- AT commands --

    def _handle_at(self, cmd: str) -> str:
        c = cmd[2:].strip()
        if c in ("Z", "WS"):
            self.connected = True
            return "ELM327 v2.1 (SOLER-EMU)"
        if c == "I":
            return "ELM327 v2.1"
        if c == "RV":
            return f"{self.state.battery_voltage:.1f}V"
        if c.startswith("SP"):
            self.protocol = c[2:].strip() or "auto"
            return "OK"
        if c == "DP":
            return f"AUTO, {self.protocol.upper()}"
        if c == "DPN":
            return "6"  # CAN 11-bit 500kbaud
        if c in ("E0", "E1"):
            self.echo = c == "E1"
            return "OK"
        if c in ("L0", "L1"):
            self.linefeed = c == "L1"
            return "OK"
        if c in ("H0", "H1"):
            self.headers = c == "H1"
            return "OK"
        if c in ("S0", "S1"):
            return "OK"
        if c in ("AL", "NL"):
            return "OK"
        if c in ("ST00", "STFF"):
            return "OK"
        return "OK"

    # -- Mode 01: current data --

    def _handle_mode01(self, pid: str) -> str:
        if not pid:
            return "NO DATA"

        s = self.state

        # Supported PIDs bitmask (PID 00)
        if pid == "00":
            bitmask = 0
            for p in self.SUPPORTED_PIDS_01:
                pnum = int(p, 16)
                if 1 <= pnum <= 32:
                    bitmask |= 1 << (32 - pnum)
            return f"41 00 {bitmask >> 24 & 0xFF:02X} {bitmask >> 16 & 0xFF:02X} {bitmask >> 8 & 0xFF:02X} {bitmask & 0xFF:02X}"

        handlers = {
            "01": self._pid_01_mil_dtc_count,
            "03": lambda: f"41 03 02 00",  # fuel system status
            "04": lambda: f"41 04 {int(s.engine_load_pct * 2.55):02X}",
            "05": lambda: f"41 05 {int(s.coolant_temp_c + 40):02X}",
            "06": lambda: f"41 06 {128 + int(random.uniform(-5, 5) * 1.28):02X}",
            "0B": lambda: f"41 0B {int(s.map_kpa):02X}",
            "0C": lambda: self._pid_0c_rpm(),
            "0D": lambda: f"41 0D {int(s.speed_kmh):02X}",
            "0E": lambda: f"41 0E {int((s.timing_advance_deg + 64) * 2):02X}",
            "0F": lambda: f"41 0F {int(s.intake_temp_c + 40):02X}",
            "10": lambda: self._pid_10_maf(),
            "11": lambda: f"41 11 {int(s.throttle_pct * 2.55):02X}",
            "1C": lambda: "41 1C 06",  # OBD-II as per EOBD
            "1F": lambda: f"41 1F {s.runtime_seconds >> 8 & 0xFF:02X} {s.runtime_seconds & 0xFF:02X}",
            "2F": lambda: f"41 2F {int(s.fuel_level_pct * 2.55):02X}",
            "42": lambda: self._pid_42_voltage(),
        }

        handler = handlers.get(pid)
        if handler:
            return handler()
        return "NO DATA"

    def _pid_01_mil_dtc_count(self) -> str:
        count = len(self.state.stored_dtcs)
        a = (0x80 if self.state.mil_on else 0x00) | (count & 0x7F)
        return f"41 01 {a:02X} 07 E5 00"

    def _pid_0c_rpm(self) -> str:
        raw = int(self.state.rpm * 4)
        return f"41 0C {raw >> 8 & 0xFF:02X} {raw & 0xFF:02X}"

    def _pid_10_maf(self) -> str:
        raw = int(self.state.maf_gs * 100)
        return f"41 10 {raw >> 8 & 0xFF:02X} {raw & 0xFF:02X}"

    def _pid_42_voltage(self) -> str:
        raw = int(self.state.battery_voltage * 1000)
        return f"41 42 {raw >> 8 & 0xFF:02X} {raw & 0xFF:02X}"

    # -- Mode 03: stored DTCs --

    def _handle_mode03(self) -> str:
        if not self.state.stored_dtcs:
            return "43 00"
        return _encode_dtc_response(0x03, self.state.stored_dtcs, self.state.mil_on)

    # -- Mode 04: clear DTCs --

    def _handle_mode04(self) -> str:
        cleared = len(self.state.stored_dtcs) + len(self.state.pending_dtcs)
        self.state.stored_dtcs.clear()
        self.state.pending_dtcs.clear()
        self.state.mil_on = False
        logger.info("Emulator: cleared %d DTCs", cleared)
        return "44"

    # -- Mode 07: pending DTCs --

    def _handle_mode07(self) -> str:
        if not self.state.pending_dtcs:
            return "47 00"
        return _encode_dtc_response(0x07, self.state.pending_dtcs, False)

    # -- Mode 09: vehicle info --

    def _handle_mode09(self, pid: str) -> str:
        if pid == "02":
            # VIN - encode as ASCII hex
            vin_hex = " ".join(f"{ord(c):02X}" for c in self.state.vin)
            return f"49 02 01 {vin_hex}"
        if pid == "0A":
            # ECU name
            ecu = "SOLER-EMU"
            ecu_hex = " ".join(f"{ord(c):02X}" for c in ecu)
            return f"49 0A 01 {ecu_hex}"
        return "NO DATA"
