"""
Scaner Soler Pro — Backend FastAPI mínimo.

Endpoints:
  GET  /api/hub/dtc/{code}        — Lookup completo de un DTC (base + extended + OEM)
  POST /api/ai/repair-guide       — Guía de reparación basada en KB (AI opcional)
  GET  /api/mapa-noticias         — DTCs + alertas recientes (para el dashboard)
  GET  /api/ev/bms                — Estado BMS más reciente (si hay sesión activa)
  GET  /health                    — Ping de salud

Uso:
  pip install fastapi uvicorn
  python -m scaner_soler.api.server
  # o: uvicorn scaner_soler.api.server:app --port 8765 --reload
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    _FASTAPI_OK = True
except ImportError:
    _FASTAPI_OK = False
    print("WARN: fastapi/pydantic no instalados. Instalar con: pip install fastapi uvicorn pydantic")

from scaner_soler.diagnostic.dtc_database import DTCDatabase
from scaner_soler.knowledge.unified_kb import UnifiedKnowledgeBase

# ── Singletons ────────────────────────────────────────────────────────────────
_db = DTCDatabase()
_kb = UnifiedKnowledgeBase()

# ── Modelos Pydantic ──────────────────────────────────────────────────────────

if _FASTAPI_OK:
    class RepairGuideRequest(BaseModel):
        dtc_code:    str
        make:        Optional[str] = ""
        symptoms:    Optional[list[str]] = []
        mileage_km:  Optional[int] = 0

    class RepairGuideResponse(BaseModel):
        code:              str
        description:       str
        technical_diagnosis: str
        real_solution:     str
        probable_causes:   list[str]
        tools_needed:      list[str]
        estimated_hours:   float
        cost_min_usd:      int
        cost_max_usd:      int
        source:            str

    class DTCInfo(BaseModel):
        code:           str
        description:    str
        system:         str
        severity:       str
        suggested_action: str
        source:         str
        oem_variants:   int
        extended:       Optional[dict] = None

    class MapaNoticiaItem(BaseModel):
        code:        str
        description: str
        severity:    str
        system:      str
        timestamp:   str

# ── App FastAPI ───────────────────────────────────────────────────────────────

def create_app() -> "FastAPI":
    if not _FASTAPI_OK:
        raise ImportError("fastapi no instalado")

    app = FastAPI(
        title="Scaner Soler Pro API",
        version="1.0.0",
        description="Backend para el escáner automotriz — DTCs, guías de reparación, BMS EV.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── /health ───────────────────────────────────────────────────────────────
    @app.get("/health")
    def health():
        stats = _kb.stats()
        return {
            "status": "ok",
            "dtc_codes": stats.get("dtc_codes", 0),
            "ecu_models": stats.get("ecu_models", 0),
            "ev_brands":  stats.get("ev_brands", 0),
        }

    # ── GET /api/hub/dtc/{code} ───────────────────────────────────────────────
    @app.get("/api/hub/dtc/{code}", response_model=DTCInfo)
    def get_dtc(code: str, make: str = Query(default="")):
        """Lookup completo de un código DTC."""
        code = code.upper().strip()
        result = _kb.lookup_dtc(code, make=make)
        if result.get("source") == "unknown":
            raise HTTPException(status_code=404, detail=f"DTC {code} no encontrado")

        # Agregar extended si existe
        extended = _get_extended(code)

        return DTCInfo(
            code=result.get("code", code),
            description=result.get("description", ""),
            system=result.get("system", ""),
            severity=result.get("severity", "info"),
            suggested_action=result.get("suggested_action", ""),
            source=result.get("source", ""),
            oem_variants=result.get("oem_variants", 0),
            extended=extended,
        )

    # ── POST /api/ai/repair-guide ─────────────────────────────────────────────
    @app.post("/api/ai/repair-guide", response_model=RepairGuideResponse)
    def repair_guide(req: RepairGuideRequest):
        """Devuelve guía de reparación profesional para un DTC."""
        code = req.dtc_code.upper().strip()
        extended = _get_extended(code)
        if not extended:
            # Fallback a datos básicos de la KB
            dtc_info = _kb.lookup_dtc(code, make=req.make or "")
            return RepairGuideResponse(
                code=code,
                description=dtc_info.get("description", "Código desconocido"),
                technical_diagnosis="Información detallada no disponible en la base de datos.",
                real_solution=dtc_info.get("suggested_action", "Consultar manual del vehículo."),
                probable_causes=["Consultar manual OEM"],
                tools_needed=["Escáner automotriz"],
                estimated_hours=1.0,
                cost_min_usd=0,
                cost_max_usd=0,
                source="SAE J2012 básico",
            )

        import json
        return RepairGuideResponse(
            code=code,
            description=_kb.lookup_dtc(code).get("description", ""),
            technical_diagnosis=extended.get("technical_diagnosis", ""),
            real_solution=extended.get("real_solution", ""),
            probable_causes=_parse_json_list(extended.get("probable_causes")),
            tools_needed=_parse_json_list(extended.get("tools_needed")),
            estimated_hours=extended.get("estimated_time_hours", 1.0),
            cost_min_usd=extended.get("cost_min_usd", 0),
            cost_max_usd=extended.get("cost_max_usd", 0),
            source="professional",
        )

    # ── GET /api/mapa-noticias ────────────────────────────────────────────────
    @app.get("/api/mapa-noticias")
    def mapa_noticias(limit: int = Query(default=20, ge=1, le=100)):
        """
        DTCs críticos y de advertencia recientes de la base de datos
        (simulación: devuelve los DTCs más graves disponibles).
        """
        from datetime import datetime
        import sqlite3
        with sqlite3.connect(_db.db_path) as con:
            rows = con.execute("""
                SELECT code, description, severity, system
                FROM dtc_codes
                WHERE severity IN ('critical','warning')
                ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, code
                LIMIT ?
            """, (limit,)).fetchall()

        now = datetime.now().isoformat()
        return {
            "timestamp": now,
            "total": len(rows),
            "items": [
                {
                    "code": r[0],
                    "description": r[1],
                    "severity": r[2],
                    "system": r[3] or "",
                    "timestamp": now,
                }
                for r in rows
            ]
        }

    # ── GET /api/ev/bms ───────────────────────────────────────────────────────
    @app.get("/api/ev/bms")
    def ev_bms():
        """Resumen del estado del BMS EV (datos estáticos si no hay sesión activa)."""
        return {
            "connected": False,
            "message": "Sin sesión EV activa. Conecte un adaptador ELM327 a un vehículo EV.",
            "ev_brands_supported": list(_kb.kb.get("ev_brands", {}).keys()),
        }

    # ── GET /api/ev/dtcs ──────────────────────────────────────────────────────
    @app.get("/api/ev/dtcs")
    def ev_dtcs(make: str = Query(default="")):
        """Retorna todos los DTCs EV disponibles en la base de datos."""
        import sqlite3
        with sqlite3.connect(_db.db_path) as con:
            rows = con.execute("""
                SELECT code, description, system, severity, source
                FROM dtc_codes
                WHERE system LIKE 'EV%'
                   OR source LIKE 'SAE J1979-2%'
                   OR source IN ('Nissan','BMW','VW_MEB','Chevrolet','Hyundai')
                ORDER BY code
            """).fetchall()
        return {
            "total": len(rows),
            "dtcs": [
                {"code": r[0], "description": r[1],
                 "system": r[2], "severity": r[3], "source": r[4]}
                for r in rows
            ]
        }

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_extended(code: str) -> dict | None:
    import sqlite3
    try:
        with sqlite3.connect(_db.db_path) as con:
            row = con.execute("""
                SELECT symptoms, technical_diagnosis, real_solution,
                       probable_causes, tools_needed,
                       estimated_time_hours, cost_min_usd, cost_max_usd, cost_labor_usd
                FROM dtc_extended WHERE code=? AND source='professional'
            """, (code,)).fetchone()
        if row:
            return {
                "symptoms":             row[0],
                "technical_diagnosis":  row[1],
                "real_solution":        row[2],
                "probable_causes":      row[3],
                "tools_needed":         row[4],
                "estimated_time_hours": row[5],
                "cost_min_usd":         row[6],
                "cost_max_usd":         row[7],
                "cost_labor_usd":       row[8],
            }
    except Exception:
        pass
    return None


def _parse_json_list(val) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        import json
        result = json.loads(val)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    return [val]


# ── Punto de entrada ──────────────────────────────────────────────────────────

if _FASTAPI_OK:
    app = create_app()

if __name__ == "__main__":
    if not _FASTAPI_OK:
        print("ERROR: instala fastapi y uvicorn: pip install fastapi uvicorn")
        sys.exit(1)
    try:
        import uvicorn
        uvicorn.run("scaner_soler.api.server:app", host="127.0.0.1", port=8765, reload=True)
    except ImportError:
        print("ERROR: instala uvicorn: pip install uvicorn")
