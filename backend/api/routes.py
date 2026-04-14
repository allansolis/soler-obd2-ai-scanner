"""
SOLER OBD2 AI Scanner - API Routes

All REST and WebSocket endpoints for the backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    ClearDTCRequest,
    ClearDTCResponse,
    ConnectRequest,
    DTCItem,
    DTCListResponse,
    DTCSeverity,
    DiagnosisItem,
    DiagnosisResponse,
    ErrorResponse,
    ExportMapRequest,
    ExportMapResponse,
    FreezeFrameData,
    HealthScoreResponse,
    SafetyCheckResponse,
    ScanDetailResponse,
    ScanHistoryItem,
    ScanHistoryResponse,
    SensorListResponse,
    SensorStreamMessage,
    SensorValue,
    SimulationResult,
    StatusResponse,
    ConnectionStatus,
    SupportedPID,
    SupportedPIDsResponse,
    SuccessResponse,
    TuningMapResponse,
    TuningMapValue,
    TuningProfile,
    VehicleInfoResponse,
)
from backend.config import settings
from backend.database.db import get_session
from backend.database.models import (
    DiagnosisRecord,
    DTCRecord,
    ScanRecord,
    SensorReading,
    VehicleProfile,
)
from backend.emulator.elm327_sim import ELM327Emulator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Shared state (managed by the app lifespan, see server.py)
# ---------------------------------------------------------------------------

_emulator: Optional[ELM327Emulator] = None
_connection_status = ConnectionStatus.DISCONNECTED
_connected_at: Optional[float] = None
_connection_port: Optional[str] = None
_connection_error: Optional[str] = None


def _get_emulator() -> ELM327Emulator:
    global _emulator
    if _emulator is None:
        _emulator = ELM327Emulator()
    return _emulator


def set_emulator(emu: ELM327Emulator) -> None:
    """Allow server.py lifespan to inject the emulator instance."""
    global _emulator
    _emulator = emu


# ---------------------------------------------------------------------------
# Connection endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Return current OBD-II connection status."""
    uptime = 0.0
    if _connected_at is not None:
        uptime = time.monotonic() - _connected_at

    emu = _get_emulator()
    voltage: Optional[float] = None
    if _connection_status == ConnectionStatus.CONNECTED:
        try:
            rv = emu.send("ATRV")
            voltage = float(rv.replace("V", ""))
        except (ValueError, AttributeError):
            pass

    return StatusResponse(
        status=_connection_status,
        port=_connection_port,
        protocol=emu.protocol if _connection_status == ConnectionStatus.CONNECTED else None,
        voltage=voltage,
        uptime_seconds=round(uptime, 1),
        error=_connection_error,
    )


