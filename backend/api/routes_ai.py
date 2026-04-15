"""
SOLER OBD2 AI Scanner - AI-specific routes.

Expone endpoints para el AI Copilot:
- POST /api/ai/scan-full
- POST /api/ai/repair-guide
- POST /api/ai/tune-guide
- POST /api/ai/research
- POST /api/ai/learn
- POST /api/ai/clear-dtc
- POST /api/ai/chat
- POST /api/ai/propose-skill
- GET  /api/ai/knowledge-stats
- GET  /api/ai/weekly-report
- WebSocket /api/ai/live-guide
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.ai_agent.copilot_orchestrator import CopilotOrchestrator
from backend.ai_agent.self_improvement import SelfImprovementEngine
from backend.ai_agent.web_researcher import WebResearcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ---------------------------------------------------------------------------
# Singletons (lazy-built)
# ---------------------------------------------------------------------------

_orchestrator: Optional[CopilotOrchestrator] = None
_learning: Optional[SelfImprovementEngine] = None
_web: Optional[WebResearcher] = None


def _get_web() -> WebResearcher:
    global _web
    if _web is None:
        _web = WebResearcher()
    return _web


def _get_orchestrator() -> CopilotOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CopilotOrchestrator(web_researcher=_get_web())
    return _orchestrator


def _get_learning() -> SelfImprovementEngine:
    global _learning
    if _learning is None:
        _learning = SelfImprovementEngine()
    return _learning


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VehiclePayload(BaseModel):
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    ecu_type: Optional[str] = Field(default=None, alias="ecuType")

    class Config:
        populate_by_name = True


class ScanFullRequest(BaseModel):
    vehicle: Optional[VehiclePayload] = None


class RepairGuideRequest(BaseModel):
    dtc_code: str = Field(..., alias="dtc_code")
    vehicle: Optional[VehiclePayload] = None

    class Config:
        populate_by_name = True


class TuneGuideRequest(BaseModel):
    profile: str
    vehicle: Optional[VehiclePayload] = None


class ResearchRequest(BaseModel):
    query: str
    vehicle: Optional[VehiclePayload] = None


class ClearDTCRequest(BaseModel):
    dtc_code: str
    vehicle: Optional[VehiclePayload] = None


class ChatRequest(BaseModel):
    message: str
    vehicle: Optional[VehiclePayload] = None


class LearnRequest(BaseModel):
    sessionId: str
    outcome: dict
    vehicle: Optional[VehiclePayload] = None
    actions: Optional[list[dict]] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/scan-full")
async def scan_full(req: ScanFullRequest) -> dict:
    vehicle = req.vehicle.model_dump() if req.vehicle else None
    result = await _get_orchestrator().full_scan_workflow(vehicle)
    return result.to_dict()


@router.post("/repair-guide")
async def repair_guide(req: RepairGuideRequest) -> dict:
    vehicle = req.vehicle.model_dump() if req.vehicle else None
    guide = await _get_orchestrator().guided_repair_workflow(req.dtc_code, vehicle)
    return guide.to_dict()


@router.post("/tune-guide")
async def tune_guide(req: TuneGuideRequest) -> dict:
    vehicle = req.vehicle.model_dump() if req.vehicle else None
    guide = await _get_orchestrator().guided_tune_workflow(req.profile, vehicle)
    return guide.to_dict()


@router.post("/research")
async def research(req: ResearchRequest) -> dict:
    vehicle = req.vehicle.model_dump() if req.vehicle else None
    return await _get_orchestrator().web_research(req.query, vehicle)


@router.post("/clear-dtc")
async def clear_dtc(req: ClearDTCRequest) -> dict:
    vehicle = req.vehicle.model_dump() if req.vehicle else None
    result = await _get_orchestrator().clear_dtc_safely(req.dtc_code, vehicle)
    return result.to_dict()


@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    message = req.message.strip()
    if not message:
        return {"answer": "Hola, dime en que puedo ayudarte."}

    # Try real Claude first
    try:
        from backend.ai_agent.claude_client import get_claude_client
        claude = get_claude_client()
        if claude.enabled:
            from backend.knowledge_hub import KnowledgeHub
            hub = KnowledgeHub()
            try:
                context = await hub.ai_context_for_query(message)
            except TypeError:
                context = hub.ai_context_for_query(message)  # type: ignore
            context_str = str(context)[:3000]
            system = (
                "Eres un asistente experto en diagnostico automotriz OBD2 de SOLER.\n"
                f"Contexto relevante del KnowledgeHub:\n{context_str}\n\n"
                "Responde en español, conciso, profesional. Si no sabes, dilo."
            )
            response = await claude.complete(system, message)
            if response:
                return {"answer": response, "response": response, "source": "claude"}
    except Exception as e:  # noqa: BLE001
        logger.warning("Claude path failed, fallback: %s", e)

    lower = message.lower()
    if "escan" in lower:
        return {
            "answer": (
                "Perfecto, puedo ejecutar un escaneo completo. "
                "Presiona 'Escanear' en las acciones rapidas."
            )
        }
    if any(k in lower for k in ("dtc", "codigo", "código", "falla")):
        return {
            "answer": (
                "Dime el codigo exacto (ej. P0420) y genero una guia de reparacion "
                "paso a paso cruzando mi base de conocimiento."
            )
        }
    if "tune" in lower or "mapa" in lower:
        return {
            "answer": (
                "Puedo generar un tune optimizado validando seguridad antes de flashear. "
                "Selecciona un perfil en la pagina de Tuning."
            )
        }
    return {
        "answer": (
            f"Entendido: '{message}'. Estoy aqui para guiarte en escaneo, "
            f"diagnostico, reparacion y tuning. ¿Que deseas hacer?"
        )
    }


@router.post("/learn")
async def learn(req: LearnRequest) -> dict:
    await _get_orchestrator().learn_from_outcome(req.sessionId, req.outcome)

    # Tambien registra en SelfImprovementEngine
    learn_engine = _get_learning()
    outcome = req.outcome or {}
    kind = outcome.get("type", "scan")
    if kind == "repair":
        await learn_engine.record_repair_success(
            dtc_code=str(outcome.get("dtcCode", "")),
            repair_action=str(outcome.get("action", "")),
            success=bool(outcome.get("success", False)),
        )
    elif kind == "tune":
        await learn_engine.record_tune_result(
            tune_profile=str(outcome.get("profile", "")),
            before=outcome.get("before", {}),
            after=outcome.get("after", {}),
        )
    else:
        await learn_engine.record_scan_outcome(
            scan_data=outcome.get("scanData", {}),
            outcome=outcome,
        )
    return {"status": "recorded"}


@router.get("/knowledge-stats")
async def knowledge_stats() -> dict:
    stats = _get_learning().get_stats()
    return {
        "dtcCount": stats.get("repairs", 0),
        "pdfCount": 0,
        "rulesCount": 0,
        "lastUpdated": "",
        "lessonsLearned": stats.get("lessonsLearned", 0),
        "scans": stats.get("scans", 0),
        "tunes": stats.get("tunes", 0),
    }


@router.get("/weekly-report")
async def weekly_report() -> dict:
    report = await _get_learning().generate_weekly_report()
    return report.to_dict()


@router.post("/propose-skill")
async def propose_skill() -> dict:
    proposals = await _get_learning().propose_new_functionality()
    return {"proposals": [p.to_dict() for p in proposals]}


# ---------------------------------------------------------------------------
# Live guidance WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/live-guide")
async def live_guide(ws: WebSocket) -> None:
    """Stream de guia en vivo desde el AI Copilot."""
    await ws.accept()
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "message": "Copiloto SOLER listo. Envia 'action' para recibir guia.",
                }
            )
        )
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "JSON invalido"}))
                continue

            action = msg.get("action")
            if action == "scan":
                for i, step in enumerate(
                    [
                        "Conectando al vehiculo...",
                        "Leyendo sensores...",
                        "Leyendo DTCs...",
                        "Analizando con reglas AI...",
                        "Generando reporte final...",
                    ],
                    start=1,
                ):
                    await ws.send_text(
                        json.dumps({"type": "step", "order": i, "message": step})
                    )
                    await asyncio.sleep(0.3)
                result = await _get_orchestrator().full_scan_workflow(msg.get("vehicle"))
                await ws.send_text(json.dumps({"type": "done", "result": result.to_dict()}))
            elif action == "repair":
                guide = await _get_orchestrator().guided_repair_workflow(
                    msg.get("dtcCode", ""), msg.get("vehicle")
                )
                await ws.send_text(json.dumps({"type": "done", "result": guide.to_dict()}))
            else:
                await ws.send_text(
                    json.dumps({"type": "ack", "received": action or "unknown"})
                )
    except WebSocketDisconnect:
        logger.info("live_guide websocket desconectado")
    except Exception as exc:  # noqa: BLE001
        logger.exception("live_guide error: %s", exc)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
