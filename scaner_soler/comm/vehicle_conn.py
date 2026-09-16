import time
from typing import Generator
from .base import AbstractProtocol, DTC, LiveDataFrame
from .elm327 import ELM327Protocol, PID_TABLE

ALL_PIDS = list(PID_TABLE.keys())


class VehicleConnection:
    """
    Unified facade over all vehicle communication protocols.
    Defaults to ELM327. Swap protocol by passing a different AbstractProtocol.
    """

    def __init__(self, protocol: AbstractProtocol | None = None):
        self._proto: AbstractProtocol = protocol or ELM327Protocol()

    def connect(self, port: str = "COM3", baudrate: int = 115200) -> bool:
        return self._proto.connect(port, baudrate)

    def disconnect(self) -> None:
        self._proto.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._proto.is_connected

    # ── Live data ──────────────────────────────────────────────────────────

    def get_live_data(self, pids: list[int] | None = None) -> dict:
        targets = pids or ALL_PIDS
        result = {}
        for pid in targets:
            data = self._proto.read_pid(pid)
            if data.get("value") is not None:
                result[data["name"]] = {"value": data["value"], "unit": data["unit"]}
        return result

    def live_stream(self, pids: list[int] | None = None, hz: int = 10) -> Generator[LiveDataFrame, None, None]:
        interval = 1.0 / max(1, hz)
        while self.is_connected:
            raw = self.get_live_data(pids)
            flat = {k: v["value"] for k, v in raw.items()}
            yield LiveDataFrame(timestamp=time.time(), values=flat)
            time.sleep(interval)

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_all_dtc(self) -> list[DTC]:
        return self._proto.read_dtc()

    def clear_dtc(self) -> bool:
        return self._proto.clear_dtc()

    def get_freeze_frame(self, dtc_code: str) -> dict:
        return self._proto.read_freeze_frame(dtc_code)

    def get_vehicle_info(self) -> dict:
        return self._proto.read_vehicle_info()

    # ── ECU memory (UDS / KWP) ─────────────────────────────────────────────

    def read_ecu_memory(self, start_addr: int, length: int) -> bytes:
        if hasattr(self._proto, "uds_read_memory"):
            return self._proto.uds_read_memory(start_addr, length)
        raise NotImplementedError("Connected protocol does not support memory read")

    def write_ecu_memory(self, start_addr: int, data: bytes) -> bool:
        if hasattr(self._proto, "uds_write_memory"):
            return self._proto.uds_write_memory(start_addr, data)
        raise NotImplementedError("Connected protocol does not support memory write")

    def read_full_flash(self) -> bytes:
        if hasattr(self._proto, "read_full_flash"):
            return self._proto.read_full_flash()
        raise NotImplementedError("Full flash read not supported by this protocol")

    def write_full_flash(self, data: bytes) -> bool:
        if hasattr(self._proto, "write_full_flash"):
            return self._proto.write_full_flash(data)
        raise NotImplementedError("Full flash write not supported by this protocol")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()
