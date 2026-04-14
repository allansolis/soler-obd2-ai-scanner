"""
Data models for the Google Drive integration.

Everything here is plain-Python dataclass / enum — no I/O — so the
models can be serialized to JSON for the FastAPI endpoints and stored
in SQLite without coupling to the rest of the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any


class FileCategory(str, Enum):
    """
    Categorias internas en las que clasificamos archivos del Drive.

    Se guarda como string en SQLite, por eso heredamos de ``str``.
    """

    WORKSHOP_MANUAL = "workshop_manual"
    WIRING_DIAGRAM = "wiring_diagram"
    ECU_PINOUT = "ecu_pinout"
    DTC_DATABASE = "dtc_database"
    TUNING_MAP = "tuning_map"
    WINOLS_DAMOS = "winols_damos"
    SOFTWARE_TOOL = "software_tool"
    VIDEO_COURSE = "video_course"
    TECHNICAL_BULLETIN = "technical_bulletin"
    MISCELLANEOUS = "miscellaneous"

    @classmethod
    def from_value(cls, value: str | None) -> "FileCategory":
        if not value:
            return cls.MISCELLANEOUS
        try:
            return cls(value)
        except ValueError:
            return cls.MISCELLANEOUS


@dataclass
class DriveFile:
    """Representacion normalizada de un archivo indexado del Drive."""

    file_id: str
    name: str
    mime_type: str
    size: int
    path: str  # e.g. "4LAP/ECM Titanium/file.rar"
    category: str = FileCategory.MISCELLANEOUS.value
    tags: list[str] = field(default_factory=list)
    vehicle_tags: list[str] = field(default_factory=list)
    preview_text: str = ""
    automotive_score: float = 0.0
    last_indexed: datetime | None = None
    download_url: str = ""
    modified_time: datetime | None = None
    parents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.last_indexed:
            data["last_indexed"] = self.last_indexed.isoformat()
        if self.modified_time:
            data["modified_time"] = self.modified_time.isoformat()
        return data


@dataclass
class IndexStats:
    """Estadisticas resultantes de una indexacion del Drive."""

    total_files: int = 0
    automotive_files: int = 0
    total_size_bytes: int = 0
    pdf_count: int = 0
    archive_count: int = 0
    video_count: int = 0
    image_count: int = 0
    document_count: int = 0
    indexed_at: datetime | None = None
    categories: dict[str, int] = field(default_factory=dict)
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.indexed_at:
            data["indexed_at"] = self.indexed_at.isoformat()
        return data

    @property
    def total_size_human(self) -> str:
        """Tamaño total en formato humano (KB/MB/GB/TB)."""
        size = float(self.total_size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"


@dataclass
class IndexProgress:
    """Evento de progreso emitido durante la indexacion."""

    files_indexed: int
    total_estimated: int
    current_file: str = ""
    current_path: str = ""
    percent: float = 0.0
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    phase: str = "scanning"  # scanning | downloading | extracting | done

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
