"""
SOLER OBD2 AI Scanner - OBD-II Connection Manager

Handles auto-detection of ELM327 adapters (USB / Bluetooth / WiFi),
initialization with AT commands, VIN reading, supported-PID scanning,
and automatic reconnection with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import obd
from obd import OBDStatus
import serial.tools.list_ports

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class AdapterType(str, Enum):
    USB = "usb"
    BLUETOOTH = "bluetooth"
    WIFI = "wifi"
    UNKNOWN = "unknown"


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class AdapterInfo:
    port: str
    adapter_type: AdapterType
    description: str = ""
    hwid: str = ""


@dataclass
class ConnectionStatus:
    state: ConnectionState = ConnectionState.DISCONNECTED
    adapter: Optional[AdapterInfo] = None
    protocol: str = ""
    voltage: Optional[float] = None
    vin: Optional[str] = None
    supported_pids: list[str] = field(default_factory=list)
    error: Optional[str] = None
    connected_at: Optional[float] = None


# ---------------------------------------------------------------------------
# AT-command initialization sequence
# ---------------------------------------------------------------------------

AT_INIT_SEQUENCE: list[tuple[str, str]] = [
    ("ATZ",   "Reset adapter"),
    ("ATE0",  "Echo off"),
    ("ATS0",  "Spaces off"),
    ("ATL0",  "Linefeeds off"),
    ("ATH1",  "Headers on"),
    ("ATSP0", "Auto-detect protocol"),
]

# Known USB vendor IDs for common ELM327 clones
ELM327_USB_VIDS = {"1A86", "0403", "067B", "10C4", "2341"}

# WiFi adapter default endpoints
WIFI_ENDPOINTS = [
    ("192.168.0.10", 35000),
    ("192.168.0.10", 23),
]


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class OBDConnectionManager:
    """
    Manages the full lifecycle of an OBD-II connection:
    detection -> initialisation -> reading -> reconnection.
    """

    def __init__(self) -> None:
        self._connection: Optional[obd.OBD] = None
        self._status = ConnectionStatus()
        self._lock = asyncio.Lock()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._cfg = settings.obd

    # -- public properties ---------------------------------------------------

    @property
    def status(self) -> ConnectionStatus:
        return self._status

    @property
    def is_connected(self) -> bool:
        return (
            self._connection is not None
            and self._connection.status() == OBDStatus.CAR_CONNECTED
        )

    @property
    def connection(self) -> Optional[obd.OBD]:
        return self._connection

    # -- detection -----------------------------------------------------------

    @staticmethod
    def detect_adapters() -> list[AdapterInfo]:
        """Scan serial ports and WiFi endpoints for ELM327 adapters."""
        adapters: list[AdapterInfo] = []

        # USB / Bluetooth serial ports
        for port_info in serial.tools.list_ports.comports():
            vid_hex = f"{port_info.vid:04X}" if port_info.vid else ""
            adapter_type = AdapterType.UNKNOWN

            desc_lower = (port_info.description or "").lower()
            if vid_hex in ELM327_USB_VIDS or "elm327" in desc_lower:
                adapter_type = AdapterType.USB
            elif "bluetooth" in desc_lower or "bt" in desc_lower:
                adapter_type = AdapterType.BLUETOOTH
            elif "serial" in desc_lower:
                adapter_type = AdapterType.USB

            if adapter_type != AdapterType.UNKNOWN:
                adapters.append(
                    AdapterInfo(
                        port=port_info.device,
                        adapter_type=adapter_type,
                        description=port_info.description or "",
                        hwid=port_info.hwid or "",
                    )
                )

        # WiFi probe (non-blocking, best-effort)
        import socket

        for host, port in WIFI_ENDPOINTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    adapters.append(
                        AdapterInfo(
                            port=f"{host}:{port}",
                            adapter_type=AdapterType.WIFI,
                            description=f"WiFi ELM327 @ {host}:{port}",
                        )
                    )
            except OSError:
                pass

        logger.info("Detected %d OBD adapter(s): %s", len(adapters), adapters)
        return adapters

    # -- connect / disconnect ------------------------------------------------

    async def connect(self, port: Optional[str] = None) -> ConnectionStatus:
        """
        Connect to an ELM327 adapter.

        If *port* is ``None`` the manager will auto-detect the first
        available adapter.
        """
        async with self._lock:
            self._status.state = ConnectionState.CONNECTING
            self._status.error = None

            target_port = port or self._cfg.port

            if target_port is None:
                adapters = self.detect_adapters()
                if not adapters:
                    self._status.state = ConnectionState.ERROR
                    self._status.error = "No OBD-II adapter detected"
                    logger.error(self._status.error)
                    return self._status
                target_port = adapters[0].port
                self._status.adapter = adapters[0]
                logger.info("Auto-selected adapter on %s", target_port)

            try:
                self._status.state = ConnectionState.INITIALIZING
                conn = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: obd.OBD(
                        portstr=target_port,
                        baudrate=self._cfg.baudrate,
                        fast=self._cfg.fast_mode,
                        timeout=self._cfg.timeout,
                    ),
                )

                if conn.status() != OBDStatus.CAR_CONNECTED:
                    self._status.state = ConnectionState.ERROR
                    self._status.error = (
                        f"Could not connect to vehicle via {target_port} "
                        f"(status: {conn.status()})"
                    )
                    logger.error(self._status.error)
                    return self._status

                self._connection = conn
                self._status.state = ConnectionState.CONNECTED
                self._status.connected_at = time.time()
                self._status.protocol = str(conn.protocol_name())

                # Send AT init sequence for reliable communication
                await self._send_at_init()

                # Read voltage
                if self._cfg.check_voltage:
                    self._status.voltage = await self._read_voltage()

                # Read VIN
                self._status.vin = await self.read_vin()

                # Scan supported PIDs
                self._status.supported_pids = await self.scan_supported_pids()

                logger.info(
                    "Connected: protocol=%s VIN=%s PIDs=%d",
                    self._status.protocol,
                    self._status.vin,
                    len(self._status.supported_pids),
                )

            except Exception as exc:
                self._status.state = ConnectionState.ERROR
                self._status.error = str(exc)
                logger.exception("Connection failed")

            return self._status

    async def disconnect(self) -> None:
        """Gracefully close the OBD connection."""
        async with self._lock:
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
            if self._connection:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None
            self._status = ConnectionStatus()
            logger.info("Disconnected from OBD adapter")

    # -- AT init -------------------------------------------------------------

    async def _send_at_init(self) -> None:
        """Send AT initialization sequence to the ELM327 chip."""
        if not self._connection:
            return
        for cmd_str, description in AT_INIT_SEQUENCE:
            try:
                cmd = obd.OBDCommand(
                    cmd_str, description, b"", 0,
                    lambda messages: messages,
                    obd.ECU.ALL, False,
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, self._connection.query, cmd,
                )
                logger.debug("AT init: %s (%s) OK", cmd_str, description)
            except Exception as exc:
                logger.warning("AT init %s failed: %s", cmd_str, exc)

    # -- voltage -------------------------------------------------------------

    async def _read_voltage(self) -> Optional[float]:
        """Read adapter input voltage via ATRV."""
        if not self._connection:
            return None
        try:
            cmd = obd.OBDCommand(
                "ATRV", "Read voltage", b"", 0,
                lambda messages: messages,
                obd.ECU.ALL, False,
            )
            resp = await asyncio.get_event_loop().run_in_executor(
                None, self._connection.query, cmd,
            )
            if resp and resp.value:
                match = re.search(r"(\d+\.?\d*)", str(resp.value))
                if match:
                    return float(match.group(1))
        except Exception as exc:
            logger.warning("Voltage read failed: %s", exc)
        return None

    # -- VIN -----------------------------------------------------------------

    async def read_vin(self) -> Optional[str]:
        """Read Vehicle Identification Number (Mode 09, PID 02)."""
        if not self._connection:
            return None
        try:
            cmd = obd.commands["GET_VIN"]
            resp = await asyncio.get_event_loop().run_in_executor(
                None, self._connection.query, cmd,
            )
            if resp and not resp.is_null():
                return str(resp.value).strip()
        except Exception as exc:
            logger.warning("VIN read failed: %s", exc)
        return None

    # -- supported PIDs ------------------------------------------------------

    async def scan_supported_pids(self) -> list[str]:
        """Return a list of PID names supported by the connected vehicle."""
        if not self._connection:
            return []

        supported: list[str] = []
        try:
            for cmd in self._connection.supported_commands:
                supported.append(cmd.name)
        except Exception as exc:
            logger.warning("PID scan failed: %s", exc)

        return sorted(supported)

    # -- raw query -----------------------------------------------------------

    async def query(self, command: obd.OBDCommand) -> Optional[obd.OBDResponse]:
        """Execute a single OBD command with connection-loss detection."""
        if not self.is_connected:
            logger.warning("Query attempted while disconnected")
            self._trigger_reconnect()
            return None

        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, self._connection.query, command,  # type: ignore[union-attr]
            )
            return resp
        except Exception as exc:
            logger.error("Query %s failed: %s", command.name, exc)
            self._trigger_reconnect()
            return None

    # -- reconnection --------------------------------------------------------

    def _trigger_reconnect(self) -> None:
        """Start the reconnect loop if not already running."""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to re-establish the connection with exponential backoff."""
        delay = self._cfg.reconnect_delay
        for attempt in range(1, self._cfg.max_reconnect_attempts + 1):
            logger.info(
                "Reconnect attempt %d/%d in %.1fs",
                attempt,
                self._cfg.max_reconnect_attempts,
                delay,
            )
            await asyncio.sleep(delay)

            # Close stale handle
            if self._connection:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None

            status = await self.connect()
            if status.state == ConnectionState.CONNECTED:
                logger.info("Reconnected successfully on attempt %d", attempt)
                return

            delay = min(delay * 2, 30.0)  # cap at 30 s

        self._status.state = ConnectionState.ERROR
        self._status.error = "Max reconnection attempts exceeded"
        logger.error(self._status.error)
