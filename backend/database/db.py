"""
SOLER OBD2 AI Scanner - Async Database Setup (SQLite via aiosqlite)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.database.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_url() -> str:
    """Build the async SQLite URL from settings."""
    return f"sqlite+aiosqlite:///{settings.database.sqlite_path}"


async def init_db() -> None:
    """Create the async engine, session factory, and all tables."""
    global _engine, _session_factory

    db_path = Path(settings.database.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = _build_url()
    logger.info("Initializing database: %s", url)

    _engine = create_async_engine(
        url,
        echo=settings.database.echo_sql,
        pool_pre_ping=True,
        # SQLite doesn't benefit from pool size, but keep defaults reasonable
        connect_args={"check_same_thread": False},
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created successfully.")


async def close_db() -> None:
    """Dispose of the engine and release connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed.")
        _engine = None
        _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the current engine, raising if not initialized."""
    if _engine is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() first."
        )
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session."""
    if _session_factory is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() first."
        )
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
