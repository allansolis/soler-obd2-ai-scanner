"""
SOLER OBD2 AI Scanner - Expert Advisor API Routes
==================================================
Endpoints REST para el modo experto. Da recomendaciones de herramientas
y workflows segun escenario (DTC, tuning, programacion).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.knowledge_hub.expert_advisor import get_advisor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/expert", tags=["ExpertAdvisor"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AdviseRequest(BaseModel):
    scenario: str = Field(..., description="dtc | tuning | programming")
    dtc: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    goal: Optional[str] = None
    task: Optional[str] = None


class CompareRequest(BaseModel):
    tool_ids: list[str] = Field(..., min_length=2, max_length=6)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tools")
async def list_expert_tools():
    """Lista todos los perfiles expertos disponibles."""
    advisor = get_advisor()
    return {"tools": advisor.list_tools(), "total": len(advisor.list_tools())}


@router.get("/tool/{tool_id}")
async def get_tool_profile(tool_id: str):
    """Retorna el perfil profundo de una herramienta."""
    advisor = get_advisor()
    tool = advisor.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' no encontrada")
    return tool


@router.post("/advise")
async def advise(req: AdviseRequest):
    """Da consejo experto: recomienda herramientas y workflow segun escenario."""
    advisor = get_advisor()
    scenario = req.scenario.lower().strip()

    if scenario == "dtc":
        if not req.dtc:
            raise HTTPException(status_code=400, detail="dtc requerido para scenario=dtc")
        recs = advisor.recommend_tools_for_dtc(req.dtc, req.make, req.year)
    elif scenario == "tuning":
        if not req.make:
            raise HTTPException(status_code=400, detail="make requerido para scenario=tuning")
        recs = advisor.recommend_tools_for_tuning(req.make, req.model, req.year, req.goal or "stage1")
    elif scenario == "programming":
        if not req.make:
            raise HTTPException(status_code=400, detail="make requerido para scenario=programming")
        recs = advisor.recommend_tools_for_programming(req.make, req.model, req.year, req.task or "key_programming")
    else:
        raise HTTPException(status_code=400, detail=f"scenario invalido: {scenario}")

    return {
        "scenario": scenario,
        "input": req.model_dump(),
        "recommendations": [r.to_dict() for r in recs],
        "total": len(recs),
    }


@router.get("/workflow/{tool_id}/{task}")
async def get_workflow(tool_id: str, task: str):
    """Retorna el workflow paso a paso para una herramienta + tarea."""
    advisor = get_advisor()
    wf = advisor.get_workflow(tool_id, task)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' no encontrada")
    return wf.to_dict()


@router.post("/compare")
async def compare(req: CompareRequest):
    """Compara N herramientas en una matriz."""
    advisor = get_advisor()
    matrix = advisor.compare_tools(req.tool_ids)
    if not matrix.tool_ids:
        raise HTTPException(status_code=404, detail="Ninguna herramienta encontrada")
    return matrix.to_dict()


@router.post("/reload")
async def reload_profiles():
    """Recarga el JSON de perfiles desde disco."""
    advisor = get_advisor()
    advisor.reload()
    return {"reloaded": True, "total_tools": len(advisor.list_tools())}


# ---------------------------------------------------------------------------
# Evidencia real extraida de PDFs (knowledge_graph)
# ---------------------------------------------------------------------------

@router.get("/evidence/tool/{tool_id}")
async def evidence_for_tool(tool_id: str, dtc: Optional[str] = None, limit: int = 8):
    """PDFs locales que citan el tool (+ opcionalmente el DTC)."""
    advisor = get_advisor()
    return advisor.get_evidence(tool_id, dtc=dtc, limit=limit)


@router.get("/evidence/dtc/{dtc}")
async def evidence_for_dtc(dtc: str, limit: int = 10):
    """PDFs locales que mencionan el DTC."""
    advisor = get_advisor()
    g = advisor._get_graph()  # type: ignore[attr-defined]
    if g is None:
        return {"available": False, "dtc": dtc.upper(), "pdfs": []}
    return {
        "available": True,
        "dtc": dtc.upper(),
        "pdfs": [e.to_dict() for e in g.evidence_for_dtc(dtc, limit=limit)],
        "info": g.dtc_info(dtc),
    }


@router.get("/context")
async def vehicle_context(
    make: str,
    model: Optional[str] = None,
    year: Optional[int] = None,
    dtc: Optional[str] = None,
):
    """Contexto completo del vehiculo + DTC: PDFs, procedimientos, torques."""
    advisor = get_advisor()
    return advisor.context_for_vehicle(make=make, model=model or "", year=year, dtc=dtc)


@router.post("/advise_with_evidence")
async def advise_with_evidence(req: AdviseRequest):
    """Como /advise pero adjunta evidencia real de manuales por cada rec."""
    advisor = get_advisor()
    if req.scenario.lower() != "dtc":
        raise HTTPException(status_code=400, detail="solo scenario=dtc por ahora")
    if not req.dtc:
        raise HTTPException(status_code=400, detail="dtc requerido")
    recs = advisor.recommend_tools_for_dtc_with_evidence(req.dtc, req.make, req.year)
    return {"scenario": "dtc", "input": req.model_dump(), "recommendations": recs, "total": len(recs)}
