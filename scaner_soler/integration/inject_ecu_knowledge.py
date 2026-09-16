"""
Inyecta el conocimiento ECU extraído del PDF (scaner_soler/database/dtc_codes.db)
en las tablas del KnowledgeHub principal (SQLAlchemy / RepairProcedure + DTCCatalog).

Uso:
    python -m scaner_soler.integration.inject_ecu_knowledge
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_SRC  = Path(__file__).parent.parent / "database" / "dtc_codes.db"


def inject_into_knowledge_hub(hub_db_url: str | None = None) -> dict:
    """
    Lee las tablas ecu_models / ecu_faults / ecu_components del SQLite local
    y las inserta en las tablas del KnowledgeHub.
    Devuelve estadísticas de lo insertado.
    """
    try:
        from backend.knowledge_hub.schema import Base, RepairProcedure, DTCCatalog
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        hub_url = hub_db_url or "sqlite:///knowledge_hub.db"
        engine  = create_engine(hub_url)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
    except ImportError:
        # Running outside the FastAPI backend — just report
        return _report_local_stats()

    src_conn = sqlite3.connect(str(DB_SRC))
    inserted_repair = inserted_dtc = 0

    # ── ECU faults → RepairProcedure ─────────────────────────────────────────
    rows = src_conn.execute("""
        SELECT m.ecu_code, m.make, f.symptom, f.solution, f.page_ref
        FROM ecu_faults f JOIN ecu_models m ON f.ecu_id = m.id
    """).fetchall()

    for ecu_code, make, symptom, solution, page in rows:
        existing = session.query(RepairProcedure).filter_by(
            title=symptom[:200], ecu_model=ecu_code
        ).first()
        if not existing:
            rp = RepairProcedure(
                title=symptom[:200],
                ecu_model=ecu_code,
                vehicle_make=make,
                description=symptom,
                procedure=solution,
                source=f"Guia Completo de Reparo de ECUs 2025 p.{page}",
                verified=True,
            )
            session.add(rp)
            inserted_repair += 1

    # ── Generic OBD-II DTCs ──────────────────────────────────────────────────
    dtc_rows = src_conn.execute(
        "SELECT code, description, system, severity FROM dtc_codes"
    ).fetchall()

    for code, description, system, severity in dtc_rows:
        existing = session.query(DTCCatalog).filter_by(code=code).first()
        if not existing:
            session.add(DTCCatalog(
                code=code,
                description=description,
                system=system,
                severity=severity,
                source="SAE J2012 / OBD-II Generic",
            ))
            inserted_dtc += 1

    session.commit()
    session.close()
    src_conn.close()

    return {
        "repair_procedures_inserted": inserted_repair,
        "dtc_codes_inserted": inserted_dtc,
        "total": inserted_repair + inserted_dtc,
    }


def _report_local_stats() -> dict:
    """Stats without FastAPI backend available."""
    if not DB_SRC.exists():
        return {"error": "DB not found", "path": str(DB_SRC)}
    conn = sqlite3.connect(str(DB_SRC))
    models = conn.execute("SELECT COUNT(*) FROM ecu_models").fetchone()[0]
    faults = conn.execute("SELECT COUNT(*) FROM ecu_faults").fetchone()[0]
    comps  = conn.execute("SELECT COUNT(*) FROM ecu_components").fetchone()[0]
    dtcs   = conn.execute("SELECT COUNT(*) FROM dtc_codes").fetchone()[0]
    conn.close()
    return {"ecu_models": models, "ecu_faults": faults,
            "ecu_components": comps, "dtc_codes": dtcs}


if __name__ == "__main__":
    result = inject_into_knowledge_hub()
    print("Integración ECU knowledge → KnowledgeHub:")
    for k, v in result.items():
        print(f"  {k}: {v}")
