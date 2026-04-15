"""
SOLER OBD2 AI Scanner - Inyector de conocimiento estructurado
==============================================================
Script que toma `expert_knowledge.json` y lo inyecta en la base SQLite
del KnowledgeHub (`data/knowledge_hub.db`).

- Upserta DTCs enriquecidos en la tabla `dtc_catalog`.
- Inserta torque specs como Resources con type='torque_spec'.
- Inserta component locations como Resources con type='component_location'.
- Inserta decision trees como RepairProcedure.

Uso:
    python -m backend.knowledge_hub.inject_knowledge
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from backend.knowledge_hub.hub import KnowledgeHub
from backend.knowledge_hub.schema import (
    DTCCatalog,
    Resource,
    RepairProcedure,
)

logger = logging.getLogger(__name__)

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "expert_knowledge.json"


# ---------------------------------------------------------------------------
# Helpers de mapeo
# ---------------------------------------------------------------------------

def _dtc_type_from_code(code: str) -> str:
    if not code:
        return "powertrain"
    ch = code[0].upper()
    return {
        "P": "powertrain",
        "C": "chassis",
        "B": "body",
        "U": "network",
    }.get(ch, "powertrain")


def _diagnostic_tree_to_text(tree: list[dict]) -> str:
    lines = []
    for s in tree or []:
        step = s.get("step", "?")
        rest = "; ".join(f"{k}={v}" for k, v in s.items() if k != "step")
        lines.append(f"{step}. {rest}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Upsert de DTCs
# ---------------------------------------------------------------------------

def upsert_dtc(session, code: str, info: dict) -> bool:
    existing = session.execute(
        select(DTCCatalog).where(DTCCatalog.code == code)
    ).scalar_one_or_none()

    cost_min, cost_max = 0.0, 0.0
    rng = info.get("cost_range_usd") or []
    if len(rng) >= 2:
        cost_min = float(rng[0])
        cost_max = float(rng[1])

    if existing:
        existing.description_es = info.get("description_es") or existing.description_es
        existing.severity = info.get("severity") or existing.severity
        existing.common_symptoms = info.get("symptoms") or existing.common_symptoms
        existing.diagnosis_steps = (
            _diagnostic_tree_to_text(info.get("diagnostic_tree") or [])
            or existing.diagnosis_steps
        )
        existing.probable_causes = info.get("probable_causes") or existing.probable_causes
        existing.related_makes = info.get("affected_makes") or existing.related_makes
        existing.cost_range_min_usd = cost_min or existing.cost_range_min_usd
        existing.cost_range_max_usd = cost_max or existing.cost_range_max_usd
        existing.time_hours = info.get("time_hours", existing.time_hours)
        existing.type = _dtc_type_from_code(code)
        return False
    else:
        session.add(
            DTCCatalog(
                code=code,
                type=_dtc_type_from_code(code),
                sae_standard=True,
                description_es=info.get("description_es") or "",
                description_en="",
                severity=info.get("severity") or "medium",
                common_symptoms=info.get("symptoms") or [],
                diagnosis_steps=_diagnostic_tree_to_text(info.get("diagnostic_tree") or []),
                probable_causes=info.get("probable_causes") or [],
                related_makes=info.get("affected_makes") or [],
                cost_range_min_usd=cost_min,
                cost_range_max_usd=cost_max,
                time_hours=float(info.get("time_hours") or 1.0),
            )
        )
        return True


# ---------------------------------------------------------------------------
# Upsert de torque specs como Resources
# ---------------------------------------------------------------------------

def upsert_torque_spec(session, component: str, vehicle_key: str, data: dict) -> bool:
    name = f"Torque: {component} - {vehicle_key}"
    existing = session.execute(
        select(Resource).where(Resource.name == name)
    ).scalar_one_or_none()
    description = f"{data.get('spec_es', '')} (unit: {data.get('unit', 'Nm')})"
    if data.get("sequence"):
        description += f" | Secuencia: {data['sequence']}"
    if existing:
        existing.description = description
        existing.last_indexed = datetime.utcnow()
        return False
    session.add(
        Resource(
            name=name,
            type="torque_spec",
            category="engine",
            source="builtin",
            source_url="backend/knowledge_hub/expert_knowledge.json",
            description=description,
            make_tags=[vehicle_key.split()[0].lower()] if vehicle_key else [],
            system_tags=[component],
            language="es",
            is_available_local=True,
            last_indexed=datetime.utcnow(),
        )
    )
    return True


# ---------------------------------------------------------------------------
# Upsert de component locations como Resources
# ---------------------------------------------------------------------------

def upsert_component_location(session, component: str, data: dict) -> bool:
    name = f"Ubicacion componente: {component}"
    existing = session.execute(
        select(Resource).where(Resource.name == name)
    ).scalar_one_or_none()
    desc_lines = []
    for k, v in data.items():
        desc_lines.append(f"{k}: {v}")
    description = " | ".join(desc_lines)[:2000]
    if existing:
        existing.description = description
        existing.last_indexed = datetime.utcnow()
        return False
    session.add(
        Resource(
            name=name,
            type="component_location",
            category="diagnostic",
            source="builtin",
            source_url="backend/knowledge_hub/expert_knowledge.json",
            description=description,
            system_tags=[component],
            language="es",
            is_available_local=True,
            last_indexed=datetime.utcnow(),
        )
    )
    return True


# ---------------------------------------------------------------------------
# Upsert de decision trees como RepairProcedure
# ---------------------------------------------------------------------------

def upsert_decision_tree(session, name: str, steps: list[dict]) -> bool:
    title = f"Decision Tree: {name}"
    existing = session.execute(
        select(RepairProcedure).where(RepairProcedure.title == title)
    ).scalar_one_or_none()
    struct_steps = [
        {
            "order": s.get("step", idx + 1),
            "title": str(s.get("check", "")),
            "description": "; ".join(f"{k}={v}" for k, v in s.items() if k not in ("step", "check")),
        }
        for idx, s in enumerate(steps or [])
    ]
    if existing:
        existing.steps = struct_steps
        return False
    session.add(
        RepairProcedure(
            title=title,
            system="engine",
            difficulty="medium",
            time_hours=1.5,
            tools_required=["scanner OBD2", "multimetro"],
            parts_required=[],
            steps=struct_steps,
            warnings=[],
            related_dtcs=[],
            applicable_vehicles=[],
        )
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> dict:
    logging.basicConfig(level=logging.INFO)
    if not KNOWLEDGE_FILE.exists():
        logger.error("No existe %s", KNOWLEDGE_FILE)
        return {"ok": False, "reason": "missing_file"}

    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    hub = KnowledgeHub()
    stats = {
        "dtcs_new": 0,
        "dtcs_updated": 0,
        "torques_new": 0,
        "torques_updated": 0,
        "locations_new": 0,
        "locations_updated": 0,
        "trees_new": 0,
        "trees_updated": 0,
    }

    with hub.SessionLocal() as session:
        # DTCs
        for code, info in (data.get("dtc_knowledge") or {}).items():
            # saltamos pseudo-alias con _alt/_extended
            if not code or "_" in code:
                continue
            if not info or info.get("_note"):
                continue
            created = upsert_dtc(session, code.upper(), info)
            if created:
                stats["dtcs_new"] += 1
            else:
                stats["dtcs_updated"] += 1

        # Torque specs
        for component, vehicles in (data.get("torque_specs") or {}).items():
            if not isinstance(vehicles, dict):
                continue
            for vehicle_key, spec in vehicles.items():
                if not isinstance(spec, dict):
                    continue
                created = upsert_torque_spec(session, component, vehicle_key, spec)
                if created:
                    stats["torques_new"] += 1
                else:
                    stats["torques_updated"] += 1

        # Component locations
        for comp, meta in (data.get("component_locations") or {}).items():
            if not isinstance(meta, dict):
                continue
            created = upsert_component_location(session, comp, meta)
            if created:
                stats["locations_new"] += 1
            else:
                stats["locations_updated"] += 1

        # Decision trees
        for tree_name, steps in (data.get("decision_trees") or {}).items():
            if not isinstance(steps, list):
                continue
            created = upsert_decision_tree(session, tree_name, steps)
            if created:
                stats["trees_new"] += 1
            else:
                stats["trees_updated"] += 1

        session.commit()

    logger.info("Inyeccion completada: %s", stats)
    return {"ok": True, "stats": stats}


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
