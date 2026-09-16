import csv
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..comm.vehicle_conn import VehicleConnection

SESSIONS_DIR = Path(__file__).parent.parent.parent / "sessions"

FAST_PIDS = [0x0C, 0x0B, 0x11, 0x0E]            # RPM, MAP, TPS, Ignition — 100Hz
SLOW_PIDS = [0x05, 0x0F, 0x5C, 0x0D, 0x10, 0x14] # Temps, speed, MAF, O2 — 10Hz

FAST_HZ = 20    # realistic over ELM327 (true 100Hz needs J2534/CAN direct)
SLOW_HZ = 5


@dataclass
class SessionMeta:
    name: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    sample_count: int = 0
    vehicle_vin: str = ""
    notes: str = ""


class TrackLogger:

    def __init__(self, conn: VehicleConnection, on_frame: Callable | None = None):
        self.conn = conn
        self.on_frame = on_frame    # optional callback for live dashboard
        self._running = False
        self._threads: list[threading.Thread] = []
        self._csv_file = None
        self._csv_writer = None
        self._lock = threading.Lock()
        self.meta: SessionMeta | None = None
        self._columns: list[str] = []

    # ── Session lifecycle ──────────────────────────────────────────────────

    def start(self, session_name: str = "", vin: str = "") -> Path:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = session_name or f"session_{ts}"
        self.meta = SessionMeta(name=name, vehicle_vin=vin)
        path = SESSIONS_DIR / f"{name}_{ts}.csv"
        self._columns = ["timestamp", "source"] + [
            "rpm", "map_kpa", "throttle", "ignition_advance",
            "coolant_temp", "iat", "oil_temp", "speed",
            "maf", "o2_v", "fuel_trim_st", "fuel_trim_lt",
        ]
        self._csv_file = open(path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self._columns, extrasaction="ignore")
        self._csv_writer.writeheader()
        self._running = True
        self._threads = [
            threading.Thread(target=self._fast_loop, daemon=True),
            threading.Thread(target=self._slow_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        return path

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=3.0)
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
        if self.meta:
            self.meta.end_time = datetime.now()

    # ── Sampling loops ─────────────────────────────────────────────────────

    def _fast_loop(self):
        interval = 1.0 / FAST_HZ
        while self._running:
            t0 = time.time()
            try:
                data = self.conn.get_live_data(FAST_PIDS)
                row = {"timestamp": t0, "source": "fast"}
                for k, v in data.items():
                    row[k] = v["value"]
                self._write_row(row)
                if self.on_frame:
                    self.on_frame(row)
            except Exception:
                pass
            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))

    def _slow_loop(self):
        interval = 1.0 / SLOW_HZ
        while self._running:
            t0 = time.time()
            try:
                data = self.conn.get_live_data(SLOW_PIDS)
                row = {"timestamp": t0, "source": "slow"}
                for k, v in data.items():
                    row[k] = v["value"]
                self._write_row(row)
            except Exception:
                pass
            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))

    def _write_row(self, row: dict):
        with self._lock:
            if self._csv_writer:
                self._csv_writer.writerow(row)
                self._csv_file.flush()
                if self.meta:
                    self.meta.sample_count += 1

    @property
    def is_running(self) -> bool:
        return self._running
