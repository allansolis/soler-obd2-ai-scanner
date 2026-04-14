"""
SOLER OBD2 AI Scanner - API Package

FastAPI application with REST and WebSocket endpoints for real-time
OBD-II diagnostics, AI analysis, and tuning.
"""

from backend.api.server import app, create_app

__all__ = ["app", "create_app"]
