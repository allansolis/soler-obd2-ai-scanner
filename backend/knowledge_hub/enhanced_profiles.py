"""
SOLER OBD2 AI Scanner - Enhanced Expert Profiles
================================================
Cruza expert_profiles.json con pdf_analysis.json para producir un perfil
enriquecido de cada herramienta/base de datos:

    tool_id -> {
        ...(campos originales)...,
        "real_world_evidence": {
            "pdfs_mentioning_tool": [...],
            "dtcs_found_near_tool": [...],
            "supported_makes_in_corpus": [...],
        }
    }

Tambien expone `get_real_world_evidence(tool_id)` para uso programatico
(desde ExpertAdvisor / API).

Uso CLI:
    python backend/knowledge_hub/enhanced_profiles.py  # escribe enhanced_profiles.json
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from knowledge_graph import get_graph, KnowledgeGraph  # type: ignore

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_JSON = Path(__file__).resolve().parent / "expert_profiles.json"
ENHANCED_JSON = Path(__file__).resolve().parent / "enhanced_profiles.json"


@dataclass
class RealWorldEvidence:
    tool_id: str
    pdfs_mentioning_tool: list[dict] = field(default_factory=list)
    dtcs_found_near_tool: list[str] = field(default_factory=list)
    supported_makes_in_corpus: list[str] = field(default_factory=list)
    sample_procedures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def get_real_world_evidence(tool_id: str, graph: Optional[KnowledgeGraph] = None,
                            max_pdfs: int = 8) -> RealWorldEvidence:
    """
    Retorna evidencia REAL de un tool extraida de los manuales analizados.
    Si no hay pdf_analysis.json, retorna una estructura vacia (no falla).
    """
    g = graph or get_graph()
    evidences = g.evidence_for_tool(tool_id, limit=max_pdfs)
    dtc_counter: Counter[str] = Counter()
    make_counter: Counter[str] = Counter()
    procedures: list[str] = []

    for ev in evidences:
        pdf = g._pdfs_by_file.get(ev.pdf) or {}  # noqa: SLF001 - acceso interno por rendimiento
        for d in (pdf.get("dtcs_mentioned") or []):
            dtc_counter[d] += 1
        for v in (pdf.get("vehicles_mentioned") or []):
            mk = v.get("make")
            if mk:
                make_counter[mk] += 1
        for p in (pdf.get("procedures") or [])[:3]:
            if p not in procedures:
                procedures.append(p)

    return RealWorldEvidence(
        tool_id=tool_id,
        pdfs_mentioning_tool=[
            {"pdf": e.pdf, "title": e.title, "category": e.category,
             "system": e.system, "pages": e.pages, "why": e.why}
            for e in evidences
        ],
        dtcs_found_near_tool=[d for d, _ in dtc_counter.most_common(30)],
        supported_makes_in_corpus=[m for m, _ in make_counter.most_common(15)],
        sample_procedures=procedures[:6],
    )


def build_enhanced_profiles(output: Path = ENHANCED_JSON) -> dict[str, Any]:
    """Genera enhanced_profiles.json fusionando perfiles + evidencia real."""
    if not PROFILES_JSON.is_file():
        raise SystemExit(f"No se encontro {PROFILES_JSON}")

    with PROFILES_JSON.open("r", encoding="utf-8") as fp:
        profiles = json.load(fp)

    g = get_graph()
    tools = profiles.get("tools", {}) or {}
    enhanced: dict[str, Any] = {}
    for tid, tool in tools.items():
        ev = get_real_world_evidence(tid, graph=g)
        enhanced[tid] = {**tool, "real_world_evidence": ev.to_dict()}

    payload = {
        **{k: v for k, v in profiles.items() if k != "tools"},
        "tools": enhanced,
        "enhancement_source": "pdf_analysis.json + expert_profiles.json",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    logger.info("enhanced_profiles -> %s (%d tools)", output, len(enhanced))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build_enhanced_profiles()
    print(f"OK -> {ENHANCED_JSON}")
    sys.exit(0)
