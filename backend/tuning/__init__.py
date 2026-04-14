"""
SOLER OBD2 AI Scanner - ECU Tuning / Mapping Module
====================================================
Provides ECU map generation, tuning profiles, safety verification,
performance simulation, and map export capabilities.
"""

from __future__ import annotations

from backend.tuning.map_generator import ECUMapGenerator, ECUMapSet
from backend.tuning.profiles import TuningProfile, ProfileLibrary, ProfileName
from backend.tuning.safety import SafetyVerifier, SafetyReport
from backend.tuning.simulator import PerformanceSimulator, SimulationResult
from backend.tuning.exporter import MapExporter, ExportFormat

__all__ = [
    "ECUMapGenerator",
    "ECUMapSet",
    "TuningProfile",
    "ProfileLibrary",
    "ProfileName",
    "SafetyVerifier",
    "SafetyReport",
    "PerformanceSimulator",
    "SimulationResult",
    "MapExporter",
    "ExportFormat",
]
