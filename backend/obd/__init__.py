"""
SOLER OBD2 AI Scanner - OBD-II Package

Provides connection management, real-time sensor streaming, and DTC diagnostics
for ELM327-compatible OBD-II adapters over USB, Bluetooth, and WiFi.
"""

from backend.obd.connection import OBDConnectionManager
from backend.obd.sensors import SensorReader, SensorReading
from backend.obd.dtc import DTCReader, DTCRecord

__all__ = [
    "OBDConnectionManager",
    "SensorReader",
    "SensorReading",
    "DTCReader",
    "DTCRecord",
]
