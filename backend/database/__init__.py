"""
SOLER OBD2 AI Scanner - Database Package

Async SQLite persistence via SQLAlchemy 2.0 + aiosqlite.
"""

from backend.database.db import init_db, close_db, get_session, get_engine
from backend.database.models import (
    Base,
    VehicleProfile,
    ScanRecord,
    SensorReading,
    DTCRecord,
    TuningMap,
    DiagnosisRecord,
)

__all__ = [
    "init_db",
    "close_db",
    "get_session",
    "get_engine",
    "Base",
    "VehicleProfile",
    "ScanRecord",
    "SensorReading",
    "DTCRecord",
    "TuningMap",
    "DiagnosisRecord",
]
