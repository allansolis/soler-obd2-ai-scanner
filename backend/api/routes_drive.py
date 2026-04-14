"""
FastAPI routes for the Google Drive integration.

Expose:
    POST   /api/drive/auth               -> kickoff OAuth2 flow
    GET    /api/drive/status             -> connection + index stats
    POST   /api/drive/index              -> start full reindex (background)
    POST   /api/drive/index/incremental  -> incremental update
    GET    /api/drive/search             -> search the index
    GET    /api/drive/files/{id}/content -> download a file
    GET    /api/drive/folders            -> folder tree
    WS     /api/drive/ws/progress        -> indexing progress stream
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response

from backend.integrations.drive_indexer import DriveIndexer
from backend.integrations.drive_models import IndexProgress
from backend.integrations.google_drive import (
    DriveAuthError,
    DriveIntegrationError,
    DriveNotAuthenticatedError,
    GoogleDriveKnowledgeBase,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drive", tags=["drive"])


# ---------------------------------------------------------------------------
# Singletons (simple in-process state — good enough for the single-user app)
# ---------------------------------------------------------------------------

_drive: GoogleDriveKnowledgeBase | None = None
_indexer: DriveIndexer | None = None
_progress_queue: "asyncio.Queue[IndexProgress]" = asyncio.Queue(maxsize=100)


def get_drive() -> GoogleDriveKnowledgeBase:
    global _drive
    if _drive is None:
        _drive = GoogleDriveKnowledgeBase()
    return _drive


def get_indexer() -> DriveIndexer:
    global _indexer
    if _indexer is None:
        _indexer = DriveIndexer(get_drive())
    return _indexer


async def _progress_callback(progress: IndexProgress) -> None:
    """Funcion usada como callback en el indexer -> feed del WS."""
    try:
        # Drop oldest if full so we never block the indexer.
        if _progress_queue.full():
            try:
                _progress_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        _progress_queue.put_nowait(progress)
    except Exception:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/auth")
async def authenticate_drive() -> dict[str, Any]:
    """Inicia el flujo OAuth2 para conectar Google Drive."""
    drive = get_drive()
    try:
        await drive.authenticate_async()
        return {
            "status": "authenticated",
            "message": "Google Drive conectado correctamente.",
        }
    except DriveAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DriveIntegrationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error en auth")
        raise HTTPException(status_code=500, detail=f"Error inesperado: {exc}")


@router.post("/logout")
async def logout_drive() -> dict[str, Any]:
    """Borra el token local y cierra la sesion."""
    drive = get_drive()
    try:
        if drive.token_path.exists():
            drive.token_path.unlink()
        drive.service = None
        drive._credentials = None
        return {"status": "logged_out"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Status / stats
# ---------------------------------------------------------------------------

@router.get("/status")
async def drive_status() -> dict[str, Any]:
    """Estado de conexion y estadisticas del indice."""
    drive = get_drive()
    indexer = get_indexer()

    stats = drive.get_index_stats()
    return {
        "connected": drive.is_authenticated(),
        "token_exists": drive.token_path.exists(),
        "credentials_configured": drive.credentials_path.exists(),
        "indexing": indexer.is_running,
        "stats": {
            **stats.to_dict(),
            "total_size_human": stats.total_size_human,
        },
    }


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

@router.post("/index")
async def start_indexing(
    background: BackgroundTasks,
    extract_text: bool = Query(True, description="Extraer texto de PDFs/Docs"),
    max_files: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    """Inicia la indexacion completa en background."""
    drive = get_drive()
    indexer = get_indexer()

    if not drive.is_authenticated():
        raise HTTPException(
            status_code=401,
            detail="Google Drive no esta autenticado. Llama a /api/drive/auth primero.",
        )
    if indexer.is_running:
        raise HTTPException(status_code=409, detail="Ya hay una indexacion en curso.")

    async def _run():
        try:
            await indexer.run_initial_index(
                callback=_progress_callback,
                extract_text=extract_text,
                max_files=max_files,
            )
        except Exception as exc:
            logger.exception("Fallo la indexacion: %s", exc)

    background.add_task(_run)
    return {"status": "started", "message": "Indexacion en curso."}


@router.post("/index/incremental")
async def incremental_update(background: BackgroundTasks) -> dict[str, Any]:
    """Actualiza solo archivos modificados desde la ultima indexacion."""
    drive = get_drive()
    indexer = get_indexer()
    if not drive.is_authenticated():
        raise HTTPException(status_code=401, detail="No autenticado.")
    if indexer.is_running:
        raise HTTPException(status_code=409, detail="Indexacion en curso.")

    async def _run():
        try:
            await indexer.run_incremental_update(callback=_progress_callback)
        except Exception as exc:
            logger.exception("Fallo la actualizacion incremental: %s", exc)

    background.add_task(_run)
    return {"status": "started"}


@router.post("/index/cancel")
async def cancel_indexing() -> dict[str, Any]:
    """Cancela la indexacion en curso."""
    get_indexer().cancel()
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_drive(
    q: str = Query(..., min_length=1, description="Texto de busqueda"),
    type: str | None = Query(None, description="Extension o mime parcial"),
    make: str | None = Query(None, description="Marca del vehiculo"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Busca en el indice SQLite local del Drive."""
    drive = get_drive()
    try:
        results = await drive.search(q, file_type=type, make=make, max_results=limit)
    except Exception as exc:
        logger.exception("Error buscando")
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "query": q,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# File access
# ---------------------------------------------------------------------------

@router.get("/files/{file_id}/content")
async def get_file_content(file_id: str):
    """Descarga un archivo especifico del Drive."""
    drive = get_drive()
    try:
        data = await drive.get_file_content(file_id)
    except DriveNotAuthenticatedError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=data, media_type="application/octet-stream")


@router.get("/files/{file_id}/preview")
async def get_file_preview(file_id: str) -> dict[str, Any]:
    """Devuelve el preview de texto guardado en el indice."""
    import sqlite3

    drive = get_drive()
    with sqlite3.connect(drive.index_db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT file_id, name, mime_type, path, preview_text, category "
            "FROM drive_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Archivo no indexado.")
    return dict(row)


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

@router.get("/folders")
async def list_folders() -> dict[str, Any]:
    """Lista la estructura de carpetas del Drive."""
    drive = get_drive()
    try:
        return await drive.get_folder_structure()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# WebSocket — indexing progress
# ---------------------------------------------------------------------------

@router.websocket("/ws/progress")
async def index_progress_ws(websocket: WebSocket) -> None:
    """Stream de progreso de indexacion."""
    await websocket.accept()
    try:
        while True:
            try:
                progress = await asyncio.wait_for(_progress_queue.get(), timeout=30)
                await websocket.send_json(progress.to_dict())
            except asyncio.TimeoutError:
                await websocket.send_json({"phase": "idle"})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover
        logger.warning("WS progress error: %s", exc)
        try:
            await websocket.close()
        except Exception:
            pass
