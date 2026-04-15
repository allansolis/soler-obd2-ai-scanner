"""
SOLER OBD2 AI Scanner - Knowledge Hub (cerebro central)
========================================================
Compila, indexa y sirve TODO el conocimiento automotriz del scanner
en una unica base de datos SQLite, integrando recursos del Drive,
PDFs locales, perfiles de vehiculos, DTCs, mapas de tuning y
procedimientos de reparacion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker

from backend.knowledge_hub.schema import (
    Base,
    Resource,
    SoftwareTool,
    VehicleProfile,
    DTCCatalog,
    DiagramReference,
    RepairProcedure,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stat dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CompileStats:
    """Estadisticas de una compilacion completa."""
    drive_inventory: int = 0
    local_pdfs: int = 0
    vehicle_db: int = 0
    dtc_db: int = 0
    map_types: int = 0
    repair_guides: int = 0
    online_resources: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    @property
    def total_resources(self) -> int:
        return (
            self.drive_inventory
            + self.local_pdfs
            + self.map_types
            + self.online_resources
        )

    @property
    def total_vehicles(self) -> int:
        return self.vehicle_db

    @property
    def total_dtcs(self) -> int:
        return self.dtc_db

    @property
    def total_pdfs(self) -> int:
        return self.local_pdfs

    @property
    def total_software(self) -> int:
        return self.drive_inventory

    @property
    def db_size_mb(self) -> float:
        return 0.0  # set by caller after compile

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update({
            "total_resources": self.total_resources,
            "total_vehicles": self.total_vehicles,
            "total_dtcs": self.total_dtcs,
            "total_pdfs": self.total_pdfs,
            "total_software": self.total_software,
        })
        return d


@dataclass
class HubStats:
    """Estadisticas del estado actual del hub."""
    total_resources: int = 0
    total_software: int = 0
    total_vehicles: int = 0
    total_dtcs: int = 0
    total_diagrams: int = 0
    total_repair_procedures: int = 0
    total_pdfs_local: int = 0
    total_drive: int = 0
    total_online: int = 0
    db_size_mb: float = 0.0
    last_compiled: Optional[str] = None
    by_category: dict[str, int] = field(default_factory=dict)
    by_make: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    """Resultado de busqueda en el hub."""
    kind: str  # resource, dtc, vehicle, procedure
    id: int
    title: str
    description: str
    score: float
    payload: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VehicleContext:
    """Contexto completo de un vehiculo para el AI."""
    profile: Optional[dict]
    common_dtcs: list[dict]
    resources: list[dict]
    procedures: list[dict]
    tuning_resources: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_make_tags(text: str) -> list[str]:
    """Detecta marcas mencionadas en un texto."""
    text_l = text.lower()
    makes = [
        "toyota", "honda", "nissan", "mazda", "subaru", "mitsubishi", "suzuki",
        "ford", "chevrolet", "gm", "dodge", "chrysler", "jeep", "ram",
        "bmw", "mercedes", "audi", "vw", "volkswagen", "porsche", "skoda", "seat",
        "renault", "peugeot", "citroen", "fiat", "alfa", "opel",
        "hyundai", "kia", "ssangyong", "daewoo",
        "volvo", "scania", "iveco", "man",
        "land rover", "jaguar", "mini", "cooper",
    ]
    found = [m for m in makes if m in text_l]
    # Normalize
    norm_map = {"vw": "volkswagen", "gm": "chevrolet", "alfa": "alfa romeo"}
    return sorted({norm_map.get(m, m) for m in found})


def _detect_system_tags(text: str) -> list[str]:
    """Detecta sistemas mencionados en un texto."""
    text_l = text.lower()
    systems = {
        "engine": ["motor", "engine", "ecu", "ecm", "encendido", "inyeccion"],
        "transmission": ["transmision", "transmission", "caja", "tcm", "atsg", "automatic"],
        "abs": ["abs", "esp", "frenos", "brake"],
        "airbag": ["airbag", "srs", "bolsa"],
        "hvac": ["aire acondicionado", "ac ", "hvac", "climatizacion"],
        "electrical": ["electric", "diagrama", "wiring", "pinout"],
        "tuning": ["tuning", "mapas", "remap", "stage", "winols", "ols"],
        "diagnostic": ["diagnostico", "diagnos", "obd", "scan"],
        "immobilizer": ["immo", "inmoviliz", "immobilizer"],
        "parts_catalog": ["catalogo", "epc", "etka", "partes"],
        "emissions": ["dpf", "egr", "adblue", "scr", "catalitico"],
    }
    found = []
    for tag, kws in systems.items():
        if any(kw in text_l for kw in kws):
            found.append(tag)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# KnowledgeHub
# ---------------------------------------------------------------------------

class KnowledgeHub:
    """Hub central de conocimiento del scanner.

    Compila, indexa y sirve TODO el conocimiento automotriz disponible.
    """

    def __init__(self, db_path: Optional[Path] = None, project_root: Optional[Path] = None):
        # Resolver project root (..\..\..)
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.db_path = db_path or (self.project_root / "data" / "knowledge_hub.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    # ------------------------------------------------------------------
    # Compilacion (asincrona, paraleliza I/O cuando es posible)
    # ------------------------------------------------------------------

    async def compile_all(self) -> CompileStats:
        """Compila todos los recursos disponibles en la base de datos."""
        stats = CompileStats(started_at=datetime.utcnow().isoformat())
        logger.info("KnowledgeHub: iniciando compilacion completa.")

        async def _safe(name: str, coro):
            try:
                return await coro
            except Exception as exc:
                logger.exception("Error en import_%s: %s", name, exc)
                stats.errors.append(f"{name}: {exc}")
                return 0

        stats.drive_inventory = await _safe("drive_inventory", self.import_drive_inventory())
        stats.local_pdfs = await _safe("local_pdfs", self.import_local_pdfs())
        stats.vehicle_db = await _safe("vehicle_db", self.import_vehicle_db())
        stats.dtc_db = await _safe("dtc_database", self.import_dtc_database())
        stats.map_types = await _safe("map_types", self.import_map_types())
        stats.repair_guides = await _safe("repair_guides", self.import_repair_guides())
        stats.online_resources = await _safe("online_resources", self.import_online_resources())
        # Expert profiles -> tambien indexados como SoftwareTool/Resource
        try:
            await asyncio.to_thread(self._import_expert_profiles_sync)
        except Exception as exc:
            logger.exception("Error importing expert profiles: %s", exc)
            stats.errors.append(f"expert_profiles: {exc}")

        stats.finished_at = datetime.utcnow().isoformat()
        try:
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            object.__setattr__(stats, "_db_size_mb", size_mb)
        except OSError:
            pass

        logger.info(
            "KnowledgeHub: compilacion completa. recursos=%d vehiculos=%d dtcs=%d",
            stats.total_resources, stats.total_vehicles, stats.total_dtcs,
        )
        return stats

    # ------------------------------------------------------------------
    # Importadores
    # ------------------------------------------------------------------

    async def import_drive_inventory(self) -> int:
        """Importa data/drive_inventory.md como Resources + SoftwareTool."""
        path = self.project_root / "data" / "drive_inventory.md"
        if not path.exists():
            logger.warning("drive_inventory.md no encontrado: %s", path)
            return 0

        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return await asyncio.to_thread(self._import_drive_inventory_sync, text)

    def _import_drive_inventory_sync(self, text: str) -> int:
        """Parsea el markdown y crea Resources + SoftwareTool."""
        count = 0
        # Match table rows: | **Name** | size | description |
        row_pattern = re.compile(
            r"^\|\s*\*\*([^*|]+)\*\*\s*(?:\([^)]+\))?\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
            re.MULTILINE,
        )

        with self.SessionLocal() as session:
            # Limpia los recursos previos del Drive para evitar duplicados
            session.query(Resource).filter(Resource.source == "google_drive").delete()
            session.commit()

            for m in row_pattern.finditer(text):
                name = m.group(1).strip()
                size_str = m.group(2).strip()
                desc = m.group(3).strip()

                # Skip header row "Archivo" or "Carpeta"
                if name.lower() in ("archivo", "carpeta", "tamano", "compartido por"):
                    continue

                size_bytes = self._parse_size(size_str)
                rtype, category = self._classify_drive_resource(name, desc)

                make_tags = _detect_make_tags(name + " " + desc)
                system_tags = _detect_system_tags(name + " " + desc)

                resource = Resource(
                    name=name,
                    type=rtype,
                    category=category,
                    source="google_drive",
                    source_url=f"drive://{name}",
                    size_bytes=size_bytes,
                    description=desc,
                    make_tags=make_tags,
                    system_tags=system_tags,
                    language="es",
                    is_available_local=False,
                    last_indexed=datetime.utcnow(),
                )
                session.add(resource)
                session.flush()  # get id

                # Si es software, crea SoftwareTool asociado
                if rtype == "software":
                    sw = SoftwareTool(
                        name=name,
                        version=self._extract_version(name),
                        publisher=self._guess_publisher(name),
                        supports_brands=make_tags,
                        supports_features=self._guess_features(name, desc),
                        license_type="commercial",
                        requires_hardware=self._guess_hardware(name),
                        resource_id=resource.id,
                    )
                    session.add(sw)

                count += 1

            session.commit()

        logger.info("import_drive_inventory: %d recursos creados.", count)
        return count

    def _parse_size(self, s: str) -> int:
        """Parsea '6.19 GB', '484 MB', '~62 GB', 'folder' a bytes."""
        s = s.replace("~", "").replace("*", "").strip().lower()
        if not s or s in ("folder", "-", "?"):
            return 0
        m = re.match(r"([\d.]+)\s*(gb|mb|kb|b)?", s)
        if not m:
            return 0
        try:
            num = float(m.group(1))
        except ValueError:
            return 0
        unit = (m.group(2) or "b").lower()
        mult = {"gb": 1024**3, "mb": 1024**2, "kb": 1024, "b": 1}.get(unit, 1)
        return int(num * mult)

    def _classify_drive_resource(self, name: str, desc: str) -> tuple[str, str]:
        text = (name + " " + desc).lower()
        # Software keywords
        sw_kw = ["tuners", "winols", "gds", "epc", "etka", "delphi", "autodata",
                 "mitchell", "dialogys", "alldata", "elsawin", "dicatec",
                 "tecnocar", "simplo", "diagnos", "wow", "tolerance", "ultramate",
                 "scania", "alfa test", "atsg", "bmw 2019"]
        if any(k in text for k in sw_kw):
            cat = "tuning" if "tuners" in text or "winols" in text else "diagnostic"
            return "software", cat
        if "pinout" in text or "ecm pinout" in text:
            return "pinout", "electrical"
        if "diagrama" in text:
            return "diagram", "electrical"
        if "manual" in text:
            return "manual", "repair"
        if "catalogo" in text or "partes" in text:
            return "catalog", "parts_catalog"
        if "immo" in text or "inmoviliz" in text:
            return "database", "immobilizer"
        return "manual", "repair"

    def _extract_version(self, name: str) -> str:
        m = re.search(r"\b(\d+\.\d+(?:\.\d+)?|\d{4})\b", name)
        return m.group(1) if m else ""

    def _guess_publisher(self, name: str) -> str:
        nl = name.lower()
        publishers = {
            "hp tuners": "HP Tuners", "winols": "EVC Electronik",
            "autodata": "Autodata Ltd", "delphi": "Delphi",
            "mitchell": "Mitchell 1", "bosch": "Bosch",
            "hyundai": "Hyundai Motor", "kia": "Kia Motors",
            "toyota": "Toyota Motor", "bmw": "BMW AG",
            "dialogys": "Renault", "etka": "Volkswagen AG",
            "elsawin": "Volkswagen AG", "scania": "Scania AB",
            "dicatec": "Dicatec", "tecnocar": "TecnoCar",
            "simplo": "Simplo", "wow": "Wurth",
            "atsg": "ATSG",
        }
        for k, v in publishers.items():
            if k in nl:
                return v
        return "OEM"

    def _guess_features(self, name: str, desc: str) -> list[str]:
        text = (name + " " + desc).lower()
        feats = []
        if any(k in text for k in ["diagnos", "scan", "obd"]):
            feats.append("diagnostic")
        if any(k in text for k in ["program", "flash", "tuners", "winols"]):
            feats.append("programming")
        if "tuning" in text or "tuners" in text or "winols" in text:
            feats.append("tuning")
        if "partes" in text or "epc" in text or "catalogo" in text:
            feats.append("parts_catalog")
        if "manual" in text or "reparac" in text or "mitchell" in text:
            feats.append("repair_info")
        if "wiring" in text or "diagrama" in text or "pinout" in text:
            feats.append("wiring_diagrams")
        return feats or ["diagnostic"]

    def _guess_hardware(self, name: str) -> str:
        nl = name.lower()
        if "tuners" in nl: return "MPVI2/MPVI3"
        if "winols" in nl: return "KESS / KTAG / J2534"
        if "gds" in nl: return "VCI II"
        if "delphi" in nl: return "DS150E"
        if "bmw" in nl: return "ICOM / ENET"
        if "dialogys" in nl: return "CLIP"
        return ""

    async def import_local_pdfs(self) -> int:
        """Indexa todos los PDFs locales en data/."""
        data_dir = self.project_root / "data"
        if not data_dir.exists():
            return 0
        return await asyncio.to_thread(self._import_local_pdfs_sync, data_dir)

    def _import_local_pdfs_sync(self, data_dir: Path) -> int:
        count = 0
        # Carpetas a indexar (todas las que tengan PDFs)
        skip_dirs = {"knowledge_base", "knowledge_hub", "tuning_maps"}
        with self.SessionLocal() as session:
            session.query(Resource).filter(Resource.source == "local_pdf").delete()
            session.commit()

            pdfs = [
                p for p in data_dir.rglob("*.pdf")
                if not any(part in skip_dirs for part in p.parts)
            ]
            logger.info("Indexando %d PDFs locales...", len(pdfs))

            batch = []
            for pdf in pdfs:
                try:
                    rel = pdf.relative_to(self.project_root)
                except ValueError:
                    rel = pdf
                category_dir = pdf.parts[pdf.parts.index("data") + 1] if "data" in pdf.parts else "general"
                category = self._categorize_dir(category_dir)
                make_tags = _detect_make_tags(pdf.name + " " + category_dir)
                system_tags = _detect_system_tags(pdf.name + " " + category_dir)
                size = pdf.stat().st_size if pdf.exists() else 0

                batch.append(Resource(
                    name=pdf.stem[:500],
                    type="manual" if "manual" in category else "diagram" if "diagrama" in category_dir else "manual",
                    category=category,
                    source="local_pdf",
                    source_url=str(rel).replace("\\", "/"),
                    size_bytes=size,
                    description=f"PDF local en {category_dir}",
                    make_tags=make_tags,
                    system_tags=system_tags,
                    language="es",
                    is_available_local=True,
                    local_path=str(pdf),
                    last_indexed=datetime.utcnow(),
                ))
                count += 1
                if len(batch) >= 200:
                    session.bulk_save_objects(batch)
                    session.commit()
                    batch.clear()
            if batch:
                session.bulk_save_objects(batch)
                session.commit()

        logger.info("import_local_pdfs: %d PDFs indexados.", count)
        return count

    def _categorize_dir(self, dir_name: str) -> str:
        d = dir_name.lower()
        mapping = {
            "obd-diesel": "diagnostic",
            "datos-tecnicos": "engine",
            "abs-esp": "abs",
            "airbag": "airbag",
            "aire-acondicionado": "hvac",
            "transmision": "transmission",
            "localizacion-componentes": "electrical",
            "kit-scaner": "diagnostic",
            "4lap": "tuning",
            "vehicle_profiles": "engine",
            "tuning_maps": "tuning",
            "knowledge_base": "diagnostic",
            "dtc_database": "diagnostic",
        }
        return mapping.get(d, "repair")

    async def import_vehicle_db(self) -> int:
        """Importa vehicle_maps_db.py al hub."""
        return await asyncio.to_thread(self._import_vehicle_db_sync)

    def _import_vehicle_db_sync(self) -> int:
        try:
            from backend.tuning.vehicle_maps_db import VehicleMapDatabase
        except Exception as exc:
            logger.error("No se pudo cargar vehicle_maps_db: %s", exc)
            return 0

        db = VehicleMapDatabase()
        count = 0
        with self.SessionLocal() as session:
            session.query(VehicleProfile).delete()
            session.commit()
            for v in db:
                year_start, year_end = self._parse_year_range(v.year_range)
                profile = VehicleProfile(
                    make=v.make,
                    model=v.model,
                    year_start=year_start,
                    year_end=year_end,
                    engine_code=self._extract_engine_code(v.engine),
                    engine_displacement=self._extract_displacement(v.engine),
                    fuel_type=v.fuel_type,
                    turbo=bool(v.turbo),
                    ecu_type=v.ecu_type,
                    ecu_manufacturer=v.ecu_manufacturer,
                    obd_protocol=self._guess_protocol(v.tuning_notes),
                    common_dtcs=[],
                    known_issues="\n".join(v.known_issues),
                    tuning_notes=v.tuning_notes,
                    tuning_stages_available=[
                        op for op in v.supported_operations
                        if op.startswith("stage")
                    ],
                    related_resources=[],
                )
                session.add(profile)
                count += 1
            session.commit()

        logger.info("import_vehicle_db: %d vehiculos importados.", count)
        return count

    def _parse_year_range(self, yr: str) -> tuple[Optional[int], Optional[int]]:
        nums = re.findall(r"\d{4}", yr or "")
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        if len(nums) == 1:
            return int(nums[0]), int(nums[0])
        return None, None

    def _extract_engine_code(self, engine: str) -> str:
        m = re.search(r"\b([A-Z]\d+[A-Z]*(?:-[A-Z]+)?|[A-Z]{2,4}\d*[A-Z]*)\b", engine or "")
        return m.group(1) if m else ""

    def _extract_displacement(self, engine: str) -> Optional[float]:
        m = re.search(r"(\d\.\d)\s*L", engine or "", re.I)
        return float(m.group(1)) if m else None

    def _guess_protocol(self, notes: str) -> str:
        nl = (notes or "").lower()
        if "kwp2000" in nl or "iso 14230" in nl: return "KWP2000"
        if "iso 9141" in nl: return "ISO 9141-2"
        if "iso 15765" in nl or "can" in nl: return "ISO 15765-4 (CAN)"
        if "j1850" in nl: return "J1850"
        return "ISO 15765-4 (CAN)"

    async def import_dtc_database(self) -> int:
        """Importa data/dtc_database/professional_dtc_database.json."""
        path = self.project_root / "data" / "dtc_database" / "professional_dtc_database.json"
        if not path.exists():
            return 0
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return await asyncio.to_thread(self._import_dtc_db_sync, text)

    def _import_dtc_db_sync(self, text: str) -> int:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("DTC JSON invalido: %s", exc)
            return 0

        count = 0
        with self.SessionLocal() as session:
            session.query(DTCCatalog).delete()
            session.commit()

            for entry in data.get("dtcs", []):
                code = entry.get("code", "").upper()
                if not code:
                    continue
                # Evita duplicados
                existing = session.query(DTCCatalog).filter_by(code=code).first()
                if existing:
                    continue
                cost = entry.get("estimated_cost_usd", {}) or {}
                total_min = float(cost.get("parts_min", 0) or 0) + float(cost.get("labor", 0) or 0)
                total_max = float(cost.get("parts_max", 0) or 0) + float(cost.get("labor", 0) or 0)

                dtc = DTCCatalog(
                    code=code,
                    type=self._dtc_type(code),
                    sae_standard=self._is_sae_standard(code),
                    description_en="",
                    description_es=entry.get("description", ""),
                    severity=entry.get("severity", "medium"),
                    common_symptoms=entry.get("symptoms", []),
                    diagnosis_steps=entry.get("technical_diagnosis", ""),
                    repair_procedure=entry.get("real_solution", ""),
                    probable_causes=entry.get("probable_causes", []),
                    related_makes=[],
                    cost_range_min_usd=total_min,
                    cost_range_max_usd=total_max,
                    time_hours=float(entry.get("estimated_time_hours", 1.0) or 1.0),
                )
                session.add(dtc)
                count += 1
            session.commit()

        logger.info("import_dtc_database: %d DTCs importados.", count)
        return count

    def _dtc_type(self, code: str) -> str:
        if not code: return "unknown"
        c = code[0].upper()
        return {"P": "powertrain", "C": "chassis", "B": "body", "U": "network"}.get(c, "unknown")

    def _is_sae_standard(self, code: str) -> bool:
        # P0xxx, P2xxx, P34xx-P39xx son SAE generic
        if len(code) < 5: return False
        return code[1] in ("0", "2") and code[0] == "P"

    async def import_map_types(self) -> int:
        """Importa el catalogo completo de tipos de mapas de tuning."""
        return await asyncio.to_thread(self._import_map_types_sync)

    def _import_map_types_sync(self) -> int:
        try:
            from backend.tuning.map_types import MapCatalog
        except Exception as exc:
            logger.error("No se pudo cargar map_types: %s", exc)
            return 0

        catalog = MapCatalog()
        count = 0
        with self.SessionLocal() as session:
            # Eliminar map_types previos
            session.query(Resource).filter(
                Resource.source == "builtin",
                Resource.type == "tuning_map_type",
            ).delete()
            session.commit()

            for m in catalog.get_all():
                desc = getattr(m, "description_es", "") or getattr(m, "description", "")
                category = getattr(m, "category", None)
                cat_value = category.value if hasattr(category, "value") else str(category or "tuning")

                resource = Resource(
                    name=getattr(m, "spanish_name", None) or getattr(m, "name", "Mapa"),
                    type="tuning_map_type",
                    category="tuning",
                    source="builtin",
                    source_url=f"map_type://{getattr(m, 'name', '')}",
                    size_bytes=0,
                    description=str(desc)[:1000],
                    make_tags=[],
                    system_tags=["tuning", cat_value],
                    language="es",
                    is_available_local=True,
                    last_indexed=datetime.utcnow(),
                )
                session.add(resource)
                count += 1
            session.commit()

        logger.info("import_map_types: %d tipos de mapa importados.", count)
        return count

    async def import_repair_guides(self) -> int:
        """Importa guias de reparacion de dtc_repair_guide.py."""
        return await asyncio.to_thread(self._import_repair_guides_sync)

    def _import_repair_guides_sync(self) -> int:
        try:
            from backend.ai_agent.dtc_repair_guide import get_repair_database
        except Exception as exc:
            logger.error("No se pudo cargar dtc_repair_guide: %s", exc)
            return 0

        repair_db = get_repair_database()
        count = 0
        with self.SessionLocal() as session:
            session.query(RepairProcedure).delete()
            session.commit()

            for code in repair_db.get_all_codes():
                guide = repair_db.get_guide(code)
                if not guide:
                    continue
                steps = []
                if guide.technical_diagnosis:
                    for i, line in enumerate(
                        [l.strip() for l in guide.technical_diagnosis.split(".") if l.strip()],
                        start=1,
                    ):
                        steps.append({"order": i, "description": line})

                proc = RepairProcedure(
                    title=f"{guide.code} - {guide.description}",
                    system=guide.system,
                    difficulty=self._severity_to_difficulty(guide.severity),
                    time_hours=float(guide.estimated_time_hours or 1.0),
                    tools_required=guide.tools_needed or [],
                    parts_required=[],
                    steps=steps,
                    warnings=[guide.real_solution] if guide.real_solution else [],
                    related_dtcs=[guide.code],
                    applicable_vehicles=[],
                )
                session.add(proc)
                count += 1
            session.commit()

        logger.info("import_repair_guides: %d procedimientos importados.", count)
        return count

    def _severity_to_difficulty(self, severity: str) -> str:
        return {
            "low": "easy", "medium": "medium",
            "high": "hard", "critical": "expert",
        }.get(severity, "medium")

    async def import_online_resources(self) -> int:
        """Marca recursos online conocidos analizados (workshop-manuals, etc)."""
        return await asyncio.to_thread(self._import_online_resources_sync)

    def _import_online_resources_sync(self) -> int:
        sources = [
            ("Workshop Manuals", "https://workshop-manuals.com",
             "Manuales taller multimarca online", "manual", "repair"),
            ("DataCar", "https://datacar.com.ar",
             "Datos tecnicos automotrices", "database", "diagnostic"),
            ("AngelVF", "https://angelvf.es",
             "Recursos tecnicos y diagramas en espanol", "diagram", "electrical"),
            ("OBD-Codes", "https://www.obd-codes.com",
             "Base de datos de codigos OBD-II", "database", "diagnostic"),
            ("AllDataDIY", "https://www.alldatadiy.com",
             "Reparacion DIY con datos OEM", "manual", "repair"),
            ("ECU Connections", "https://www.ecuconnections.com",
             "Foro de tuning y mapas ECU", "database", "tuning"),
            ("WinOLS Damos", "https://winols.com",
             "Bases de datos DAMOS para WinOLS", "database", "tuning"),
            ("HPTuners Forum", "https://forum.hptuners.com",
             "Comunidad HP Tuners", "database", "tuning"),
            ("BimmerForums", "https://www.bimmerforums.com",
             "Comunidad BMW", "database", "diagnostic"),
            ("MBWorld", "https://mbworld.org",
             "Comunidad Mercedes", "database", "diagnostic"),
        ]
        count = 0
        with self.SessionLocal() as session:
            session.query(Resource).filter(Resource.source == "online").delete()
            session.commit()
            for name, url, desc, rtype, cat in sources:
                r = Resource(
                    name=name,
                    type=rtype,
                    category=cat,
                    source="online",
                    source_url=url,
                    size_bytes=0,
                    description=desc,
                    make_tags=_detect_make_tags(name + " " + desc),
                    system_tags=_detect_system_tags(name + " " + desc),
                    language="es",
                    is_available_local=False,
                    last_indexed=datetime.utcnow(),
                )
                session.add(r)
                count += 1
            session.commit()
        logger.info("import_online_resources: %d recursos online indexados.", count)
        return count

    # ------------------------------------------------------------------
    # Expert profiles -> indexar en la DB como SoftwareTool + Resource
    # ------------------------------------------------------------------

    def _import_expert_profiles_sync(self) -> int:
        """Lee expert_profiles.json y crea/actualiza SoftwareTool + Resource."""
        profiles_path = Path(__file__).resolve().parent / "expert_profiles.json"
        if not profiles_path.is_file():
            logger.warning("expert_profiles.json no encontrado, skipping.")
            return 0

        with profiles_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        tools = data.get("tools", {})
        count = 0

        with self.SessionLocal() as session:
            session.query(SoftwareTool).filter(
                SoftwareTool.publisher.like("expert_profile%")
            ).delete(synchronize_session=False)
            for tid, t in tools.items():
                supports = t.get("supports", {}) or {}
                resource = Resource(
                    name=t.get("name", tid),
                    type="software",
                    category=t.get("category", "diagnostic"),
                    source="expert_profile",
                    source_url=t.get("official_url"),
                    size_bytes=0,
                    description=t.get("description_es", ""),
                    make_tags=supports.get("brands", []) or [],
                    system_tags=supports.get("functions", []) or [],
                    language="es",
                    is_available_local=True,
                    last_indexed=datetime.utcnow(),
                )
                session.add(resource)
                session.flush()
                tool = SoftwareTool(
                    name=t.get("name", tid),
                    version="expert",
                    publisher=f"expert_profile:{t.get('publisher','')}",
                    supports_brands=supports.get("brands", []) or [],
                    supports_features=supports.get("functions", []) or [],
                    license_type=t.get("license", "comercial"),
                    requires_hardware=", ".join(t.get("hardware_required", []) or []),
                    resource_id=resource.id,
                )
                session.add(tool)
                count += 1
            session.commit()
        logger.info("_import_expert_profiles_sync: %d perfiles expertos indexados.", count)
        return count

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def search(self, query: str, filters: Optional[dict] = None, limit: int = 50) -> list[SearchResult]:
        """Busqueda full-text basica en toda la DB."""
        filters = filters or {}
        q = (query or "").strip().lower()
        results: list[SearchResult] = []
        if not q:
            return results

        like = f"%{q}%"
        with self.SessionLocal() as session:
            # Resources
            qr = session.query(Resource).filter(
                or_(
                    func.lower(Resource.name).like(like),
                    func.lower(Resource.description).like(like),
                )
            )
            if "make" in filters and filters["make"]:
                m = filters["make"].lower()
                qr = qr.filter(func.lower(Resource.make_tags).like(f"%{m}%"))
            if "system" in filters and filters["system"]:
                s = filters["system"].lower()
                qr = qr.filter(func.lower(Resource.system_tags).like(f"%{s}%"))
            if "type" in filters and filters["type"]:
                qr = qr.filter(Resource.type == filters["type"])
            if "category" in filters and filters["category"]:
                qr = qr.filter(Resource.category == filters["category"])
            for r in qr.limit(limit).all():
                score = 1.0 if q in (r.name or "").lower() else 0.5
                results.append(SearchResult(
                    kind="resource", id=r.id, title=r.name,
                    description=r.description or "", score=score,
                    payload=r.to_dict(),
                ))

            # DTCs
            for d in session.query(DTCCatalog).filter(
                or_(
                    func.lower(DTCCatalog.code).like(like),
                    func.lower(DTCCatalog.description_es).like(like),
                )
            ).limit(limit).all():
                results.append(SearchResult(
                    kind="dtc", id=d.id,
                    title=f"{d.code} - {d.description_es}",
                    description=d.diagnosis_steps[:200],
                    score=1.5 if q == d.code.lower() else 0.8,
                    payload=d.to_dict(),
                ))

            # Vehicles
            qv = session.query(VehicleProfile).filter(
                or_(
                    func.lower(VehicleProfile.make).like(like),
                    func.lower(VehicleProfile.model).like(like),
                    func.lower(VehicleProfile.engine_code).like(like),
                )
            )
            for v in qv.limit(limit).all():
                results.append(SearchResult(
                    kind="vehicle", id=v.id,
                    title=f"{v.make} {v.model} ({v.year_start}-{v.year_end})",
                    description=v.tuning_notes[:200] if v.tuning_notes else "",
                    score=0.9, payload=v.to_dict(),
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def get_vehicle_full_context(
        self, make: str, model: str, year: Optional[int] = None
    ) -> VehicleContext:
        """Retorna el contexto completo disponible para un vehiculo."""
        with self.SessionLocal() as session:
            q = session.query(VehicleProfile).filter(
                func.lower(VehicleProfile.make) == make.lower(),
                func.lower(VehicleProfile.model).like(f"%{model.lower()}%"),
            )
            if year is not None:
                q = q.filter(
                    VehicleProfile.year_start <= year,
                    VehicleProfile.year_end >= year,
                )
            profile = q.first()

            # Recursos con make_tag
            resources = session.query(Resource).filter(
                func.lower(Resource.make_tags).like(f"%{make.lower()}%")
            ).limit(50).all()

            # DTCs comunes (asociados a la marca o no especifico)
            dtcs = []
            if profile and profile.common_dtcs:
                dtcs = session.query(DTCCatalog).filter(
                    DTCCatalog.code.in_(profile.common_dtcs)
                ).all()

            # Procedimientos
            procs = session.query(RepairProcedure).limit(20).all()

            # Tuning resources
            tuning_res = session.query(Resource).filter(
                Resource.category == "tuning",
            ).limit(20).all()

            return VehicleContext(
                profile=profile.to_dict() if profile else None,
                common_dtcs=[d.to_dict() for d in dtcs],
                resources=[r.to_dict() for r in resources],
                procedures=[p.to_dict() for p in procs],
                tuning_resources=[t.to_dict() for t in tuning_res],
            )

    def get_resources_for_dtc(self, dtc: str, make: Optional[str] = None) -> list[dict]:
        """Recursos relevantes para un DTC."""
        results: list[dict] = []
        with self.SessionLocal() as session:
            d = session.query(DTCCatalog).filter(
                func.upper(DTCCatalog.code) == dtc.upper()
            ).first()
            if d:
                results.append({"kind": "dtc", **d.to_dict()})

            # Procedimientos relacionados
            procs = session.query(RepairProcedure).filter(
                func.lower(RepairProcedure.title).like(f"%{dtc.lower()}%")
            ).all()
            results.extend({"kind": "procedure", **p.to_dict()} for p in procs)

            # Recursos por sistema (si DTC P -> engine, C -> chassis, etc.)
            system = "engine" if dtc.upper().startswith("P") else "electrical"
            qr = session.query(Resource).filter(
                func.lower(Resource.system_tags).like(f"%{system}%")
            )
            if make:
                qr = qr.filter(func.lower(Resource.make_tags).like(f"%{make.lower()}%"))
            for r in qr.limit(20).all():
                results.append({"kind": "resource", **r.to_dict()})
        return results

    def get_tuning_resources(self, vehicle_id: int) -> list[dict]:
        """Software y mapas de tuning para un vehiculo."""
        with self.SessionLocal() as session:
            v = session.get(VehicleProfile, vehicle_id)
            if not v:
                return []
            mlow = v.make.lower()
            resources = session.query(Resource).filter(
                Resource.category == "tuning",
                func.lower(Resource.make_tags).like(f"%{mlow}%"),
            ).all()
            # tambien todos los tipos de mapa builtin
            map_types = session.query(Resource).filter(
                Resource.type == "tuning_map_type"
            ).all()
            return [r.to_dict() for r in resources] + [m.to_dict() for m in map_types]

    def get_stats(self) -> HubStats:
        """Estadisticas actuales del hub."""
        with self.SessionLocal() as session:
            total_resources = session.query(func.count(Resource.id)).scalar() or 0
            total_software = session.query(func.count(SoftwareTool.id)).scalar() or 0
            total_vehicles = session.query(func.count(VehicleProfile.id)).scalar() or 0
            total_dtcs = session.query(func.count(DTCCatalog.id)).scalar() or 0
            total_diagrams = session.query(func.count(DiagramReference.id)).scalar() or 0
            total_procs = session.query(func.count(RepairProcedure.id)).scalar() or 0

            total_pdfs = session.query(func.count(Resource.id)).filter(
                Resource.source == "local_pdf"
            ).scalar() or 0
            total_drive = session.query(func.count(Resource.id)).filter(
                Resource.source == "google_drive"
            ).scalar() or 0
            total_online = session.query(func.count(Resource.id)).filter(
                Resource.source == "online"
            ).scalar() or 0

            # By category
            cat_rows = session.query(Resource.category, func.count(Resource.id)).group_by(Resource.category).all()
            by_category = {c: n for c, n in cat_rows}

            # By make
            make_rows = session.query(VehicleProfile.make, func.count(VehicleProfile.id)).group_by(VehicleProfile.make).all()
            by_make = {m: n for m, n in make_rows}

            last_dt = session.query(func.max(Resource.last_indexed)).scalar()

        size_mb = 0.0
        try:
            if self.db_path.exists():
                size_mb = self.db_path.stat().st_size / (1024 * 1024)
        except OSError:
            pass

        return HubStats(
            total_resources=total_resources,
            total_software=total_software,
            total_vehicles=total_vehicles,
            total_dtcs=total_dtcs,
            total_diagrams=total_diagrams,
            total_repair_procedures=total_procs,
            total_pdfs_local=total_pdfs,
            total_drive=total_drive,
            total_online=total_online,
            db_size_mb=round(size_mb, 2),
            last_compiled=last_dt.isoformat() if last_dt else None,
            by_category=by_category,
            by_make=by_make,
        )

    def list_resources(
        self,
        type_: Optional[str] = None,
        category: Optional[str] = None,
        make: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Lista recursos con filtros."""
        with self.SessionLocal() as session:
            q = session.query(Resource)
            if type_: q = q.filter(Resource.type == type_)
            if category: q = q.filter(Resource.category == category)
            if source: q = q.filter(Resource.source == source)
            if make:
                q = q.filter(func.lower(Resource.make_tags).like(f"%{make.lower()}%"))
            return [r.to_dict() for r in q.offset(offset).limit(limit).all()]

    # ------------------------------------------------------------------
    # AI Integration
    # ------------------------------------------------------------------

    async def ai_context_for_query(
        self, query: str, vehicle_id: Optional[int] = None
    ) -> str:
        """Genera un bloque de contexto formateado para que el AI responda."""
        results = self.search(query, limit=8)
        lines = [f"# Contexto KnowledgeHub para: {query}", ""]

        if vehicle_id is not None:
            with self.SessionLocal() as session:
                v = session.get(VehicleProfile, vehicle_id)
                if v:
                    lines.append("## Vehiculo activo")
                    lines.append(f"- {v.make} {v.model} ({v.year_start}-{v.year_end})")
                    lines.append(f"- Motor: {v.engine_code}, ECU: {v.ecu_type}")
                    if v.tuning_notes:
                        lines.append(f"- Notas: {v.tuning_notes[:300]}")
                    lines.append("")

        if results:
            lines.append("## Resultados relevantes")
            for r in results:
                lines.append(f"- [{r.kind}] {r.title}")
                if r.description:
                    lines.append(f"    {r.description[:200]}")
            lines.append("")

        stats = self.get_stats()
        lines.append("## Inventario disponible")
        lines.append(
            f"- {stats.total_resources} recursos, {stats.total_dtcs} DTCs, "
            f"{stats.total_vehicles} vehiculos, {stats.total_pdfs_local} PDFs locales."
        )
        return "\n".join(lines)
