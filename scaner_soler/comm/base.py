from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DTC:
    code: str
    category: str       # P=Powertrain B=Body C=Chassis U=Network
    status: str         # confirmed | pending | permanent
    description: str = ""
    system: str = ""
    severity: str = "warning"   # critical | warning | info
    freeze_frame: dict = field(default_factory=dict)
    first_seen: datetime = field(default_factory=datetime.now)
    occurrence_count: int = 1
    suggested_action: str = ""

    @classmethod
    def from_raw_code(cls, code: str) -> "DTC":
        category_map = {"P": "Powertrain", "B": "Body", "C": "Chassis", "U": "Network"}
        category = category_map.get(code[0].upper(), "Unknown") if code else "Unknown"
        return cls(code=code.upper(), category=category, status="pending")


@dataclass
class LiveDataFrame:
    timestamp: float
    values: dict    # {pid_name: value}
    rpm: Optional[float] = None
    speed_kmh: Optional[float] = None
    coolant_temp: Optional[float] = None
    throttle_pct: Optional[float] = None
    map_kpa: Optional[float] = None
    maf_gs: Optional[float] = None
    ignition_advance: Optional[float] = None
    lambda_value: Optional[float] = None
    knock_sensor: Optional[float] = None

    def __post_init__(self):
        self.rpm = self.values.get("rpm")
        self.speed_kmh = self.values.get("speed")
        self.coolant_temp = self.values.get("coolant_temp")
        self.throttle_pct = self.values.get("throttle")
        self.map_kpa = self.values.get("map_kpa")
        self.maf_gs = self.values.get("maf")
        self.ignition_advance = self.values.get("ignition_advance")
        self.lambda_value = self.values.get("lambda")
        self.knock_sensor = self.values.get("knock")


class AbstractProtocol(ABC):

    @abstractmethod
    def connect(self, port: str, baudrate: int = 115200) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def send_raw(self, data: bytes, timeout: float = 5.0) -> bytes: ...

    @abstractmethod
    def read_pid(self, pid: int, mode: int = 0x01) -> dict: ...

    @abstractmethod
    def read_dtc(self) -> list[DTC]: ...

    @abstractmethod
    def clear_dtc(self) -> bool: ...

    @abstractmethod
    def read_freeze_frame(self, dtc_code: str) -> dict: ...

    @abstractmethod
    def read_vehicle_info(self) -> dict: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