@router.post("/connect", response_model=StatusResponse)
async def connect_vehicle(req: ConnectRequest) -> StatusResponse:
    """Connect to the vehicle (or emulator)."""
    global _connection_status, _connected_at, _connection_port, _connection_error

    if _connection_status == ConnectionStatus.CONNECTED:
        raise HTTPException(status_code=409, detail="Already connected")

    _connection_status = ConnectionStatus.CONNECTING
    _connection_error = None

    try:
        emu = _get_emulator()
        emu.protocol = req.protocol
        emu.connect()
        # Initialize adapter
        emu.send("ATZ")
        emu.send("ATE0")
        emu.send("ATL0")
        emu.send(f"ATSP{req.protocol}" if req.protocol != "auto" else "ATSP0")

        _connection_status = ConnectionStatus.CONNECTED
        _connected_at = time.monotonic()
        _connection_port = req.port or "EMULATOR"

        logger.info("Connected to vehicle on port=%s protocol=%s", _connection_port, req.protocol)
    except Exception as exc:
        _connection_status = ConnectionStatus.ERROR
        _connection_error = str(exc)
        logger.error("Connection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return await get_status()


@router.post("/disconnect", response_model=StatusResponse)
async def disconnect_vehicle() -> StatusResponse:
    """Disconnect from the vehicle."""
    global _connection_status, _connected_at, _connection_port, _connection_error

    if _connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(status_code=409, detail="Not connected")

    emu = _get_emulator()
    emu.disconnect()

    _connection_status = ConnectionStatus.DISCONNECTED
    _connected_at = None
    _connection_port = None
    _connection_error = None

    logger.info("Disconnected from vehicle")
    return await get_status()


# ---------------------------------------------------------------------------
# Vehicle Info
# ---------------------------------------------------------------------------

@router.get("/vehicle-info", response_model=VehicleInfoResponse)
async def get_vehicle_info() -> VehicleInfoResponse:
    """Read vehicle identification (VIN, make, model, etc.)."""
    _require_connected()
    emu = _get_emulator()
    info = emu.get_vehicle_info()
    return VehicleInfoResponse(**info)


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

@router.get("/sensors", response_model=SensorListResponse)
async def get_sensors() -> SensorListResponse:
    """Read all current sensor values."""
    _require_connected()
    emu = _get_emulator()
    snapshot = emu.get_sensor_snapshot()

    sensors = [
        SensorValue(pid=pid, name=data["name"], value=data["value"], unit=data["unit"])
        for pid, data in snapshot.items()
    ]
    return SensorListResponse(sensors=sensors, count=len(sensors))


@router.get("/sensors/supported", response_model=SupportedPIDsResponse)
async def get_supported_pids() -> SupportedPIDsResponse:
    """List all PIDs supported by the connected vehicle."""
    _require_connected()
    emu = _get_emulator()
    snapshot = emu.get_sensor_snapshot()

    pids = [
        SupportedPID(
            pid=pid,
            name=data["name"],
            unit=data["unit"],
            description=f"OBD-II PID {pid}",
        )
        for pid, data in snapshot.items()
    ]
    return SupportedPIDsResponse(pids=pids, count=len(pids))


# ---------------------------------------------------------------------------
# WebSocket: real-time sensor streaming
# ---------------------------------------------------------------------------

@router.websocket("/ws/sensors")
async def ws_sensor_stream(ws: WebSocket) -> None:
    """Stream sensor data in real-time over WebSocket."""
    await ws.accept()
    logger.info("WebSocket sensor stream connected")

    emu = _get_emulator()
    interval = 1.0 / settings.sampling.critical_hz

    try:
        while True:
            if _connection_status != ConnectionStatus.CONNECTED:
                await ws.send_json({"event": "disconnected"})
                await asyncio.sleep(1)
                continue

            snapshot = emu.get_sensor_snapshot()
            sensors = [
                SensorValue(pid=pid, name=d["name"], value=d["value"], unit=d["unit"])
                for pid, d in snapshot.items()
            ]
            msg = SensorStreamMessage(sensors=sensors)
            await ws.send_text(msg.model_dump_json())
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.info("WebSocket sensor stream disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await ws.close(code=1011, reason=str(exc))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DTCs
# ---------------------------------------------------------------------------

@router.get("/dtc", response_model=DTCListResponse)
async def get_dtcs() -> DTCListResponse:
    """Read all stored and pending DTCs."""
    _require_connected()
    emu = _get_emulator()

    items: list[DTCItem] = []
    for code in emu.get_all_stored_dtcs():
        info = emu.get_dtc_info(code) or {}
        items.append(DTCItem(
            code=code,
            description=info.get("description", ""),
            severity=DTCSeverity(info.get("severity", "medium")),
            system=info.get("system", ""),
            possible_causes=info.get("possible_causes", []),
            is_pending=False,
        ))
    for code in emu.get_all_pending_dtcs():
        if not any(d.code == code for d in items):
            info = emu.get_dtc_info(code) or {}
            items.append(DTCItem(
                code=code,
                description=info.get("description", ""),
                severity=DTCSeverity(info.get("severity", "medium")),
                system=info.get("system", ""),
                possible_causes=info.get("possible_causes", []),
                is_pending=True,
            ))

    return DTCListResponse(
        dtcs=items,
        count=len(items),
        mil_on=emu.state.mil_on,
    )


@router.get("/dtc/freeze-frame/{dtc_code}", response_model=FreezeFrameData)
async def get_freeze_frame(dtc_code: str) -> FreezeFrameData:
    """Get freeze-frame snapshot for a specific DTC."""
    _require_connected()
    emu = _get_emulator()
    ff = emu.get_freeze_frame(dtc_code.upper())
    if ff is None:
        raise HTTPException(status_code=404, detail=f"No freeze-frame for {dtc_code}")

    sensors = [
        SensorValue(pid="FF", name=name, value=val, unit="")
        for name, val in ff.items()
    ]
    return FreezeFrameData(dtc_code=dtc_code.upper(), sensors=sensors)


@router.post("/dtc/clear", response_model=ClearDTCResponse)
async def clear_dtcs(req: ClearDTCRequest) -> ClearDTCResponse:
    """Clear all DTCs (requires confirmation)."""
    _require_connected()
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Set confirm=true to clear DTCs.",
        )

    emu = _get_emulator()
    count = len(emu.get_all_stored_dtcs()) + len(emu.get_all_pending_dtcs())
    emu.send("04")

    return ClearDTCResponse(
        success=True,
        cleared_count=count,
        message=f"Cleared {count} DTCs and turned off MIL.",
    )


# ---------------------------------------------------------------------------
# Diagnosis & Health
# ---------------------------------------------------------------------------

@router.get("/diagnosis", response_model=DiagnosisResponse)
async def get_diagnosis() -> DiagnosisResponse:
    """Generate a full AI-assisted diagnosis of the vehicle."""
    _require_connected()
    emu = _get_emulator()

    vehicle = VehicleInfoResponse(**emu.get_vehicle_info())
    dtc_resp = await get_dtcs()

    # Build analysis items from DTCs and sensor data
    analysis: list[DiagnosisItem] = []

    for dtc in dtc_resp.dtcs:
        status = "critical" if dtc.severity == DTCSeverity.CRITICAL else (
            "warning" if dtc.severity in (DTCSeverity.MEDIUM, DTCSeverity.HIGH) else "ok"
        )
        analysis.append(DiagnosisItem(
            system=dtc.system or "General",
            status=status,
            message=f"{dtc.code}: {dtc.description}",
            confidence=0.85,
            recommendations=dtc.possible_causes[:2],
        ))

    # Check coolant temp
    snapshot = emu.get_sensor_snapshot()
    coolant = snapshot.get("0105", {}).get("value", 90)
    if isinstance(coolant, (int, float)) and coolant > 105:
        analysis.append(DiagnosisItem(
            system="Cooling",
            status="critical",
            message=f"Coolant temperature elevated at {coolant}C",
            confidence=0.95,
            recommendations=["Check coolant level", "Inspect thermostat"],
        ))

    summary = (
        f"Vehicle has {dtc_resp.count} active DTCs. "
        f"Primary concerns: {', '.join(d.code for d in dtc_resp.dtcs[:3])}."
        if dtc_resp.count > 0
        else "No active DTCs. Vehicle systems appear normal."
    )

    return DiagnosisResponse(
        vehicle=vehicle,
        dtcs=dtc_resp.dtcs,
        analysis=analysis,
        summary=summary,
        ai_model=settings.ai.model,
    )


@router.get("/health-score", response_model=HealthScoreResponse)
async def get_health_score() -> HealthScoreResponse:
    """Calculate vehicle health score 0-100."""
    _require_connected()
    emu = _get_emulator()

    dtc_count = len(emu.get_all_stored_dtcs())
    pending_count = len(emu.get_all_pending_dtcs())
    snapshot = emu.get_sensor_snapshot()

    # Start at 100, deduct points
    score = 100
    breakdown: dict[str, int] = {}

    # DTCs: -15 per stored, -5 per pending
    dtc_penalty = dtc_count * 15 + pending_count * 5
    breakdown["dtc"] = max(0, 100 - dtc_penalty)
    score -= dtc_penalty

    # Coolant temp: penalize if out of range
    coolant = snapshot.get("0105", {}).get("value", 90)
    if isinstance(coolant, (int, float)):
        if coolant > 105 or coolant < 70:
            breakdown["cooling"] = 60
            score -= 10
        else:
            breakdown["cooling"] = 100

    # Battery voltage
    voltage = snapshot.get("0142", {}).get("value", 13.8)
    if isinstance(voltage, (int, float)):
        if voltage < 12.0 or voltage > 15.0:
            breakdown["electrical"] = 70
            score -= 8
        else:
            breakdown["electrical"] = 100

    # Engine load (high idle load is suspicious)
    load = snapshot.get("0104", {}).get("value", 20)
    if isinstance(load, (int, float)):
        if load > 40:
            breakdown["engine"] = 75
            score -= 5
        else:
            breakdown["engine"] = 100

    # Fuel system
    fuel = snapshot.get("012F", {}).get("value", 50)
    if isinstance(fuel, (int, float)):
        breakdown["fuel"] = max(20, int(fuel))
    else:
        breakdown["fuel"] = 100

    score = max(0, min(100, score))

    # Letter grade
    if score >= 95:
        grade = "A+"
    elif score >= 85:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return HealthScoreResponse(
        score=score,
        grade=grade,
        breakdown=breakdown,
        issues_found=dtc_count + pending_count,
    )


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_TUNING_PROFILES: dict[str, dict] = {
    "eco": {
        "name": "Eco Mode",
        "description": "Optimized for fuel economy with smoother throttle response",
        "hp_gain": -5,
        "torque_gain": -3,
        "fuel_change": -12.0,
        "emissions_change": -8.0,
    },
    "stage1": {
        "name": "Stage 1 Performance",
        "description": "Mild remap for better response and modest power gains",
        "hp_gain": 15,
        "torque_gain": 20,
        "fuel_change": 5.0,
        "emissions_change": 3.0,
    },
    "sport": {
        "name": "Sport Mode",
        "description": "Aggressive throttle mapping with higher rev limits",
        "hp_gain": 25,
        "torque_gain": 30,
        "fuel_change": 10.0,
        "emissions_change": 8.0,
    },
    "stage2": {
        "name": "Stage 2 Performance",
        "description": "Maximum performance tune (requires hardware upgrades)",
        "hp_gain": 45,
        "torque_gain": 55,
        "fuel_change": 18.0,
        "emissions_change": 15.0,
        "warnings": [
            "Requires upgraded intake and exhaust",
            "May void manufacturer warranty",
            "Not legal for road use in all jurisdictions",
        ],
    },
}


@router.get("/tuning/maps/{profile}", response_model=TuningMapResponse)
async def get_tuning_maps(profile: TuningProfile) -> TuningMapResponse:
    """Get tuning maps for a specific profile."""
    _require_connected()
    meta = _TUNING_PROFILES.get(profile.value, {})

    # Generate sample ignition timing map
    ignition_map = []
    for rpm in range(1000, 7000, 500):
        for load in [0.2, 0.4, 0.6, 0.8, 1.0]:
            base_timing = 10 + (rpm / 1000) * 3 - load * 8
            modifier = {"eco": -2, "stage1": 2, "sport": 4, "stage2": 6}.get(profile.value, 0)
            ignition_map.append(TuningMapValue(
                rpm=rpm, load=load, value=round(base_timing + modifier, 1), unit="deg"
            ))

    # Generate sample fuel map
    fuel_map = []
    for rpm in range(1000, 7000, 500):
        for load in [0.2, 0.4, 0.6, 0.8, 1.0]:
            base_fuel = 12 + load * 4 - (rpm / 7000) * 2
            modifier = {"eco": 0.5, "stage1": -0.3, "sport": -0.5, "stage2": -0.8}.get(profile.value, 0)
            fuel_map.append(TuningMapValue(
                rpm=rpm, load=load, value=round(base_fuel + modifier, 2), unit="AFR"
            ))

    return TuningMapResponse(
        profile=profile,
        name=meta.get("name", profile.value),
        description=meta.get("description", ""),
        maps={"ignition_timing": ignition_map, "fuel": fuel_map},
        estimated_hp_gain=meta.get("hp_gain"),
        estimated_torque_gain=meta.get("torque_gain"),
        warnings=meta.get("warnings", []),
    )


@router.get("/tuning/safety-check/{profile}", response_model=SafetyCheckResponse)
async def tuning_safety_check(profile: TuningProfile) -> SafetyCheckResponse:
    """Run safety verification before applying a tune."""
    _require_connected()
    emu = _get_emulator()
    snapshot = emu.get_sensor_snapshot()

    checks: dict[str, bool] = {}
    warnings: list[str] = []
    blockers: list[str] = []

    # Coolant temp check
    coolant = snapshot.get("0105", {}).get("value", 90)
    checks["coolant_temp_normal"] = isinstance(coolant, (int, float)) and 70 <= coolant <= 105
    if not checks["coolant_temp_normal"]:
        blockers.append("Coolant temperature out of safe range")

    # Battery voltage
    voltage = snapshot.get("0142", {}).get("value", 13.8)
    checks["battery_voltage_ok"] = isinstance(voltage, (int, float)) and 12.0 <= voltage <= 15.5
    if not checks["battery_voltage_ok"]:
        warnings.append("Battery voltage unstable")

    # No critical DTCs
    dtc_count = len(emu.get_all_stored_dtcs())
    checks["no_critical_dtcs"] = dtc_count == 0
    if not checks["no_critical_dtcs"]:
        warnings.append(f"{dtc_count} active DTCs detected - resolve before tuning")

    # Stage 2 hardware check
    if profile == TuningProfile.STAGE2:
        checks["hardware_upgraded"] = False  # Can't verify in emulator
        blockers.append("Stage 2 requires verified hardware upgrades")

    safe = len(blockers) == 0

    return SafetyCheckResponse(
        profile=profile,
        safe=safe,
        checks=checks,
        warnings=warnings,
        blockers=blockers,
    )


@router.get("/tuning/simulate/{profile}", response_model=SimulationResult)
async def simulate_tuning(profile: TuningProfile) -> SimulationResult:
    """Simulate performance changes for a tuning profile."""
    meta = _TUNING_PROFILES.get(profile.value, {})
    baseline_hp = 158.0  # 2020 Civic 2.0L baseline
    baseline_torque = 138.0

    hp_gain = meta.get("hp_gain", 0)
    torque_gain = meta.get("torque_gain", 0)

    # Generate RPM curve data
    rpm_curve = []
    for rpm in range(1000, 7500, 250):
        factor = 1 - ((rpm - 4000) / 7000) ** 2
        base_hp_at_rpm = baseline_hp * max(0.1, factor * (rpm / 6000))
        base_tq_at_rpm = baseline_torque * max(0.2, factor)
        gain_factor = hp_gain / baseline_hp
        rpm_curve.append({
            "rpm": float(rpm),
            "baseline_hp": round(base_hp_at_rpm, 1),
            "tuned_hp": round(base_hp_at_rpm * (1 + gain_factor), 1),
            "baseline_torque": round(base_tq_at_rpm, 1),
            "tuned_torque": round(base_tq_at_rpm * (1 + torque_gain / baseline_torque), 1),
        })

    return SimulationResult(
        profile=profile,
        baseline_hp=baseline_hp,
        tuned_hp=baseline_hp + hp_gain,
        baseline_torque=baseline_torque,
        tuned_torque=baseline_torque + torque_gain,
        fuel_economy_change_pct=meta.get("fuel_change", 0),
        emissions_change_pct=meta.get("emissions_change", 0),
        rpm_curve=rpm_curve,
    )


@router.post("/tuning/export", response_model=ExportMapResponse)
async def export_tuning_map(req: ExportMapRequest) -> ExportMapResponse:
    """Export a tuning map file."""
    _require_connected()
    filename = f"soler_tune_{req.profile.value}_{int(time.time())}.{req.format}"

    # In production, this would generate a real file.
    # For now, return metadata.
    return ExportMapResponse(
        filename=filename,
        format=req.format,
        size_bytes=4096,
        download_url=f"/api/downloads/{filename}",
    )


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------

@router.post("/ai/chat", response_model=ChatResponse)
async def ai_chat(req: ChatRequest) -> ChatResponse:
    """Chat with the AI diagnostic agent."""
    emu = _get_emulator()

    # Build context from vehicle data if requested
    context = ""
    if req.include_vehicle_context and _connection_status == ConnectionStatus.CONNECTED:
        info = emu.get_vehicle_info()
        snapshot = emu.get_sensor_snapshot()
        dtcs = emu.get_all_stored_dtcs()
        context = (
            f"Vehicle: {info.get('year')} {info.get('make')} {info.get('model')} "
            f"({info.get('engine')}). "
            f"Active DTCs: {', '.join(dtcs) if dtcs else 'None'}. "
            f"RPM: {snapshot.get('010C', {}).get('value', 'N/A')}, "
            f"Coolant: {snapshot.get('0105', {}).get('value', 'N/A')}C."
        )

    # In production, this calls the Anthropic API.
    # For now, return a simulated response.
    reply = _generate_mock_ai_response(req.message, context)

    return ChatResponse(
        reply=reply,
        model=settings.ai.model,
        tokens_used=len(reply.split()) * 2,
    )


def _generate_mock_ai_response(message: str, context: str) -> str:
    """Generate a mock AI response for testing without API key."""
    msg_lower = message.lower()

    if any(w in msg_lower for w in ("dtc", "code", "error", "fault")):
        return (
            "Based on the active DTCs:\n\n"
            "- **P0420** (Catalyst Efficiency Below Threshold): The catalytic converter "
            "may need replacement. Before that, check the downstream O2 sensor.\n\n"
            "- **P0171** (System Too Lean): Check for vacuum leaks at the intake manifold. "
            "Also inspect the MAF sensor for contamination.\n\n"
            "- **P0300** (Random Misfire): Start with spark plugs and ignition coils. "
            "This DTC can also be triggered by the lean condition from P0171.\n\n"
            "I recommend addressing P0171 first, as it may be contributing to the other codes."
        )
    if any(w in msg_lower for w in ("health", "score", "overall")):
        return (
            "Your vehicle's health score reflects the 3 active DTCs. The engine is running "
            "but with some issues that should be addressed. Coolant temperature and battery "
            "voltage are within normal ranges, which is positive."
        )
    if any(w in msg_lower for w in ("tune", "tuning", "performance", "remap")):
        return (
            "I would not recommend any performance tuning until the active DTCs are resolved. "
            "The P0300 misfire code especially needs to be addressed first, as tuning with "
            "an existing misfire can cause engine damage. Once the codes are cleared and the "
            "underlying issues fixed, a Stage 1 tune would be a safe starting point."
        )

    return (
        f"I'm your SOLER AI diagnostic assistant. {context} "
        "How can I help you with your vehicle? I can analyze DTCs, recommend repairs, "
        "discuss tuning options, or explain sensor readings."
    )


# ---------------------------------------------------------------------------
# Scan History
# ---------------------------------------------------------------------------

@router.get("/history", response_model=ScanHistoryResponse)
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ScanHistoryResponse:
    """List scan history."""
    count_result = await session.execute(
        select(ScanRecord.id)
    )
    total = len(count_result.all())

    result = await session.execute(
        select(ScanRecord)
        .order_by(ScanRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    scans = result.scalars().all()

    items = []
    for scan in scans:
        vehicle_summary = ""
        if scan.vehicle:
            v = scan.vehicle
            vehicle_summary = f"{v.year or ''} {v.make or ''} {v.model or ''}".strip()
        items.append(ScanHistoryItem(
            scan_id=scan.id,
            vehicle_vin=scan.vehicle.vin if scan.vehicle else None,
            vehicle_summary=vehicle_summary,
            dtc_count=len(scan.dtc_records) if scan.dtc_records else 0,
            health_score=scan.health_score,
            created_at=scan.created_at,
        ))

    return ScanHistoryResponse(scans=items, total=total)


@router.get("/history/{scan_id}", response_model=ScanDetailResponse)
async def get_scan_detail(
    scan_id: str,
    session: AsyncSession = Depends(get_session),
) -> ScanDetailResponse:
    """Get detailed data for a specific scan."""
    result = await session.execute(
        select(ScanRecord).where(ScanRecord.id == scan_id)
    )
    scan = result.scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    vehicle_resp = None
    if scan.vehicle:
        v = scan.vehicle
        vehicle_resp = VehicleInfoResponse(
            vin=v.vin, make=v.make, model=v.model,
            year=v.year, engine=v.engine, fuel_type=v.fuel_type,
            protocol=v.protocol, ecu_name=v.ecu_name,
        )

    sensors = [
        SensorValue(
            pid=sr.pid, name=sr.name,
            value=sr.value if sr.value is not None else sr.value_text,
            unit=sr.unit or "", timestamp=sr.timestamp,
        )
        for sr in (scan.sensor_readings or [])
    ]

    dtcs = [
        DTCItem(
            code=dr.code, description=dr.description,
            severity=DTCSeverity(dr.severity),
            system=dr.system, possible_causes=dr.possible_causes or [],
            is_pending=dr.is_pending,
        )
        for dr in (scan.dtc_records or [])
    ]

    diagnosis_resp = None
    if scan.diagnosis:
        d = scan.diagnosis
        diagnosis_resp = DiagnosisResponse(
            vehicle=vehicle_resp,
            dtcs=dtcs,
            analysis=[DiagnosisItem(**item) for item in (d.analysis or [])],
            summary=d.summary,
            ai_model=d.ai_model,
            timestamp=d.created_at,
        )

    return ScanDetailResponse(
        scan_id=scan.id,
        vehicle=vehicle_resp,
        sensors=sensors,
        dtcs=dtcs,
        diagnosis=diagnosis_resp,
        health_score=scan.health_score,
        created_at=scan.created_at,
        duration_seconds=scan.duration_seconds or 0.0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_connected() -> None:
    """Raise 409 if not connected to a vehicle."""
    if _connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(
            status_code=409,
            detail="Not connected to a vehicle. Call POST /api/connect first.",
        )
