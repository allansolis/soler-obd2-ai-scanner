"""
scaner_soler/config.py — Configuración centralizada del sistema Scaner Soler Pro.

Todos los valores son configurables mediante variables de entorno.
Los defaults mantienen el comportamiento existente del sistema.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Backend FastAPI ────────────────────────────────────────────────────────────
# Ruta al backend FastAPI — configurable via variable de entorno
BACKEND_DIR = Path(
    os.environ.get(
        "SOLER_BACKEND_DIR",
        str(Path.home() / "AppData" / "Local" / "Temp" / "soler-obd2-ai-scanner")
    )
)

BACKEND_URL = os.environ.get("SOLER_BACKEND_URL", "http://localhost:8000")

# Puerto del backend
BACKEND_PORT = int(os.environ.get("SOLER_BACKEND_PORT", "8000"))

# ── Conexión OBD-II ───────────────────────────────────────────────────────────
# Puerto serial OBD por defecto
DEFAULT_SERIAL_PORT = os.environ.get("SOLER_OBD_PORT", "COM3")
DEFAULT_BAUD_RATE = int(os.environ.get("SOLER_BAUD_RATE", "38400"))
