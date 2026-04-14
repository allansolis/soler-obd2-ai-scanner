"""
SOLER OBD2 AI Scanner - Real-Time Sensor Reader

Reads all Mode 01 PIDs with proper conversion formulas, streams data at
configurable rates (10 Hz critical / 2 Hz secondary), and returns structured
readings with SI units.  Supports all five OBD-II signalling protocols via
the underlying python-OBD + ELM327 layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import obd
from obd import OBDResponse

from backend.config import settings
from backend.obd.connection import OBDConnectionManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class SensorPriority(str, Enum):
    CRITICAL = "critical"    # 10 Hz
    SECONDARY = "secondary"  # 2 Hz


@dataclass
class SensorReading:
    """One timestamped sensor value."""
    pid: str
    name: str
    value: Any
    unit: str
    timestamp: float  # epoch seconds
    priority: SensorPriority
    raw: Optional[str] = None


@dataclass
class SensorSnapshot:
    """A batch of readings taken at roughly the same instant."""
    readings: list[SensorReading] = field(default_factory=list)
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# PID registry
# ---------------------------------------------------------------------------

@dataclass
class PIDDefinition:
    """Metadata about a single Mode 01 PID."""
    pid: str
    name: str
    command: Optional[obd.OBDCommand]
    unit: str
    priority: SensorPriority
    description_es: str = ""


def _build_pid_registry() -> dict[str, PIDDefinition]:
    """Map of PID name -> definition using python-OBD built-in commands."""
    # python-OBD already handles byte-level decoding; we just classify them.
    _defs: list[tuple[str, str, str, SensorPriority, str]] = [
        # (command_name, display_name, unit, priority, spanish description)

        # --- critical (10 Hz) ---
        ("RPM",                  "RPM",                   "rpm",   SensorPriority.CRITICAL,  "Revoluciones por minuto del motor"),
        ("SPEED",                "Velocidad",             "km/h",  SensorPriority.CRITICAL,  "Velocidad del vehiculo"),
        ("THROTTLE_POS",         "Posicion acelerador",   "%",     SensorPriority.CRITICAL,  "Posicion del acelerador"),
        ("ENGINE_LOAD",          "Carga del motor",       "%",     SensorPriority.CRITICAL,  "Carga calculada del motor"),
        ("SHORT_FUEL_TRIM_1",    "STFT banco 1",         "%",     SensorPriority.CRITICAL,  "Ajuste combustible corto plazo banco 1"),
        ("LONG_FUEL_TRIM_1",     "LTFT banco 1",         "%",     SensorPriority.CRITICAL,  "Ajuste combustible largo plazo banco 1"),

        # --- secondary (2 Hz) ---
        ("COOLANT_TEMP",         "Temp. refrigerante",   "C",     SensorPriority.SECONDARY, "Temperatura del refrigerante del motor"),
        ("INTAKE_TEMP",          "Temp. admision",       "C",     SensorPriority.SECONDARY, "Temperatura del aire de admision"),
        ("INTAKE_PRESSURE",      "Presion MAP",          "kPa",   SensorPriority.SECONDARY, "Presion absoluta del colector de admision"),
        ("TIMING_ADVANCE",       "Avance encendido",     "deg",   SensorPriority.SECONDARY, "Avance del encendido"),
        ("MAF",                  "Flujo MAF",            "g/s",   SensorPriority.SECONDARY, "Flujo de masa de aire"),
        ("FUEL_LEVEL",           "Nivel combustible",    "%",     SensorPriority.SECONDARY, "Nivel de combustible"),
        ("BAROMETRIC_PRESSURE",  "Presion barometrica",  "kPa",   SensorPriority.SECONDARY, "Presion barometrica"),
        ("AMBIANT_AIR_TEMP",     "Temp. ambiente",       "C",     SensorPriority.SECONDARY, "Temperatura del aire ambiente"),
        ("OIL_TEMP",             "Temp. aceite",         "C",     SensorPriority.SECONDARY, "Temperatura del aceite del motor"),
        ("FUEL_RATE",            "Consumo combustible",  "L/h",   SensorPriority.SECONDARY, "Tasa de consumo de combustible"),
        ("SHORT_FUEL_TRIM_2",    "STFT banco 2",        "%",     SensorPriority.SECONDARY, "Ajuste combustible corto plazo banco 2"),
        ("LONG_FUEL_TRIM_2",     "LTFT banco 2",        "%",     SensorPriority.SECONDARY, "Ajuste combustible largo plazo banco 2"),
        ("FUEL_PRESSURE",        "Presion combustible",  "kPa",   SensorPriority.SECONDARY, "Presion del sistema de combustible"),
        ("O2_B1S1",              "O2 banco1 sensor1",   "V",     SensorPriority.SECONDARY, "Voltaje sensor oxigeno banco 1 sensor 1"),
        ("O2_B1S2",              "O2 banco1 sensor2",   "V",     SensorPriority.SECONDARY, "Voltaje sensor oxigeno banco 1 sensor 2"),
        ("O2_B2S1",              "O2 banco2 sensor1",   "V",     SensorPriority.SECONDARY, "Voltaje sensor oxigeno banco 2 sensor 1"),
        ("O2_B2S2",              "O2 banco2 sensor2",   "V",     SensorPriority.SECONDARY, "Voltaje sensor oxigeno banco 2 sensor 2"),
        ("CATALYST_TEMP_B1S1",   "Temp. catalizador B1S1", "C",  SensorPriority.SECONDARY, "Temperatura catalizador banco 1 sensor 1"),
        ("CATALYST_TEMP_B1S2",   "Temp. catalizador B1S2", "C",  SensorPriority.SECONDARY, "Temperatura catalizador banco 1 sensor 2"),
        ("CONTROL_MODULE_VOLTAGE", "Voltaje modulo",    "V",     SensorPriority.SECONDARY, "Voltaje del modulo de control"),
        ("ABSOLUTE_LOAD",        "Carga absoluta",       "%",     SensorPriority.SECONDARY, "Carga absoluta del motor"),
        ("COMMANDED_EQUIV_RATIO", "Relacion equiv.",     "ratio", SensorPriority.SECONDARY, "Relacion equivalente comandada"),
        ("RELATIVE_THROTTLE_POS", "Acelerador relativo", "%",    SensorPriority.SECONDARY, "Posicion relativa del acelerador"),
        ("RUN_TIME",             "Tiempo motor encendido", "s",   SensorPriority.SECONDARY, "Tiempo desde arranque del motor"),
        ("DISTANCE_W_MIL",      "Distancia con MIL",    "km",    SensorPriority.SECONDARY, "Distancia recorrida con MIL encendido"),
        ("FUEL_RAIL_PRESSURE_DIRECT", "Presion riel comb.", "kPa", SensorPriority.SECONDARY, "Presion directa del riel de combustible"),
        ("EGR_ERROR",            "Error EGR",           "%",     SensorPriority.SECONDARY, "Error del sistema EGR"),
        ("EVAPORATIVE_PURGE",    "Purga evaporativa",   "%",     SensorPriority.SECONDARY, "Purga del sistema evaporativo"),
        ("WARMUPS_SINCE_DTC_CLEAR", "Arranques desde borrado", "count", SensorPriority.SECONDARY, "Arranques en caliente desde borrado de DTCs"),
        ("DISTANCE_SINCE_DTC_CLEAR", "Distancia desde borrado", "km", SensorPriority.SECONDARY, "Distancia desde borrado de DTCs"),
    ]

    registry: dict[str, PIDDefinition] = {}
    for cmd_name, display, unit, prio, desc_es in _defs:
        cmd = getattr(obd.commands, cmd_name, None)
        registry[cmd_name] = PIDDefinition(
            pid=cmd_name,
            name=display,
            command=cmd,
            unit=unit,
            priority=prio,
            description_es=desc_es,
        )
    return registry


PID_REGISTRY: dict[str, PIDDefinition] = _build_pid_registry()


# ---------------------------------------------------------------------------
# Sensor Reader
# ---------------------------------------------------------------------------

class SensorReader:
    """
    Reads OBD-II Mode 01 PIDs and streams structured data.

    Usage::

        mgr = OBDConnectionManager()
        await mgr.connect()
        reader = SensorReader(mgr)

        # one-shot
        snapshot = await reader.read_all()

        # continuous stream
        async for snapshot in reader.stream():
            process(snapshot)
    """

    def __init__(self, manager: OBDConnectionManager) -> None:
        self._mgr = manager
        self._cfg = settings.sampling
        self._running = False
        self._callbacks: list[Callable[[SensorSnapshot], Any]] = []

    # -- public API ----------------------------------------------------------

    @property
    def available_pids(self) -> list[PIDDefinition]:
        """PIDs that both the vehicle and our registry support."""
        supported = set(self._mgr.status.supported_pids)
        return [
            defn
            for defn in PID_REGISTRY.values()
            if defn.command is not None and defn.pid in supported
        ]

    def on_snapshot(self, callback: Callable[[SensorSnapshot], Any]) -> None:
        """Register a callback invoked on every snapshot."""
        self._callbacks.append(callback)

    async def read_pid(self, pid_name: str) -> Optional[SensorReading]:
        """Read a single PID and return a structured reading."""
        defn = PID_REGISTRY.get(pid_name)
        if defn is None or defn.command is None:
            logger.warning("Unknown or unsupported PID: %s", pid_name)
            return None

        resp = await self._mgr.query(defn.command)
        if resp is None or resp.is_null():
            return None

        value = resp.value
        # python-OBD returns Pint quantities; extract magnitude
        if hasattr(value, "magnitude"):
            value = round(float(value.magnitude), 2)

        return SensorReading(
            pid=defn.pid,
            name=defn.name,
            value=value,
            unit=defn.unit,
            timestamp=time.time(),
            priority=defn.priority,
            raw=str(resp.value),
        )

    async def read_group(self, priority: SensorPriority) -> SensorSnapshot:
        """Read all PIDs of a given priority and return a snapshot."""
        available = self.available_pids
        target = [d for d in available if d.priority == priority]

        readings: list[SensorReading] = []
        for defn in target:
            reading = await self.read_pid(defn.pid)
            if reading is not None:
                readings.append(reading)

        snap = SensorSnapshot(readings=readings, timestamp=time.time())
        return snap

    async def read_all(self) -> SensorSnapshot:
        """Read every available PID once."""
        readings: list[SensorReading] = []
        for defn in self.available_pids:
            reading = await self.read_pid(defn.pid)
            if reading is not None:
                readings.append(reading)

        snap = SensorSnapshot(readings=readings, timestamp=time.time())
        return snap

    # -- streaming -----------------------------------------------------------

    async def stream(self) -> None:
        """
        Continuously poll sensors at their configured rates.

        Critical PIDs are read at ``critical_hz`` and secondary PIDs at
        ``secondary_hz``.  Registered callbacks receive each snapshot.
        """
        self._running = True
        logger.info(
            "Sensor stream started (critical=%.1f Hz, secondary=%.1f Hz)",
            self._cfg.critical_hz,
            self._cfg.secondary_hz,
        )

        critical_interval = 1.0 / self._cfg.critical_hz
        secondary_interval = 1.0 / self._cfg.secondary_hz

        last_critical = 0.0
        last_secondary = 0.0

        while self._running:
            now = time.time()

            if now - last_critical >= critical_interval:
                snap = await self.read_group(SensorPriority.CRITICAL)
                last_critical = now
                await self._dispatch(snap)

            if now - last_secondary >= secondary_interval:
                snap = await self.read_group(SensorPriority.SECONDARY)
                last_secondary = now
                await self._dispatch(snap)

            # Yield to event loop; sleep just enough to avoid busy-loop
            await asyncio.sleep(0.005)

    def stop(self) -> None:
        """Signal the streaming loop to stop."""
        self._running = False
        logger.info("Sensor stream stop requested")

    # -- internals -----------------------------------------------------------

    async def _dispatch(self, snapshot: SensorSnapshot) -> None:
        """Invoke all registered callbacks."""
        for cb in self._callbacks:
            try:
                result = cb(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Snapshot callback error")

    # -- serialisation helpers -----------------------------------------------

    @staticmethod
    def reading_to_dict(reading: SensorReading) -> dict[str, Any]:
        return {
            "pid": reading.pid,
            "name": reading.name,
            "value": reading.value,
            "unit": reading.unit,
            "timestamp": reading.timestamp,
            "priority": reading.priority.value,
        }

    @staticmethod
    def snapshot_to_dict(snapshot: SensorSnapshot) -> dict[str, Any]:
        return {
            "timestamp": snapshot.timestamp,
            "readings": [
                SensorReader.reading_to_dict(r) for r in snapshot.readings
            ],
        }
