"""
SOLER OBD2 AI Scanner - Backend Configuration
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_DIR = DATA_DIR / "db"

# ---------------------------------------------------------------------------
# OBD-II Connection
# ---------------------------------------------------------------------------

@dataclass
class OBDConnectionConfig:
    """ELM327 / OBD-II adapter connection settings."""

    port: Optional[str] = None  # None = auto-detect
    baudrate: int = 38400
    protocol: str = "auto"  # auto | SAE_J1850_PWM | SAE_J1850_VPW | ISO_9141_2 | ...
    timeout: float = 5.0  # seconds per command
    reconnect_delay: float = 2.0  # seconds between reconnect attempts
    max_reconnect_attempts: int = 5
    fast_mode: bool = True  # skip response validation for speed
    check_voltage: bool = True


# ---------------------------------------------------------------------------
# Sampling / Streaming
# ---------------------------------------------------------------------------

@dataclass
class SamplingConfig:
    """Sensor polling rates (Hz)."""

    critical_hz: float = 10.0  # RPM, speed, throttle
    secondary_hz: float = 2.0  # coolant temp, IAT, fuel level
    dtc_poll_interval: float = 30.0  # seconds between DTC scans
    freeze_frame_on_dtc: bool = True  # auto-read freeze frame when DTC found


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@dataclass
class DatabaseConfig:
    """SQLite / async database paths."""

    sqlite_path: str = str(DB_DIR / "soler_obd.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    echo_sql: bool = False


# ---------------------------------------------------------------------------
# AI Agent
# ---------------------------------------------------------------------------

@dataclass
class AIAgentConfig:
    """Anthropic Claude integration settings."""

    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.3
    system_prompt_path: str = str(BASE_DIR / "ai_agent" / "system_prompt.txt")
    language: str = "es"  # default response language


# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------

@dataclass
class APIConfig:
    """FastAPI / Uvicorn settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = os.getenv("ENV", "development") == "development"
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    ws_heartbeat: float = 15.0  # WebSocket keepalive (seconds)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    obd: OBDConnectionConfig = field(default_factory=OBDConnectionConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ai: AIAgentConfig = field(default_factory=AIAgentConfig)
    api: APIConfig = field(default_factory=APIConfig)


settings = Settings()
