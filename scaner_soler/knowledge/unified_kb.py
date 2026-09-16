"""
UnifiedKnowledgeBase
====================
Single entry-point for all diagnostic knowledge in Scaner Soler Pro.

Sources (in priority order):
  1. Local SQLite  — dtc_codes.db  (always available, offline)
  2. Backend HTTP  — http://localhost:8000  (optional, enriches results when available)

Usage
-----
    from scaner_soler.knowledge import UnifiedKnowledgeBase

    kb = UnifiedKnowledgeBase()
    info = kb.lookup_dtc("P0300", make="VAG")
    guide = kb.get_repair_guide("P0300")
    results = kb.search_dtc("misfire")
    tools = kb.get_expert_tools(scenario="ECU tuning", brands=["VAG", "BMW"])
    print(kb.stats())
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# Optional — graceful fallback if requests not installed
try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

from scaner_soler.diagnostic.dtc_database import DTCDatabase

_DB_PATH = Path(__file__).parent.parent / "database" / "dtc_codes.db"
_BACKEND_URL = "http://localhost:8000"
_HTTP_TIMEOUT = 1  # seconds — must not block the UI


class UnifiedKnowledgeBase:
    """
    Unified read-only interface to all diagnostic knowledge.

    Parameters
    ----------
    db_path : Path, optional
        Path to the SQLite database.  Defaults to the bundled dtc_codes.db.
    backend_url : str, optional
        Base URL for the FastAPI backend.  Pass ``None`` to disable HTTP look-ups.
    """

    def __init__(
        self,
        db_path: Path = _DB_PATH,
        backend_url: str | None = _BACKEND_URL,
    ) -> None:
        self._db_path = Path(db_path)
        self._backend_url = backend_url
        self._dtc_db = DTCDatabase(self._db_path)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _http_get(self, path: str) -> dict | list | None:
        """GET from backend with a hard timeout; returns None on any error."""
        if not _REQUESTS_OK or not self._backend_url:
            return None
        try:
            resp = _requests.get(f"{self._backend_url}{path}", timeout=_HTTP_TIMEOUT)
            if resp.ok:
                return resp.json()
        except Exception:
            pass
        return None

    def _extended_row(self, code: str) -> dict:
        """Return the dtc_extended row for *code* or an empty dict."""
        with self._conn() as con:
            tbls = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "dtc_extended" not in tbls:
                return {}
            row = con.execute(
                "SELECT symptoms, technical_diagnosis, real_solution, probable_causes, "
                "tools_needed, estimated_time_hours, cost_min_usd, cost_max_usd, cost_labor_usd "
                "FROM dtc_extended WHERE code=?",
                (code.upper(),)
            ).fetchone()
            if not row:
                return {}
            def _loads(v):
                if v is None:
                    return []
                try:
                    return json.loads(v)
                except Exception:
                    return [v] if v else []
            return {
                "symptoms": _loads(row[0]),
                "technical_diagnosis": row[1] or "",
                "real_solution": row[2] or "",
                "probable_causes": _loads(row[3]),
                "tools_needed": _loads(row[4]),
                "estimated_time_hours": row[5],
                "cost_min_usd": row[6],
                "cost_max_usd": row[7],
                "cost_labor_usd": row[8],
            }

    # ── Public API ────────────────────────────────────────────────────────────

    def lookup_dtc(self, code: str, make: str = "") -> dict:
        """
        Look up a single DTC code.

        Returns a dict with at minimum:
            code, description, system, severity, source

        Extended fields (from dtc_extended / backend) when available:
            symptoms, technical_diagnosis, real_solution, probable_causes,
            tools_needed, estimated_time_hours, estimated_cost_usd, oem_variants
        """
        code = code.upper().strip()

        # 1 — local base lookup
        result: dict[str, Any] = self._dtc_db.lookup(code, make=make)

        # 2 — enrich from dtc_extended (local)
        ext = self._extended_row(code)
        if ext:
            result.update(ext)
            cost = {}
            if ext.get("cost_min_usd") is not None:
                cost["parts_min"] = ext["cost_min_usd"]
            if ext.get("cost_max_usd") is not None:
                cost["parts_max"] = ext["cost_max_usd"]
            if ext.get("cost_labor_usd") is not None:
                cost["labor"] = ext["cost_labor_usd"]
            if cost:
                result["estimated_cost_usd"] = cost

        # 3 — enrich from backend (non-blocking)
        backend_data = self._http_get(f"/api/hub/dtc/{code}")
        if backend_data and isinstance(backend_data, dict):
            for k, v in backend_data.items():
                if k not in result or not result[k]:
                    result[k] = v

        return result

    def search_dtc(self, query: str, make: str = "") -> list[dict]:
        """
        Full-text search across DTC codes and descriptions.

        Returns a list of dicts, each with at minimum:
            code, description, system, severity, source
        """
        results = self._dtc_db.search(query, make=make)

        # Try to add extended data for each match (best-effort)
        for item in results:
            ext = self._extended_row(item["code"])
            if ext:
                item.update(ext)

        return results

    def get_repair_guide(self, code: str) -> str:
        """
        Return a Markdown repair guide for the given DTC code.

        If extended data is available, produces a structured guide.
        Otherwise produces a basic guide from the base dtc_codes table.
        """
        code = code.upper().strip()

        # 1 — try backend AI guide first (richest result)
        backend = self._http_get(f"/api/ai/repair-guide?code={code}")
        if backend and isinstance(backend, dict) and backend.get("guide"):
            return str(backend["guide"])

        # 2 — build from local data
        base = self._dtc_db.lookup(code)
        ext = self._extended_row(code)

        lines: list[str] = []
        lines.append(f"# Guía de Reparación — {code}")
        lines.append("")
        lines.append(f"**Descripción:** {base.get('description', 'Sin descripción')}")
        lines.append(f"**Sistema:** {base.get('system', 'Desconocido')}")
        lines.append(f"**Severidad:** {base.get('severity', 'desconocida').upper()}")
        lines.append("")

        if ext:
            # Detailed guide from professional database
            if ext.get("symptoms"):
                lines.append("## Síntomas")
                for s in ext["symptoms"]:
                    lines.append(f"- {s}")
                lines.append("")

            if ext.get("probable_causes"):
                lines.append("## Causas Probables")
                for i, c in enumerate(ext["probable_causes"], 1):
                    lines.append(f"{i}. {c}")
                lines.append("")

            if ext.get("technical_diagnosis"):
                lines.append("## Diagnóstico Técnico")
                lines.append(ext["technical_diagnosis"])
                lines.append("")

            if ext.get("real_solution"):
                lines.append("## Solución")
                lines.append(ext["real_solution"])
                lines.append("")

            if ext.get("tools_needed"):
                lines.append("## Herramientas Necesarias")
                for t in ext["tools_needed"]:
                    lines.append(f"- {t}")
                lines.append("")

            cost_parts: list[str] = []
            if ext.get("cost_min_usd") is not None and ext.get("cost_max_usd") is not None:
                cost_parts.append(
                    f"Repuestos: ${ext['cost_min_usd']}–${ext['cost_max_usd']} USD"
                )
            if ext.get("cost_labor_usd") is not None:
                cost_parts.append(f"Mano de obra: ~${ext['cost_labor_usd']} USD")
            if ext.get("estimated_time_hours") is not None:
                cost_parts.append(f"Tiempo estimado: {ext['estimated_time_hours']}h")
            if cost_parts:
                lines.append("## Estimación de Costos")
                for cp in cost_parts:
                    lines.append(f"- {cp}")
                lines.append("")
        else:
            # Basic guide from SAE data only
            suggested = base.get("suggested_action") or base.get("fix_hint", "")
            if suggested:
                lines.append("## Acción Sugerida")
                lines.append(suggested)
                lines.append("")

            lines.append("## Pasos de Diagnóstico Básicos")
            lines.append("1. Verificar condición de la batería y tierra del motor.")
            lines.append("2. Inspeccionar cableado y conectores del sensor relacionado.")
            lines.append("3. Escanear parámetros en vivo (PIDs) para confirmar el fallo.")
            lines.append("4. Comparar valores con especificaciones del fabricante.")
            lines.append("5. Reemplazar componente defectuoso si se confirma el fallo.")
            lines.append("")
            lines.append(
                "> *Esta guía básica se generó desde los datos SAE J2012. "
                "Importa `professional_dtc_database.json` para obtener guías detalladas.*"
            )

        return "\n".join(lines)

    def search_ecu_faults(self, make: str = "", keyword: str = "") -> list[dict]:
        """
        Search ECU repair knowledge.  Delegates to DTCDatabase.

        Returns list of dicts with keys: ecu, make, symptom, solution, page.
        """
        return self._dtc_db.search_ecu_faults(make=make, keyword=keyword)

    def get_expert_tools(
        self, scenario: str = "", brands: list[str] | None = None
    ) -> list[dict]:
        """
        Return professional diagnostic/tuning tools from the expert_tools table.

        Filters by *brands* (list of brand names) and/or free-text *scenario*
        (matched against use_cases and description).  Returns all tools when
        called with no filters.
        """
        with self._conn() as con:
            tbls = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "expert_tools" not in tbls:
                return []

            rows = con.execute(
                "SELECT tool_id, name, category, publisher, description, "
                "brands, use_cases, strengths, limitations, "
                "license_type, price_range, hardware_required, official_url "
                "FROM expert_tools"
            ).fetchall()

        def _loads(v):
            if v is None:
                return []
            try:
                return json.loads(v)
            except Exception:
                return [v] if v else []

        results = []
        for row in rows:
            tool: dict[str, Any] = {
                "tool_id": row[0],
                "name": row[1],
                "category": row[2],
                "publisher": row[3],
                "description": row[4],
                "brands": _loads(row[5]),
                "use_cases": _loads(row[6]),
                "strengths": _loads(row[7]),
                "limitations": _loads(row[8]),
                "license_type": row[9],
                "price_range": row[10],
                "hardware_required": bool(row[11]),
                "official_url": row[12],
            }

            # Brand filter
            if brands:
                supported = {b.lower() for b in tool["brands"]}
                if not any(b.lower() in supported for b in brands):
                    continue

            # Scenario free-text filter
            if scenario:
                haystack = (
                    " ".join(tool["use_cases"]) + " " + (tool["description"] or "")
                ).lower()
                if scenario.lower() not in haystack:
                    continue

            results.append(tool)

        return results

    def stats(self) -> dict:
        """
        Return a summary of all knowledge in the local database.

        Keys:
            dtc_codes, oem_variants, dtc_extended, ecu_models, ecu_faults,
            ecu_components, expert_tools, tables
        """
        with self._conn() as con:
            tbls = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}

            def _count(table: str) -> int:
                if table not in tbls:
                    return 0
                return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

            ecu_info = self._dtc_db.ecu_stats()

            return {
                "dtc_codes": _count("dtc_codes"),
                "oem_variants": _count("oem_desc"),
                "dtc_extended": _count("dtc_extended"),
                "ecu_models": ecu_info.get("models", 0),
                "ecu_faults": ecu_info.get("faults", 0),
                "ecu_components": ecu_info.get("components", 0),
                "expert_tools": _count("expert_tools"),
                "tables": sorted(tbls),
                "ecu_by_make": ecu_info.get("by_make", {}),
                "backend_available": self._check_backend(),
            }

    def _check_backend(self) -> bool:
        """Return True if the FastAPI backend is reachable."""
        data = self._http_get("/health")
        return data is not None
