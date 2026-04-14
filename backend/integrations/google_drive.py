"""
Google Drive Knowledge Base.

Integra el Drive de 2TB del usuario como base de conocimiento del
AI Copilot de SOLER. Usa OAuth2 para autenticarse, mantiene un indice
SQLite local con metadata y texto extraido, y expone un API asincrono
para busqueda, descarga y sincronizacion.

Notas de diseño:
    * Las llamadas HTTP a la API de Google son sincronas (googleapiclient).
      Envolvemos cada llamada critica con ``asyncio.to_thread`` para no
      bloquear el event-loop de FastAPI.
    * Se aplica rate-limiting simple (token bucket) para respetar la
      cuota de Google Drive (1000 queries / 100s / user).
    * El indice vive en ``data/google_drive_index.db`` y se crea on-demand.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import sqlite3
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from backend.integrations.drive_models import (
    DriveFile,
    FileCategory,
    IndexProgress,
    IndexStats,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional imports — the module has to import even if google libs are missing
# (so the rest of the backend keeps working). We raise a clear error only when
# the user actually tries to use the Drive features.
# ---------------------------------------------------------------------------

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload

    GOOGLE_LIBS_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    GOOGLE_LIBS_AVAILABLE = False
    Request = Credentials = InstalledAppFlow = build = None  # type: ignore
    HttpError = Exception  # type: ignore
    MediaIoBaseDownload = None  # type: ignore


class DriveIntegrationError(RuntimeError):
    """Error generico de la integracion con Drive."""


class DriveAuthError(DriveIntegrationError):
    """Problema de autenticacion / credenciales."""


class DriveNotAuthenticatedError(DriveIntegrationError):
    """Se intento usar el servicio antes de autenticar."""


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """
    Token bucket muy simple.

    Google Drive tiene una cuota de ~1000 peticiones / 100s por usuario.
    Usamos 8 req/s de forma conservadora. Es thread-safe via asyncio.Lock.
    """

    def __init__(self, rate_per_second: float = 8.0, burst: int = 16):
        self.rate = rate_per_second
        self.capacity = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class GoogleDriveKnowledgeBase:
    """
    Google Drive como base de datos del agente AI.

    Usa OAuth2 para conectarse a la cuenta del usuario.
    Indexa todos los archivos automotrices y los hace consultables
    por el AI Copilot y el sistema de diagnostico.
    """

    SCOPES = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]

    # Tipos de archivo que nos interesan
    AUTOMOTIVE_MIME_TYPES = [
        "application/pdf",
        "application/zip",
        "application/x-rar-compressed",
        "application/x-rar",
        "application/x-7z-compressed",
        "application/vnd.google-apps.folder",
        "text/plain",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.google-apps.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.spreadsheet",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "video/mp4",
        "video/x-msvideo",
        "video/quicktime",
    ]

    # Keywords para identificar contenido automotriz
    AUTOMOTIVE_KEYWORDS = [
        "obd", "obd2", "dtc", "ecu", "tcu", "tuning", "mapa", "mapas",
        "bosch", "delphi", "siemens", "denso", "continental", "magneti",
        "winols", "ecm titanium", "damos", "a2l", "kess", "kessv2", "ktag",
        "mpps", "galletto", "byteshooter", "swiftec",
        "edc", "med", "mev", "simos", "me7", "me9", "me17", "edc15", "edc16", "edc17",
        "motor", "diesel", "gasolina", "tdi", "crdi", "dci", "hdi",
        "diagrama", "wiring", "pinout", "esquematico", "schematic",
        "torque", "nm", "cv", "hp", "caballos",
        "mercedes", "bmw", "toyota", "nissan", "mazda", "honda", "audi",
        "ford", "vw", "volkswagen", "chevrolet", "hyundai", "kia", "seat",
        "skoda", "peugeot", "citroen", "renault", "fiat", "opel", "volvo",
        "manual", "taller", "workshop", "repair", "service",
        "scanner", "diagnostico", "diagnosis", "airbag", "abs", "esp",
        "transmission", "cambio", "caja", "automatica", "dsg", "cvt",
        "inmovilizador", "immobilizer", "key", "llave",
        "inyector", "injector", "turbo", "egr", "dpf", "fap", "adblue",
    ]

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        index_db_path: Path | None = None,
    ):
        self.credentials_path = Path(credentials_path or "config/google_credentials.json")
        self.token_path = Path(token_path or "config/google_token.json")
        self.index_db_path = Path(index_db_path or "data/google_drive_index.db")
        self.service: Any = None
        self._credentials: Any = None
        self._rate_limiter = _RateLimiter(rate_per_second=8.0, burst=16)
        self._indexing_lock = asyncio.Lock()
        self._path_cache: dict[str, str] = {}
        self._ensure_dirs()
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_libs(self) -> None:
        if not GOOGLE_LIBS_AVAILABLE:
            raise DriveIntegrationError(
                "Las librerias de Google no estan instaladas. Ejecuta: "
                "pip install google-auth google-auth-oauthlib "
                "google-auth-httplib2 google-api-python-client"
            )

    def _require_service(self) -> None:
        if self.service is None:
            raise DriveNotAuthenticatedError(
                "Google Drive no esta autenticado. Llama a authenticate() primero."
            )

    def _ensure_dirs(self) -> None:
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        """Crea el esquema SQLite si no existe."""
        with sqlite3.connect(self.index_db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS drive_files (
                    file_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mime_type TEXT,
                    size INTEGER DEFAULT 0,
                    created_time TEXT,
                    modified_time TEXT,
                    parents TEXT,
                    path TEXT,
                    extracted_text TEXT,
                    preview_text TEXT,
                    category TEXT,
                    tags TEXT,
                    vehicle_tags TEXT,
                    automotive_score REAL DEFAULT 0,
                    last_indexed TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_drive_files_name ON drive_files(name);
                CREATE INDEX IF NOT EXISTS idx_drive_files_category ON drive_files(category);
                CREATE INDEX IF NOT EXISTS idx_drive_files_mime ON drive_files(mime_type);
                CREATE INDEX IF NOT EXISTS idx_drive_files_score ON drive_files(automotive_score);

                CREATE VIRTUAL TABLE IF NOT EXISTS drive_files_fts USING fts5(
                    file_id UNINDEXED,
                    name,
                    path,
                    preview_text,
                    extracted_text,
                    tags,
                    vehicle_tags,
                    tokenize = 'unicode61 remove_diacritics 2'
                );

                CREATE TABLE IF NOT EXISTS drive_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            conn.commit()

    def _set_meta(self, key: str, value: str) -> None:
        with sqlite3.connect(self.index_db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO drive_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def _get_meta(self, key: str) -> str | None:
        with sqlite3.connect(self.index_db_path) as conn:
            row = conn.execute(
                "SELECT value FROM drive_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> bool:
        """
        Autentica con Google Drive via OAuth2.

        Primera vez: abre navegador para autorizar.
        Siguientes veces: usa token guardado.

        Returns:
            True si autenticacion exitosa.
        """
        self._require_libs()

        creds = None
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path), self.SCOPES
                )
            except Exception as exc:  # pragma: no cover - corrupt token
                logger.warning("Token corrupto, se regenerara: %s", exc)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    logger.warning("No se pudo refrescar token: %s", exc)
                    creds = None

            if not creds:
                if not self.credentials_path.exists():
                    raise DriveAuthError(
                        f"No existe el archivo de credenciales en "
                        f"{self.credentials_path}. Sigue la guia en "
                        f"backend/integrations/setup_guide.md para crearlo."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), self.SCOPES
                )
                creds = flow.run_local_server(port=8080, open_browser=True)

            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        self._credentials = creds
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
        logger.info("Google Drive autenticado correctamente.")
        return True

    def is_authenticated(self) -> bool:
        return self.service is not None

    async def authenticate_async(self) -> bool:
        """Version asincrona de authenticate() — no bloquea el event-loop."""
        return await asyncio.to_thread(self.authenticate)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_drive(
        self,
        callback: Callable[[IndexProgress], Awaitable[None] | None] | None = None,
        max_files: int | None = None,
    ) -> IndexStats:
        """
        Indexa todos los archivos automotrices del Drive.

        Args:
            callback: funcion que recibe ``IndexProgress`` (puede ser async).
            max_files: limite opcional para pruebas.
        """
        self._require_service()

        async with self._indexing_lock:
            start = time.monotonic()
            stats = IndexStats(indexed_at=datetime.utcnow())
            seen = 0
            page_token: str | None = None
            all_rows: list[dict[str, Any]] = []

            logger.info("Iniciando indexacion del Drive...")

            # Phase 1: list all files
            while True:
                await self._rate_limiter.acquire()
                try:
                    resp = await asyncio.to_thread(
                        self._list_files_page, page_token
                    )
                except HttpError as exc:
                    logger.error("Error listando archivos: %s", exc)
                    stats.errors += 1
                    break

                files = resp.get("files", [])
                all_rows.extend(files)
                seen += len(files)

                if callback:
                    progress = IndexProgress(
                        files_indexed=seen,
                        total_estimated=seen + (1000 if resp.get("nextPageToken") else 0),
                        phase="scanning",
                        elapsed_seconds=time.monotonic() - start,
                        current_file=files[-1]["name"] if files else "",
                    )
                    result = callback(progress)
                    if asyncio.iscoroutine(result):
                        await result

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
                if max_files and seen >= max_files:
                    break

            logger.info("Listados %d archivos. Procesando...", len(all_rows))

            # Phase 2: process and write to DB
            total = len(all_rows)
            for idx, item in enumerate(all_rows, 1):
                try:
                    drive_file = await self._process_file_entry(item)
                    self._upsert_file(drive_file)
                    self._update_stats(stats, drive_file, item)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Error procesando %s: %s", item.get("name"), exc)
                    stats.errors += 1

                if callback and (idx % 25 == 0 or idx == total):
                    elapsed = time.monotonic() - start
                    eta = None
                    if idx > 0:
                        rate = idx / elapsed if elapsed > 0 else 0
                        if rate > 0:
                            eta = (total - idx) / rate
                    progress = IndexProgress(
                        files_indexed=idx,
                        total_estimated=total,
                        current_file=item.get("name", ""),
                        current_path=self._path_cache.get(item.get("id", ""), ""),
                        percent=(idx / total * 100.0) if total else 100.0,
                        elapsed_seconds=elapsed,
                        eta_seconds=eta,
                        phase="indexing",
                    )
                    result = callback(progress)
                    if asyncio.iscoroutine(result):
                        await result

            self._set_meta("last_indexed_at", stats.indexed_at.isoformat())
            self._set_meta("last_stats", json.dumps(stats.to_dict()))

            if callback:
                final = IndexProgress(
                    files_indexed=total,
                    total_estimated=total,
                    percent=100.0,
                    elapsed_seconds=time.monotonic() - start,
                    phase="done",
                )
                result = callback(final)
                if asyncio.iscoroutine(result):
                    await result

            logger.info(
                "Indexacion completada: %d archivos, %d automotrices, %.2f MB",
                stats.total_files,
                stats.automotive_files,
                stats.total_size_bytes / (1024 * 1024),
            )
            return stats

    def _list_files_page(self, page_token: str | None) -> dict[str, Any]:
        """Llamada sincrona — se usa dentro de ``to_thread``."""
        return (
            self.service.files()
            .list(
                q="trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields=(
                    "nextPageToken, files(id, name, mimeType, size, "
                    "createdTime, modifiedTime, parents, webViewLink, "
                    "webContentLink)"
                ),
                supportsAllDrives=False,
            )
            .execute()
        )

    async def _process_file_entry(self, item: dict[str, Any]) -> DriveFile:
        """Convierte un dict de la API en un ``DriveFile`` con clasificacion."""
        file_id = item["id"]
        name = item.get("name", "")
        mime = item.get("mimeType", "")
        size = int(item.get("size") or 0)
        parents = item.get("parents", []) or []
        modified = item.get("modifiedTime")

        path = await self._resolve_path(file_id, name, parents)
        self._path_cache[file_id] = path

        category = self.categorize_file(item)
        vehicle_tags = self.extract_vehicle_tags(name)
        tags = self._extract_generic_tags(name)
        score = self._compute_automotive_score(name, mime, path)

        return DriveFile(
            file_id=file_id,
            name=name,
            mime_type=mime,
            size=size,
            path=path,
            category=category.value,
            tags=tags,
            vehicle_tags=vehicle_tags,
            preview_text="",
            automotive_score=score,
            last_indexed=datetime.utcnow(),
            download_url=item.get("webContentLink", "") or item.get("webViewLink", ""),
            modified_time=_parse_dt(modified),
            parents=parents,
        )

    async def _resolve_path(
        self, file_id: str, name: str, parents: list[str]
    ) -> str:
        """Resuelve el path completo (cache en memoria)."""
        if not parents:
            return name
        parent_id = parents[0]
        if parent_id in self._path_cache:
            return f"{self._path_cache[parent_id]}/{name}"

        segments: list[str] = [name]
        current = parent_id
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            if current in self._path_cache:
                segments.append(self._path_cache[current])
                break
            try:
                await self._rate_limiter.acquire()
                meta = await asyncio.to_thread(
                    lambda: self.service.files()
                    .get(fileId=current, fields="id, name, parents")
                    .execute()
                )
            except HttpError:
                break
            segments.append(meta.get("name", ""))
            new_parents = meta.get("parents") or []
            current = new_parents[0] if new_parents else ""
        path = "/".join(reversed(segments))
        self._path_cache[file_id] = path
        return path

    def _upsert_file(self, drive_file: DriveFile) -> None:
        with sqlite3.connect(self.index_db_path) as conn:
            conn.execute(
                """
                INSERT INTO drive_files (
                    file_id, name, mime_type, size, modified_time,
                    parents, path, preview_text, category, tags,
                    vehicle_tags, automotive_score, last_indexed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    name=excluded.name,
                    mime_type=excluded.mime_type,
                    size=excluded.size,
                    modified_time=excluded.modified_time,
                    parents=excluded.parents,
                    path=excluded.path,
                    category=excluded.category,
                    tags=excluded.tags,
                    vehicle_tags=excluded.vehicle_tags,
                    automotive_score=excluded.automotive_score,
                    last_indexed=excluded.last_indexed
                """,
                (
                    drive_file.file_id,
                    drive_file.name,
                    drive_file.mime_type,
                    drive_file.size,
                    drive_file.modified_time.isoformat() if drive_file.modified_time else None,
                    json.dumps(drive_file.parents),
                    drive_file.path,
                    drive_file.preview_text,
                    drive_file.category,
                    json.dumps(drive_file.tags),
                    json.dumps(drive_file.vehicle_tags),
                    drive_file.automotive_score,
                    drive_file.last_indexed.isoformat() if drive_file.last_indexed else None,
                ),
            )
            # FTS mirror
            conn.execute(
                "DELETE FROM drive_files_fts WHERE file_id = ?",
                (drive_file.file_id,),
            )
            conn.execute(
                """
                INSERT INTO drive_files_fts (
                    file_id, name, path, preview_text, extracted_text,
                    tags, vehicle_tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    drive_file.file_id,
                    drive_file.name,
                    drive_file.path,
                    drive_file.preview_text,
                    "",
                    " ".join(drive_file.tags),
                    " ".join(drive_file.vehicle_tags),
                ),
            )
            conn.commit()

    def _update_stats(
        self,
        stats: IndexStats,
        drive_file: DriveFile,
        raw: dict[str, Any],
    ) -> None:
        stats.total_files += 1
        stats.total_size_bytes += drive_file.size
        if drive_file.automotive_score >= 0.3:
            stats.automotive_files += 1
        mime = drive_file.mime_type
        if mime == "application/pdf":
            stats.pdf_count += 1
        elif mime in (
            "application/zip",
            "application/x-rar-compressed",
            "application/x-rar",
            "application/x-7z-compressed",
        ):
            stats.archive_count += 1
        elif mime.startswith("video/"):
            stats.video_count += 1
        elif mime.startswith("image/"):
            stats.image_count += 1
        elif "document" in mime or mime == "text/plain":
            stats.document_count += 1
        cat = drive_file.category
        stats.categories[cat] = stats.categories.get(cat, 0) + 1

    # ------------------------------------------------------------------
    # Search / retrieval
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        file_type: str | None = None,
        make: str | None = None,
        max_results: int = 50,
    ) -> list[DriveFile]:
        """
        Busca archivos en el Drive por texto, marca, tipo.

        Examples:
            search("P0420 Mercedes")
            search("WinOLS maps", file_type="rar")
            search("wiring diagram", make="Toyota")
        """
        return await asyncio.to_thread(
            self._search_sync, query, file_type, make, max_results
        )

    def _search_sync(
        self,
        query: str,
        file_type: str | None,
        make: str | None,
        max_results: int,
    ) -> list[DriveFile]:
        conditions: list[str] = []
        params: list[Any] = []
        use_fts = bool(query and query.strip())

        sql_parts: list[str] = []
        if use_fts:
            sql_parts.append(
                "SELECT f.* FROM drive_files f "
                "JOIN drive_files_fts fts ON fts.file_id = f.file_id "
                "WHERE drive_files_fts MATCH ?"
            )
            params.append(_fts_sanitize(query))
        else:
            sql_parts.append("SELECT * FROM drive_files WHERE 1=1")

        if file_type:
            conditions.append("(f.name LIKE ? OR f.mime_type LIKE ?)" if use_fts else "(name LIKE ? OR mime_type LIKE ?)")
            params.extend([f"%.{file_type.lstrip('.')}%", f"%{file_type}%"])
        if make:
            mk = make.lower()
            conditions.append("(f.vehicle_tags LIKE ?)" if use_fts else "(vehicle_tags LIKE ?)")
            params.append(f'%"{mk}"%')

        if conditions:
            sql_parts.append(" AND " + " AND ".join(conditions))

        sql_parts.append(
            " ORDER BY " + ("f." if use_fts else "") + "automotive_score DESC LIMIT ?"
        )
        params.append(max_results)

        sql = "".join(sql_parts)
        with sqlite3.connect(self.index_db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                logger.warning("Busqueda FTS fallo (%s); fallback LIKE", exc)
                return self._search_like_fallback(query, file_type, make, max_results)

        return [self._row_to_drivefile(dict(r)) for r in rows]

    def _search_like_fallback(
        self,
        query: str,
        file_type: str | None,
        make: str | None,
        max_results: int,
    ) -> list[DriveFile]:
        with sqlite3.connect(self.index_db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM drive_files WHERE 1=1"
            params: list[Any] = []
            if query:
                sql += " AND (name LIKE ? OR path LIKE ? OR preview_text LIKE ?)"
                like = f"%{query}%"
                params.extend([like, like, like])
            if file_type:
                sql += " AND (name LIKE ? OR mime_type LIKE ?)"
                params.extend([f"%.{file_type.lstrip('.')}%", f"%{file_type}%"])
            if make:
                sql += " AND vehicle_tags LIKE ?"
                params.append(f'%"{make.lower()}"%')
            sql += " ORDER BY automotive_score DESC LIMIT ?"
            params.append(max_results)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_drivefile(dict(r)) for r in rows]

    def _row_to_drivefile(self, row: dict[str, Any]) -> DriveFile:
        return DriveFile(
            file_id=row["file_id"],
            name=row["name"],
            mime_type=row.get("mime_type") or "",
            size=row.get("size") or 0,
            path=row.get("path") or "",
            category=row.get("category") or FileCategory.MISCELLANEOUS.value,
            tags=_load_json_list(row.get("tags")),
            vehicle_tags=_load_json_list(row.get("vehicle_tags")),
            preview_text=row.get("preview_text") or "",
            automotive_score=row.get("automotive_score") or 0.0,
            last_indexed=_parse_dt(row.get("last_indexed")),
            modified_time=_parse_dt(row.get("modified_time")),
            parents=_load_json_list(row.get("parents")),
        )

    # ------------------------------------------------------------------
    # File access
    # ------------------------------------------------------------------

    async def get_file_content(self, file_id: str) -> bytes:
        """Descarga el contenido de un archivo del Drive."""
        self._require_service()
        await self._rate_limiter.acquire()
        return await asyncio.to_thread(self._download_sync, file_id)

    def _download_sync(self, file_id: str) -> bytes:
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)
        return buffer.getvalue()

    async def extract_text_from_pdf(self, file_id: str) -> str:
        """Descarga un PDF y extrae su texto."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            try:
                from pypdf import PdfReader  # type: ignore
            except ImportError:
                logger.warning(
                    "No hay extractor de PDF disponible (instala pymupdf o pypdf)."
                )
                return ""
            data = await self.get_file_content(file_id)
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:20])

        data = await self.get_file_content(file_id)
        text_parts: list[str] = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc[:20]:
                text_parts.append(page.get_text() or "")
        return "\n".join(text_parts)

    async def get_folder_structure(self, folder_id: str | None = None) -> dict[str, Any]:
        """Retorna la estructura de carpetas del Drive desde el indice."""
        return await asyncio.to_thread(self._folder_structure_sync, folder_id)

    def _folder_structure_sync(self, folder_id: str | None) -> dict[str, Any]:
        with sqlite3.connect(self.index_db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT file_id, name, mime_type, path, category, parents "
                "FROM drive_files "
                "WHERE mime_type = 'application/vnd.google-apps.folder' "
                "ORDER BY path"
            ).fetchall()
        folders = [dict(r) for r in rows]
        # Build a simple tree: id -> {children: [...]}
        tree: dict[str, dict[str, Any]] = {}
        for f in folders:
            tree[f["file_id"]] = {
                "file_id": f["file_id"],
                "name": f["name"],
                "path": f["path"],
                "children": [],
            }
        roots: list[dict[str, Any]] = []
        for f in folders:
            parents = _load_json_list(f.get("parents"))
            parent = parents[0] if parents else None
            if parent and parent in tree:
                tree[parent]["children"].append(tree[f["file_id"]])
            else:
                roots.append(tree[f["file_id"]])
        return {"roots": roots, "count": len(folders)}

    async def sync_folder(self, folder_id: str, local_path: Path) -> int:
        """
        Sincroniza una carpeta del Drive a local (para cache).

        Returns:
            Numero de archivos descargados.
        """
        self._require_service()
        local_path = Path(local_path)
        local_path.mkdir(parents=True, exist_ok=True)

        # List direct children of folder
        q = f"'{folder_id}' in parents and trashed = false"
        await self._rate_limiter.acquire()
        resp = await asyncio.to_thread(
            lambda: self.service.files()
            .list(
                q=q,
                pageSize=1000,
                fields="files(id, name, mimeType, size)",
            )
            .execute()
        )
        downloaded = 0
        for child in resp.get("files", []):
            if child["mimeType"] == "application/vnd.google-apps.folder":
                await self.sync_folder(child["id"], local_path / child["name"])
            else:
                try:
                    data = await self.get_file_content(child["id"])
                    (local_path / child["name"]).write_bytes(data)
                    downloaded += 1
                except HttpError as exc:
                    logger.warning("No se pudo descargar %s: %s", child["name"], exc)
        return downloaded

    async def watch_for_changes(
        self,
        callback: Callable[[list[dict[str, Any]]], Awaitable[None] | None],
        poll_interval: int = 300,
    ) -> None:
        """
        Monitorea cambios en el Drive y actualiza el indice.

        Usa la Changes API con startPageToken. Corre indefinidamente.
        """
        self._require_service()
        token = self._get_meta("changes_page_token")
        if not token:
            await self._rate_limiter.acquire()
            resp = await asyncio.to_thread(
                lambda: self.service.changes().getStartPageToken().execute()
            )
            token = resp["startPageToken"]
            self._set_meta("changes_page_token", token)

        while True:
            try:
                await self._rate_limiter.acquire()
                resp = await asyncio.to_thread(
                    lambda: self.service.changes()
                    .list(pageToken=token, fields="nextPageToken, newStartPageToken, changes(fileId, file, removed)")
                    .execute()
                )
                changes = resp.get("changes", [])
                if changes:
                    result = callback(changes)
                    if asyncio.iscoroutine(result):
                        await result
                if resp.get("newStartPageToken"):
                    token = resp["newStartPageToken"]
                    self._set_meta("changes_page_token", token)
                elif resp.get("nextPageToken"):
                    token = resp["nextPageToken"]
            except Exception as exc:
                logger.warning("Error polling changes: %s", exc)
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Classification / tagging
    # ------------------------------------------------------------------

    def categorize_file(self, file_info: dict[str, Any]) -> FileCategory:
        """Categoriza un archivo usando nombre/mime/path."""
        name = (file_info.get("name") or "").lower()
        mime = file_info.get("mimeType", "")
        path = (self._path_cache.get(file_info.get("id", ""), "") + " " + name).lower()

        if mime.startswith("video/"):
            return FileCategory.VIDEO_COURSE
        if any(k in path for k in ("damos", "a2l", "winols")):
            return FileCategory.WINOLS_DAMOS
        if any(k in path for k in ("wiring", "diagrama", "esquema", "schematic")):
            return FileCategory.WIRING_DIAGRAM
        if any(k in path for k in ("pinout", "pin-out", "pin out")):
            return FileCategory.ECU_PINOUT
        if any(k in path for k in ("dtc", "trouble code", "codigo falla", "fault code")):
            return FileCategory.DTC_DATABASE
        if any(k in path for k in ("map", "mapa", "tuning", "remap", "chiptun")):
            return FileCategory.TUNING_MAP
        if any(k in path for k in ("workshop", "taller", "service manual", "repair", "manual de")):
            return FileCategory.WORKSHOP_MANUAL
        if any(k in path for k in ("bulletin", "tsb", "boletin")):
            return FileCategory.TECHNICAL_BULLETIN
        if mime in (
            "application/zip",
            "application/x-rar-compressed",
            "application/x-rar",
            "application/x-7z-compressed",
        ) or name.endswith((".exe", ".msi", ".dmg")):
            return FileCategory.SOFTWARE_TOOL
        return FileCategory.MISCELLANEOUS

    def extract_vehicle_tags(
        self, file_name: str, file_content: str = ""
    ) -> list[str]:
        """
        Extrae tags de marca/modelo/año.
        Ej: "Mercedes_C280_2008_wiring.pdf" -> ["mercedes", "c280", "2008"]
        """
        haystack = f"{file_name} {file_content}".lower()
        tags: set[str] = set()

        makes = {
            "mercedes", "benz", "bmw", "audi", "vw", "volkswagen", "seat",
            "skoda", "porsche", "toyota", "lexus", "honda", "acura",
            "nissan", "infiniti", "mazda", "subaru", "mitsubishi",
            "hyundai", "kia", "genesis", "ford", "chevrolet", "gmc",
            "cadillac", "chrysler", "dodge", "jeep", "ram", "fiat",
            "alfa", "lancia", "peugeot", "citroen", "renault", "dacia",
            "opel", "vauxhall", "volvo", "saab", "mini", "land rover",
            "range rover", "jaguar", "tesla",
        }
        for m in makes:
            if re.search(rf"\b{re.escape(m)}\b", haystack):
                tags.add(m.replace(" ", "_"))

        # Years 1980-2030
        for year in re.findall(r"\b(19[89]\d|20[0-3]\d)\b", haystack):
            tags.add(year)

        # Common ECU codes
        for code in re.findall(r"\b(edc1[567]|med[0-9.]+|me7\.[0-9]+|simos\d+|mev\d+)\b", haystack):
            tags.add(code.lower())

        # Model-ish tokens: single letter + digits (C280, A4, X5, E90, M5)
        for m in re.findall(r"\b([a-z]{1,3}\d{2,4})\b", haystack):
            if m not in {"mp3", "mp4", "rar", "zip", "pdf"}:
                tags.add(m)

        return sorted(tags)

    def _extract_generic_tags(self, file_name: str) -> list[str]:
        """Tags basados en keywords automotrices."""
        name = file_name.lower()
        return sorted({k for k in self.AUTOMOTIVE_KEYWORDS if k in name})

    def _compute_automotive_score(
        self, name: str, mime: str, path: str
    ) -> float:
        """Score 0..1 de que tan automotriz es el archivo."""
        haystack = f"{name} {path}".lower()
        hits = sum(1 for k in self.AUTOMOTIVE_KEYWORDS if k in haystack)
        score = min(1.0, hits / 4.0)
        if mime == "application/vnd.google-apps.folder":
            score *= 0.5
        if mime == "application/pdf":
            score = min(1.0, score + 0.1)
        return round(score, 3)

    # ------------------------------------------------------------------
    # Convenience queries used by the API layer
    # ------------------------------------------------------------------

    def get_index_stats(self) -> IndexStats:
        """Lee las estadisticas guardadas o recalcula sobre la marcha."""
        raw = self._get_meta("last_stats")
        if raw:
            try:
                data = json.loads(raw)
                stats = IndexStats(
                    total_files=data.get("total_files", 0),
                    automotive_files=data.get("automotive_files", 0),
                    total_size_bytes=data.get("total_size_bytes", 0),
                    pdf_count=data.get("pdf_count", 0),
                    archive_count=data.get("archive_count", 0),
                    video_count=data.get("video_count", 0),
                    image_count=data.get("image_count", 0),
                    document_count=data.get("document_count", 0),
                    indexed_at=_parse_dt(data.get("indexed_at")),
                    categories=data.get("categories", {}),
                    errors=data.get("errors", 0),
                )
                return stats
            except Exception:
                pass
        # Recalc from DB
        with sqlite3.connect(self.index_db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM drive_files").fetchone()[0]
            auto = conn.execute(
                "SELECT COUNT(*) FROM drive_files WHERE automotive_score >= 0.3"
            ).fetchone()[0]
            size = conn.execute("SELECT COALESCE(SUM(size), 0) FROM drive_files").fetchone()[0]
        return IndexStats(
            total_files=total or 0,
            automotive_files=auto or 0,
            total_size_bytes=size or 0,
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _fts_sanitize(query: str) -> str:
    """
    Limpia el input del usuario para FTS5.

    Evita operadores que puedan reventar el parser y une terminos con AND
    implicita.
    """
    tokens = re.findall(r"[\w]+", query)
    if not tokens:
        return '""'
    return " ".join(f'"{t}"' for t in tokens)
