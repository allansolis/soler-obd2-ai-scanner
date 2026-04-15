"""Registra el catalogo de AutoTech Automotriz en el KnowledgeHub.

Lee data/autotech_catalog.json e inserta cada recurso encontrado como
un `Resource` con source='autotech' en data/knowledge_hub.db.

Uso:
    python register_autotech.py

No sobrescribe recursos ya existentes (busqueda por name + source_url).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

# Permitir imports del backend
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.knowledge_hub.schema import Base, Resource


CATALOG_PATH = ROOT / "data" / "autotech_catalog.json"
DB_PATH = ROOT / "data" / "knowledge_hub.db"


def _category_for_module(slug: str) -> str:
    mapping = {
        "electricidad-automotriz": "electrical",
        "cerrajeria-automotriz": "immobilizer",
        "programacion-diagnostico": "diagnostic",
        "motores-diesel": "engine",
        "transmisiones": "transmission",
        "hp-tuners": "tuning",
    }
    return mapping.get(slug, "repair")


def _resource_exists(session, name: str, url: str | None) -> bool:
    q = session.query(Resource).filter(Resource.name == name, Resource.source == "autotech")
    if url:
        q = q.filter(Resource.source_url == url)
    return session.query(q.exists()).scalar()


def register() -> int:
    if not CATALOG_PATH.exists():
        print(f"ERROR: no existe el catalogo {CATALOG_PATH}")
        return 0

    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        catalog = json.load(f)

    engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()

    added = 0
    skipped = 0

    # 1) Modulos de cursos
    for mod in catalog.get("modules", []):
        name = f"AutoTech - {mod['name']} ({mod.get('courses_count', 0)} cursos)"
        url = mod.get("url")
        if _resource_exists(session, name, url):
            skipped += 1
            continue
        session.add(Resource(
            name=name,
            type="course",
            category=_category_for_module(mod.get("slug", "")),
            source="autotech",
            source_url=url,
            description=(mod.get("content") or {}).get("description", ""),
            make_tags=[],
            system_tags=[mod.get("slug", "")],
            language="es",
            is_available_local=False,
            last_indexed=datetime.utcnow(),
        ))
        added += 1

    # 2) Colecciones de Google Drive
    for col in catalog.get("drive_collections", []):
        name = f"AutoTech Drive - {col['name']}"
        if _resource_exists(session, name, None):
            skipped += 1
            continue
        session.add(Resource(
            name=name,
            type=col.get("type", "archive"),
            category=col.get("category", "repair"),
            source="autotech",
            source_url=None,
            description=f"Coleccion Google Drive enlazada desde AutoTech: {col['name']}",
            make_tags=[],
            system_tags=["google_drive", "autotech"],
            language="es",
            is_available_local=False,
            last_indexed=datetime.utcnow(),
        ))
        added += 1

    # 3) Software packs
    for sw in catalog.get("software_packs", []):
        name = f"AutoTech SW - {sw['name']}"
        if _resource_exists(session, name, None):
            skipped += 1
            continue
        session.add(Resource(
            name=name,
            type="software",
            category=sw.get("category", "diagnostic"),
            source="autotech",
            source_url=None,
            description=f"Pack de software enlazado desde AutoTech: {sw['name']}",
            make_tags=[],
            system_tags=["google_drive", "autotech", "software"],
            language="es",
            is_available_local=False,
            last_indexed=datetime.utcnow(),
        ))
        added += 1

    session.commit()
    session.close()

    print(f"Catalogo AutoTech registrado.")
    print(f"  Recursos agregados : {added}")
    print(f"  Recursos omitidos  : {skipped} (ya existian)")
    print(f"  DB                 : {DB_PATH}")
    return added


if __name__ == "__main__":
    register()
