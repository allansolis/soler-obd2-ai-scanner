"""
SOLER OBD2 AI Scanner - Entry Point

Run with:
    python -m backend.main
    # or
    uvicorn backend.api.server:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import sys
import uvicorn

from backend.config import settings


def main() -> None:
    """Launch the Uvicorn server with settings from config."""
    uvicorn.run(
        "backend.api.server:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        log_level="info",
        ws_ping_interval=settings.api.ws_heartbeat,
        ws_ping_timeout=settings.api.ws_heartbeat * 2,
    )


if __name__ == "__main__":
    main()
