"""
SOLER OBD2 AI Scanner - SQLAlchemy ORM Models
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all models."""
    pass


def _uuid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Vehicle Profile
# ---------------------------------------------------------------------------

class VehicleProfile(Base):
    __tablename__ = "vehicle_profiles"

    id = Column(String(32), primary_key=True, default=_uuid)
    vin = Column(String(17), unique=True, nullable=True, index=True)
    make = Column(String(64), nullable=True)
    model = Column(String(64), nullable=True)
    year = Column(Integer, nullable=True)
    engine = Column(String(128), nullable=True)
    fuel_type = Column(String(32), nullable=True)
    protocol = Column(String(32), nullable=True)
    ecu_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # relationships
    scans = relationship("ScanRecord", back_populates="vehicle", lazy="selectin")

    def __repr__(self) -> str:
        return f"<VehicleProfile {self.year} {self.make} {self.model} VIN={self.vin}>"


# ---------------------------------------------------------------------------
# Scan Record (top-level session)
# ---------------------------------------------------------------------------

class ScanRecord(Base):
    __tablename__ = "scan_records"

    id = Column(String(32), primary_key=True, default=_uuid)
    vehicle_id = Column(
        String(32), ForeignKey("vehicle_profiles.id"), nullable=True, index=True
    )
    health_score = Column(Integer, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # relationships
    vehicle = relationship("VehicleProfile", back_populates="scans", lazy="selectin")
    sensor_readings = relationship(
        "SensorReading", back_populates="scan", lazy="selectin",
        cascade="all, delete-orphan",
    )
    dtc_records = relationship(
        "DTCRecord", back_populates="scan", lazy="selectin",
        cascade="all, delete-orphan",
    )
    diagnosis = relationship(
        "DiagnosisRecord", back_populates="scan", uselist=False, lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ScanRecord {self.id[:8]} at {self.created_at}>"


# ---------------------------------------------------------------------------
# Sensor Reading
# ---------------------------------------------------------------------------

class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_sensor_scan_pid", "scan_id", "pid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(
        String(32), ForeignKey("scan_records.id"), nullable=False, index=True
    )
    pid = Column(String(16), nullable=False)
    name = Column(String(64), nullable=False)
    value = Column(Float, nullable=True)
    value_text = Column(String(256), nullable=True)
    unit = Column(String(16), default="")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    scan = relationship("ScanRecord", back_populates="sensor_readings")

    def __repr__(self) -> str:
        return f"<SensorReading {self.pid}={self.value}{self.unit}>"


# ---------------------------------------------------------------------------
# Diagnostic Trouble Code
# ---------------------------------------------------------------------------

class DTCRecord(Base):
    __tablename__ = "dtc_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(
        String(32), ForeignKey("scan_records.id"), nullable=False, index=True
    )
    code = Column(String(8), nullable=False, index=True)
    description = Column(Text, default="")
    severity = Column(String(16), default="medium")
    system = Column(String(64), default="")
    possible_causes = Column(JSON, default=list)
    is_pending = Column(Boolean, default=False)
    freeze_frame = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    scan = relationship("ScanRecord", back_populates="dtc_records")

    def __repr__(self) -> str:
        return f"<DTCRecord {self.code} severity={self.severity}>"


# ---------------------------------------------------------------------------
# Tuning Map
# ---------------------------------------------------------------------------

class TuningMap(Base):
    __tablename__ = "tuning_maps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(
        String(32), ForeignKey("vehicle_profiles.id"), nullable=True, index=True
    )
    profile = Column(String(16), nullable=False)  # eco|stage1|sport|stage2
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    map_data = Column(JSON, nullable=False)  # full map payload
    estimated_hp_gain = Column(Float, nullable=True)
    estimated_torque_gain = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<TuningMap {self.profile} for vehicle={self.vehicle_id}>"


# ---------------------------------------------------------------------------
# Diagnosis Record (AI-generated)
# ---------------------------------------------------------------------------

class DiagnosisRecord(Base):
    __tablename__ = "diagnosis_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(
        String(32), ForeignKey("scan_records.id"), nullable=False, unique=True
    )
    summary = Column(Text, default="")
    analysis = Column(JSON, default=list)  # list of DiagnosisItem dicts
    ai_model = Column(String(64), default="")
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    scan = relationship("ScanRecord", back_populates="diagnosis")

    def __repr__(self) -> str:
        return f"<DiagnosisRecord scan={self.scan_id[:8]}>"
