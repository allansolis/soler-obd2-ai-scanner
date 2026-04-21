"""Pytest configuration and fixtures for SOLER backend tests."""
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """FastAPI test client for API tests."""
    from backend.api.server import app
    return TestClient(app)


@pytest.fixture(scope="session")
def hub():
    """Shared KnowledgeHub instance."""
    from backend.knowledge_hub.hub import KnowledgeHub
    return KnowledgeHub()
