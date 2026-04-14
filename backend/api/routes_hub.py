"""
SOLER OBD2 AI Scanner - KnowledgeHub API Routes
================================================
Endpoints REST para consultar y administrar el KnowledgeHub central.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from backend.knowledge_hub.hub import KnowledgeHub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hub", tags=["KnowledgeHub"])


# Singleton del hub a nivel de modulo (lazy).
_hub: Optional[KnowledgeHub] = None
_compile_lock = asyncio.Lock()
_compile_state: dict[str, Any] = {"running": False, "last_stats": None}


def get_hub() -> KnowledgeHub:
    global _hub
    if _hub is None:
        _hub = KnowledgeHub()
    return _hub


# ---------------------------------------------------------------------------
# Endpoints de consulta
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_hub(
    q: str = Query(..., min_length=1, description="Texto de busqueda"),
    make: Optional[str] = None,
    system: Optional[str] = None,
    type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Busca en el KnowledgeHub (full-text + filtros)."""
    hub = get_hub()
    filters = {"make": make, "system": system, "type": type, "category": category}
    results = await asyncio.to_thread(hub.search, q, filters, limit)
    return {"query": q, "filters": filters, "count": len(results),
            "results": [r.to_dict() for r in results]}


@router.get("/stats")
async def hub_stats():
    """Estadisticas del KnowledgeHub."""
    hub = get_hub()
    stats = await asyncio.to_thread(hub.get_stats)
    return {
        **stats.to_dict(),
        "compile_running": _compile_state["running"],
        "last_compile": _compile_state["last_stats"],
    }


@router.get("/vehicle/{make}/{model}")
async def vehicle_context(make: str, model: str, year: Optional[int] = None):
    """Contexto completo de un vehiculo."""
    hub = get_hub()
    ctx = await asyncio.to_thread(hub.get_vehicle_full_context, make, model, year)
    if ctx.profile is None and not ctx.resources:
        raise HTTPException(status_code=404, detail="Vehiculo no encontrado")
    return ctx.to_dict()


@router.get("/dtc/{code}")
async def dtc_full_info(code: str, make: Optional[str] = None):
    """Info completa de un DTC + recursos relevantes."""
    hub = get_hub()
    data = await asyncio.to_thread(hub.get_resources_for_dtc, code, make)
    if not data:
        raise HTTPException(status_code=404, detail=f"DTC {code} no encontrado")
    return {"code": code.upper(), "results": data}


@router.get("/resources")
async def list_resources(
    type: Optional[str] = None,
    category: Optional[str] = None,
    make: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Lista paginada de recursos con filtros."""
    hub = get_hub()
    items = await asyncio.to_thread(
        hub.list_resources, type, category, make, source, limit, offset
    )
    return {"count": len(items), "limit": limit, "offset": offset, "items": items}


@router.get("/tuning/{vehicle_id}")
async def tuning_resources(vehicle_id: int):
    """Recursos de tuning para un vehiculo dado."""
    hub = get_hub()
    items = await asyncio.to_thread(hub.get_tuning_resources, vehicle_id)
    return {"vehicle_id": vehicle_id, "count": len(items), "items": items}


@router.get("/ai-context")
async def ai_context(q: str, vehicle_id: Optional[int] = None):
    """Genera contexto markdown para alimentar al AI."""
    hub = get_hub()
    text = await hub.ai_context_for_query(q, vehicle_id)
    return {"query": q, "vehicle_id": vehicle_id, "context": text}


# ---------------------------------------------------------------------------
# Compilacion
# ---------------------------------------------------------------------------

async def _compile_task():
    """Tarea de compilacion en background."""
    if _compile_state["running"]:
        return
    _compile_state["running"] = True
    try:
        hub = get_hub()
        stats = await hub.compile_all()
        _compile_state["last_stats"] = stats.to_dict()
    except Exception as exc:
        logger.exception("Error en compilacion del hub: %s", exc)
        _compile_state["last_stats"] = {"error": str(exc)}
    finally:
        _compile_state["running"] = False


@router.post("/compile")
async def trigger_compile(background: BackgroundTasks):
    """Dispara una compilacion completa del hub en background."""
    if _compile_state["running"]:
        return {"status": "already_running"}
    background.add_task(_compile_task)
    return {"status": "started"}


@router.get("/compile/status")
async def compile_status():
    """Estado de la compilacion en curso."""
    return {
        "running": _compile_state["running"],
        "last_stats": _compile_state["last_stats"],
    }
