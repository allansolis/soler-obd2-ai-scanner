"""
SOLER OBD2 AI Scanner - Knowledge Hub Schema
=============================================
Modelos SQLAlchemy del KnowledgeHub. Define la estructura de la base
de datos SQLite que centraliza todos los recursos automotrices del
sistema: software, manuales, diagramas, perfiles de vehiculos, DTCs
y procedimientos de reparacion.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator


# ---------------------------------------------------------------------------
# JSON column type (SQLite-safe for list/dict)
# ---------------------------------------------------------------------------

class JSONList(TypeDecorator):
    """Lista o dict serializado como JSON en TEXT."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or value == "":
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []


Base = declarative_base()


# ---------------------------------------------------------------------------
# Resource - recurso generico (manual, software, video, base de datos)
# ---------------------------------------------------------------------------

class Resource(Base):
    """Cualquier recurso automotriz indexable.

    Cubre desde software de diagnostico (HP TUNERS, AUTODATA), hasta
    PDFs locales, diagramas de Drive, cursos online, catalogos de
    partes y bases de datos especializadas.
    """

    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(512), nullable=False, index=True)
    type = Column(String(64), nullable=False, index=True)
    # type: software, manual, diagram, pinout, course, database, catalog, video
    category = Column(String(64), nullable=False, index=True)
    # category: diagnostic, tuning, repair, electrical, engine, transmission,
    #           parts_catalog, abs, airbag, hvac, immobilizer, oem
    source = Column(String(64), nullable=False, index=True)
    # source: google_drive, local_pdf, online, github, builtin
    source_url = Column(String(1024), nullable=True)
    size_bytes = Column(Integer, nullable=True, default=0)
    description = Column(Text, nullable=True, default="")
    make_tags = Column(JSONList, nullable=True, default=list)
    system_tags = Column(JSONList, nullable=True, default=list)
    language = Column(String(8), nullable=True, default="es")
    is_available_local = Column(Boolean, nullable=False, default=False)
    local_path = Column(String(1024), nullable=True)
    last_indexed = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relacion inversa con SoftwareTool
    software_tools = relationship(
        "SoftwareTool",
        back_populates="resource",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "category": self.category,
            "source": self.source,
            "source_url": self.source_url,
            "size_bytes": self.size_bytes or 0,
            "description": self.description or "",
            "make_tags": self.make_tags or [],
            "system_tags": self.system_tags or [],
            "language": self.language or "es",
            "is_available_local": bool(self.is_available_local),
            "local_path": self.local_path,
            "last_indexed": self.last_indexed.isoformat() if self.last_indexed else None,
        }


# ---------------------------------------------------------------------------
# SoftwareTool - software profesional especifico
# ---------------------------------------------------------------------------

class SoftwareTool(Base):
    """Software profesional de diagnostico, programacion o tuning."""

    __tablename__ = "software_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False, index=True)
    version = Column(String(64), nullable=True)
    publisher = Column(String(128), nullable=True)
    supports_brands = Column(JSONList, nullable=True, default=list)
    supports_features = Column(JSONList, nullable=True, default=list)
    license_type = Column(String(64), nullable=True, default="commercial")
    requires_hardware = Column(String(128), nullable=True, default="")
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)

    resource = relationship("Resource", back_populates="software_tools")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "supports_brands": self.supports_brands or [],
            "supports_features": self.supports_features or [],
            "license_type": self.license_type,
            "requires_hardware": self.requires_hardware,
            "resource_id": self.resource_id,
        }


# ---------------------------------------------------------------------------
# VehicleProfile - perfil completo de un vehiculo
# ---------------------------------------------------------------------------

