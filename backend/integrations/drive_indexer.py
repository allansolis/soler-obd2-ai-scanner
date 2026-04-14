"""
Drive Indexer — extraccion de texto y clasificacion en background.

Se complementa con ``GoogleDriveKnowledgeBase``:
    * ``run_initial_index``  -> primera pasada completa.
    * ``run_incremental_update`` -> cambios desde ultima sincronizacion.
    * ``extract_text_from_file`` -> texto segun tipo (PDF, DOCX, TXT).
    * ``classify_with_ai``  -> refinamiento de categoria usando el texto.
"""

from __future__ import annotations

import asyncio
import io
import logging
import sqlite3
from datetime import datetime
from typing import Any, Awaitable, Callable

from backend.integrations.drive_models import (
    FileCategory,
    IndexProgress,
    IndexStats,
)
from backend.integrations.google_drive import (
    GoogleDriveKnowledgeBase,
    _fts_sanitize,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[IndexProgress], Awaitable[None] | None]


class DriveIndexer:
    """
    Indexador que corre en background y mantiene el indice actualizado.

    Extrae texto de PDFs, clasifica archivos, genera metadata.
    """

    # Limite de bytes que bajamos para extraer texto (evita PDFs gigantes).
    MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
    PREVIEW_CHARS = 500

    def __init__(self, drive: GoogleDriveKnowledgeBase):
        self.drive = drive
        self._running = False
        self._cancel = asyncio.Event()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        self._cancel.set()

    async def run_initial_index(
        self,
        callback: ProgressCallback | None = None,
        extract_text: bool = True,
        max_files: int | None = None,
    ) -> IndexStats:
        """Primera indexacion completa del Drive (puede tomar horas)."""
        if self._running:
            raise RuntimeError("El indexador ya esta corriendo.")
        self._running = True
        self._cancel.clear()
        try:
            stats = await self.drive.index_drive(callback=callback, max_files=max_files)
            if extract_text:
                await self._extract_texts_for_top_files(callback=callback)
            return stats
        finally:
            self._running = False

    async def run_incremental_update(
        self, callback: ProgressCallback | None = None
    ) -> int:
        """
        Actualiza solo archivos modificados desde ultima sincronizacion.

        Returns:
            Numero de archivos actualizados.
        """
        if not self.drive.is_authenticated():
            raise RuntimeError("Drive no esta autenticado.")

        last = self.drive._get_meta("last_indexed_at")
        q = "trashed = false"
        if last:
            q += f" and modifiedTime > '{last}'"

        updated = 0
        page_token: str | None = None
        while True:
            if self._cancel.is_set():
                break
            await self.drive._rate_limiter.acquire()
            resp = await asyncio.to_thread(
                lambda: self.drive.service.files()
                .list(
                    q=q,
                    pageSize=500,
                    pageToken=page_token,
                    fields=(
                        "nextPageToken, files(id, name, mimeType, size, "
                        "createdTime, modifiedTime, parents, webViewLink)"
                    ),
                )
                .execute()
            )
            for item in resp.get("files", []):
                try:
                    df = await self.drive._process_file_entry(item)
                    self.drive._upsert_file(df)
                    updated += 1
                except Exception as exc:
                    logger.warning("Update fallo para %s: %s", item.get("name"), exc)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        self.drive._set_meta("last_indexed_at", datetime.utcnow().isoformat())
        logger.info("Incremental update: %d archivos", updated)
        return updated

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    async def extract_text_from_file(
        self, file_id: str, mime_type: str
    ) -> str:
        """Extrae texto segun tipo: PDF, DOCX, TXT, Google Docs."""
        try:
            if mime_type == "application/pdf":
                return await self.drive.extract_text_from_pdf(file_id)

            if mime_type == "application/vnd.google-apps.document":
                # Export to plain text
                await self.drive._rate_limiter.acquire()
                data = await asyncio.to_thread(
                    lambda: self.drive.service.files()
                    .export(fileId=file_id, mimeType="text/plain")
                    .execute()
                )
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)

            if mime_type == "text/plain" or mime_type == "text/csv":
                data = await self.drive.get_file_content(file_id)
                return data.decode("utf-8", errors="ignore")

            if mime_type == (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ):
                try:
                    import docx  # python-docx
                except ImportError:
                    logger.debug("python-docx no instalado, se salta DOCX")
                    return ""
                data = await self.drive.get_file_content(file_id)
                doc = docx.Document(io.BytesIO(data))
                return "\n".join(p.text for p in doc.paragraphs)

            if mime_type == "application/vnd.google-apps.spreadsheet":
                await self.drive._rate_limiter.acquire()
                data = await asyncio.to_thread(
                    lambda: self.drive.service.files()
                    .export(fileId=file_id, mimeType="text/csv")
                    .execute()
                )
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)

        except Exception as exc:
            logger.warning("No se pudo extraer texto de %s: %s", file_id, exc)

        return ""

    async def classify_with_ai(
        self, file_info: dict[str, Any], preview_text: str
    ) -> FileCategory:
        """
        Usa reglas + keywords para clasificar el contenido.

        Si se desea integrar un LLM mas adelante, este es el punto de extension.
        """
        # Primero reglas baratas
        rules = self.drive.categorize_file(file_info)
        if rules != FileCategory.MISCELLANEOUS:
            return rules

        if not preview_text:
            return rules

        text = preview_text.lower()
        if any(k in text for k in ("wiring diagram", "diagrama electrico")):
            return FileCategory.WIRING_DIAGRAM
        if any(k in text for k in ("dtc", "fault code", "trouble code", "p0", "p1")):
            return FileCategory.DTC_DATABASE
        if any(k in text for k in ("pinout", "pin assignment", "pin-out")):
            return FileCategory.ECU_PINOUT
        if any(k in text for k in ("tuning", "remap", "chiptuning", "stage 1")):
            return FileCategory.TUNING_MAP
        if any(k in text for k in ("workshop", "repair manual", "service manual")):
            return FileCategory.WORKSHOP_MANUAL

        return rules

    # ------------------------------------------------------------------
    # Internal: extract preview text for top automotive files
    # ------------------------------------------------------------------

    async def _extract_texts_for_top_files(
        self,
        callback: ProgressCallback | None = None,
        top_n: int = 500,
    ) -> None:
        """Baja los N archivos mas automotrices y extrae previews."""
        with sqlite3.connect(self.drive.index_db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT file_id, name, mime_type, size, path
                FROM drive_files
                WHERE automotive_score >= 0.3
                  AND size > 0 AND size <= ?
                  AND mime_type IN (
                    'application/pdf',
                    'text/plain',
                    'application/vnd.google-apps.document',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                  )
                  AND (preview_text IS NULL OR preview_text = '')
                ORDER BY automotive_score DESC
                LIMIT ?
                """,
                (self.MAX_DOWNLOAD_BYTES, top_n),
            ).fetchall()

        total = len(rows)
        for idx, row in enumerate(rows, 1):
            if self._cancel.is_set():
                break
            try:
                text = await self.extract_text_from_file(
                    row["file_id"], row["mime_type"]
                )
                preview = (text or "")[: self.PREVIEW_CHARS]
                # Refine category with text
                new_cat = await self.classify_with_ai(
                    {"id": row["file_id"], "name": row["name"], "mimeType": row["mime_type"]},
                    preview,
                )
                self._update_preview(row["file_id"], preview, text, new_cat.value)
            except Exception as exc:
                logger.debug("Preview fallo para %s: %s", row["name"], exc)

            if callback and idx % 10 == 0:
                progress = IndexProgress(
                    files_indexed=idx,
                    total_estimated=total,
                    current_file=row["name"],
                    current_path=row["path"],
                    percent=(idx / total * 100.0) if total else 100.0,
                    phase="extracting",
                )
                result = callback(progress)
                if asyncio.iscoroutine(result):
                    await result

    def _update_preview(
        self, file_id: str, preview: str, full_text: str, category: str
    ) -> None:
        with sqlite3.connect(self.drive.index_db_path) as conn:
            conn.execute(
                """
                UPDATE drive_files
                SET preview_text = ?, category = ?
                WHERE file_id = ?
                """,
                (preview, category, file_id),
            )
            conn.execute(
                "UPDATE drive_files_fts SET preview_text = ?, extracted_text = ? "
                "WHERE file_id = ?",
                (preview, full_text[:20000] if full_text else "", file_id),
            )
            conn.commit()
