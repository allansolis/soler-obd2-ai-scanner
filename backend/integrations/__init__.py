"""
SOLER OBD2 AI Scanner - Integrations Package.

External service integrations that expand the capabilities of the
SOLER AI Copilot. The flagship integration here is Google Drive, which
turns the user's 2TB Drive into the agent's knowledge base.
"""

from __future__ import annotations

from backend.integrations.drive_models import DriveFile, FileCategory, IndexStats
from backend.integrations.google_drive import GoogleDriveKnowledgeBase
from backend.integrations.drive_indexer import DriveIndexer

__all__ = [
    "DriveFile",
    "FileCategory",
    "IndexStats",
    "GoogleDriveKnowledgeBase",
    "DriveIndexer",
]
