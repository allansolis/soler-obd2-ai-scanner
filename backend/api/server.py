"""
SOLER OBD2 AI Scanner - Main FastAPI Application
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router as api_router, set_emulator
from backend.api.routes_ai import router as ai_router
from backend.api.routes_drive import router as drive_router
from backend.api.routes_hub import router as hub_router
from backend.api.routes_expert import router as expert_router
from backend.api.routes_launcher import router as launcher_router
from backend.config import settings, PROJECT_DIR
from backend.database.db import init_db, close_db
from backend.emulator.elm327_sim import ELM327Emulator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: DB init, emulator, shutdown."""
    # ---- Startup ----
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    logger.info("SOLER OBD2 AI Scanner starting up...")

    # Initialize database
    await init_db()
    logger.info("Database initialized.")

    # Create emulator instance and inject into routes
    emulator = ELM327Emulator()
    set_emulator(emulator)
    logger.info("ELM327 emulator ready.")

    yield

    # ---- Shutdown ----
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database closed. Goodbye.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    app = FastAPI(
        title="SOLER OBD2 AI Scanner",
        description=(
            "Real-time OBD-II diagnostics, AI-powered analysis, "
            "and performance tuning API."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -- CORS --
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- API key middleware (only enforces if API_KEY env is set, on /api/launcher) --
    API_KEY = os.getenv("API_KEY", "")

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        if API_KEY and request.url.path.startswith("/api/launcher"):
            key = request.headers.get("X-API-Key")
            if key != API_KEY:
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
        return await call_next(request)

    # -- Health endpoint --
    @app.get("/health")
    async def health() -> dict:
        status: dict = {"status": "ok", "services": {}}
        try:
            db_path = PROJECT_DIR / "data" / "knowledge_hub.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
            status["services"]["knowledge_hub"] = "ok"
        except Exception as e:  # noqa: BLE001
            status["services"]["knowledge_hub"] = f"error: {e}"
            status["status"] = "degraded"
        return status

    # -- API routes --
    app.include_router(api_router)
    app.include_router(ai_router)
    app.include_router(drive_router)
    app.include_router(hub_router)
    app.include_router(expert_router)
    app.include_router(launcher_router)

    # -- Global exception handler --
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )

    # -- Static files (frontend build) --
    frontend_dist = PROJECT_DIR / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        logger.info("Serving frontend from %s", frontend_dist)
    else:
        @app.get("/")
        async def root() -> dict:
            return {
                "app": "SOLER OBD2 AI Scanner",
                "version": "1.0.0",
                "docs": "/docs",
                "status": "API running — frontend not built yet",
            }

    return app


# Module-level app instance for uvicorn
app = create_app()