class VehicleProfile(Base):
    """Perfil tecnico completo de un vehiculo (ECU + tuning + DTCs comunes)."""

    __tablename__ = "vehicle_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    make = Column(String(64), nullable=False, index=True)
    model = Column(String(128), nullable=False, index=True)
    year_start = Column(Integer, nullable=True)
    year_end = Column(Integer, nullable=True)
    engine_code = Column(String(64), nullable=True)
    engine_displacement = Column(Float, nullable=True)
    fuel_type = Column(String(32), nullable=True)
    turbo = Column(Boolean, default=False)
    ecu_type = Column(String(128), nullable=True)
    ecu_manufacturer = Column(String(64), nullable=True)
    obd_protocol = Column(String(64), nullable=True)
    vin_pattern = Column(String(128), nullable=True)
    common_dtcs = Column(JSONList, nullable=True, default=list)
    known_issues = Column(Text, nullable=True, default="")
    tuning_notes = Column(Text, nullable=True, default="")
    tuning_stages_available = Column(JSONList, nullable=True, default=list)
    related_resources = Column(JSONList, nullable=True, default=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "make": self.make,
            "model": self.model,
            "year_start": self.year_start,
            "year_end": self.year_end,
            "engine_code": self.engine_code,
            "engine_displacement": self.engine_displacement,
            "fuel_type": self.fuel_type,
            "turbo": bool(self.turbo),
            "ecu_type": self.ecu_type,
            "ecu_manufacturer": self.ecu_manufacturer,
            "obd_protocol": self.obd_protocol,
            "vin_pattern": self.vin_pattern,
            "common_dtcs": self.common_dtcs or [],
            "known_issues": self.known_issues or "",
            "tuning_notes": self.tuning_notes or "",
            "tuning_stages_available": self.tuning_stages_available or [],
            "related_resources": self.related_resources or [],
        }


# ---------------------------------------------------------------------------
# DTCCatalog - catalogo unificado de DTCs
# ---------------------------------------------------------------------------

class DTCCatalog(Base):
    """Catalogo profesional de DTCs con soluciones verificadas."""

    __tablename__ = "dtc_catalog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(8), nullable=False, unique=True, index=True)
    type = Column(String(32), nullable=True)  # powertrain, chassis, body, network
    sae_standard = Column(Boolean, default=True)
    description_en = Column(Text, nullable=True, default="")
    description_es = Column(Text, nullable=True, default="")
    severity = Column(String(16), nullable=True, default="medium")
    common_symptoms = Column(JSONList, nullable=True, default=list)
    diagnosis_steps = Column(Text, nullable=True, default="")
    repair_procedure = Column(Text, nullable=True, default="")
    probable_causes = Column(JSONList, nullable=True, default=list)
    related_makes = Column(JSONList, nullable=True, default=list)
    cost_range_min_usd = Column(Float, nullable=True, default=0.0)
    cost_range_max_usd = Column(Float, nullable=True, default=0.0)
    time_hours = Column(Float, nullable=True, default=1.0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "type": self.type,
            "sae_standard": bool(self.sae_standard),
            "description_en": self.description_en or "",
            "description_es": self.description_es or "",
            "severity": self.severity,
            "common_symptoms": self.common_symptoms or [],
            "diagnosis_steps": self.diagnosis_steps or "",
            "repair_procedure": self.repair_procedure or "",
            "probable_causes": self.probable_causes or [],
            "related_makes": self.related_makes or [],
            "cost_range_min_usd": self.cost_range_min_usd or 0.0,
            "cost_range_max_usd": self.cost_range_max_usd or 0.0,
            "time_hours": self.time_hours or 1.0,
        }


# ---------------------------------------------------------------------------
# DiagramReference - referencia a un diagrama electrico/componente
# ---------------------------------------------------------------------------

class DiagramReference(Base):
    """Referencia a un diagrama (electrico, vacuum, componente)."""

    __tablename__ = "diagram_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    make = Column(String(64), nullable=True, index=True)
    model = Column(String(128), nullable=True)
    year_range = Column(String(32), nullable=True)
    system = Column(String(64), nullable=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "make": self.make,
            "model": self.model,
            "year_range": self.year_range,
            "system": self.system,
            "resource_id": self.resource_id,
        }


# ---------------------------------------------------------------------------
# RepairProcedure - procedimiento de reparacion paso a paso
# ---------------------------------------------------------------------------

class RepairProcedure(Base):
    """Procedimiento de reparacion estructurado."""

    __tablename__ = "repair_procedures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    system = Column(String(64), nullable=True, index=True)
    difficulty = Column(String(16), nullable=True, default="medium")
    time_hours = Column(Float, nullable=True, default=1.0)
    tools_required = Column(JSONList, nullable=True, default=list)
    parts_required = Column(JSONList, nullable=True, default=list)
    steps = Column(JSONList, nullable=True, default=list)
    warnings = Column(JSONList, nullable=True, default=list)
    related_dtcs = Column(JSONList, nullable=True, default=list)
    applicable_vehicles = Column(JSONList, nullable=True, default=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "system": self.system,
            "difficulty": self.difficulty,
            "time_hours": self.time_hours or 1.0,
            "tools_required": self.tools_required or [],
            "parts_required": self.parts_required or [],
            "steps": self.steps or [],
            "warnings": self.warnings or [],
            "related_dtcs": self.related_dtcs or [],
            "applicable_vehicles": self.applicable_vehicles or [],
        }
