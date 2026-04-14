"""
SOLER OBD2 AI Scanner - Pydantic v2 Request/Response Schemas
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class DTCSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TuningProfile(str, Enum):
    ECO = "eco"
    STAGE1 = "stage1"
    SPORT = "sport"
    STAGE2 = "stage2"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class ConnectRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    port: Optional[str] = Field(None, description="Serial port (None = auto-detect)")
    baudrate: int = Field(38400, ge=9600, le=500000)
    protocol: str = Field("auto", description="OBD protocol or 'auto'")
    timeout: float = Field(5.0, gt=0, le=30)


class StatusResponse(BaseModel):
    status: ConnectionStatus
    port: Optional[str] = None
    protocol: Optional[str] = None
    voltage: Optional[float] = None
    uptime_seconds: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Vehicle Info
# ---------------------------------------------------------------------------

class VehicleInfoResponse(BaseModel):
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    fuel_type: Optional[str] = None
    protocol: Optional[str] = None
    ecu_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

class SensorValue(BaseModel):
    pid: str
    name: str
    value: float | str | bool | None = None
    unit: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SensorListResponse(BaseModel):
    sensors: list[SensorValue]
    count: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SupportedPID(BaseModel):
    pid: str
    name: str
    description: str = ""
    unit: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class SupportedPIDsResponse(BaseModel):
    pids: list[SupportedPID]
    count: int


class SensorStreamMessage(BaseModel):
    """WebSocket message for real-time sensor streaming."""
    event: str = "sensor_update"
    sensors: list[SensorValue] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# DTC (Diagnostic Trouble Codes)
# ---------------------------------------------------------------------------

class DTCItem(BaseModel):
    code: str = Field(..., description="e.g. P0420")
    description: str = ""
    severity: DTCSeverity = DTCSeverity.MEDIUM
    system: str = ""
    possible_causes: list[str] = []
    is_pending: bool = False


class DTCListResponse(BaseModel):
    dtcs: list[DTCItem]
    count: int
    mil_on: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FreezeFrameData(BaseModel):
    dtc_code: str
    sensors: list[SensorValue] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClearDTCRequest(BaseModel):
    confirm: bool = Field(
        ..., description="Must be True to confirm clearing DTCs"
    )


class ClearDTCResponse(BaseModel):
    success: bool
    cleared_count: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Diagnosis / Health
# ---------------------------------------------------------------------------

class DiagnosisItem(BaseModel):
    system: str
    status: str  # "ok" | "warning" | "critical"
    message: str
    confidence: float = Field(0.0, ge=0, le=1)
    recommendations: list[str] = []


class DiagnosisResponse(BaseModel):
    vehicle: Optional[VehicleInfoResponse] = None
    dtcs: list[DTCItem] = []
    analysis: list[DiagnosisItem] = []
    summary: str = ""
    ai_model: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthScoreResponse(BaseModel):
    score: int = Field(..., ge=0, le=100)
    grade: str = ""  # A+ / A / B / C / D / F
    breakdown: dict[str, int] = {}  # system -> sub-score
    issues_found: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

class TuningMapValue(BaseModel):
    rpm: int
    load: float
    value: float
    unit: str = ""


class TuningMapResponse(BaseModel):
    profile: TuningProfile
    name: str
    description: str = ""
    maps: dict[str, list[TuningMapValue]] = {}  # map_type -> values
    estimated_hp_gain: Optional[float] = None
    estimated_torque_gain: Optional[float] = None
    warnings: list[str] = []


class SafetyCheckResponse(BaseModel):
    profile: TuningProfile
    safe: bool
    checks: dict[str, bool] = {}  # check_name -> passed
    warnings: list[str] = []
    blockers: list[str] = []


class SimulationResult(BaseModel):
    profile: TuningProfile
    baseline_hp: float = 0.0
    tuned_hp: float = 0.0
    baseline_torque: float = 0.0
    tuned_torque: float = 0.0
    fuel_economy_change_pct: float = 0.0
    emissions_change_pct: float = 0.0
    rpm_curve: list[dict[str, float]] = []


class ExportMapRequest(BaseModel):
    profile: TuningProfile
    format: str = Field("csv", description="Export format: csv | json | bin")


class ExportMapResponse(BaseModel):
    filename: str
    format: str
    size_bytes: int
    download_url: str


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    include_vehicle_context: bool = True


class ChatResponse(BaseModel):
    reply: str
    model: str = ""
    tokens_used: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Scan History
# ---------------------------------------------------------------------------

class ScanHistoryItem(BaseModel):
    scan_id: str
    vehicle_vin: Optional[str] = None
    vehicle_summary: str = ""
    dtc_count: int = 0
    health_score: Optional[int] = None
    created_at: datetime


class ScanHistoryResponse(BaseModel):
    scans: list[ScanHistoryItem]
    total: int


class ScanDetailResponse(BaseModel):
    scan_id: str
    vehicle: Optional[VehicleInfoResponse] = None
    sensors: list[SensorValue] = []
    dtcs: list[DTCItem] = []
    diagnosis: Optional[DiagnosisResponse] = None
    health_score: Optional[int] = None
    created_at: datetime
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""
