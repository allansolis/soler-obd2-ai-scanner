"""Tests for KnowledgeHub core operations."""
import pytest


def test_hub_initializes(hub):
    assert hub is not None
    assert hub.SessionLocal is not None


def test_hub_has_resources(hub):
    from backend.knowledge_hub.schema import Resource
    with hub.SessionLocal() as session:
        count = session.query(Resource).count()
    assert count > 100, f"expected >100 resources, got {count}"


def test_hub_has_dtc_catalog(hub):
    from backend.knowledge_hub.schema import DTCCatalog
    with hub.SessionLocal() as session:
        count = session.query(DTCCatalog).count()
    # After expansion we have 200+ DTCs
    assert count >= 200, f"expected >=200 DTCs, got {count}"


def test_hub_has_software_tools(hub):
    from backend.knowledge_hub.schema import SoftwareTool
    with hub.SessionLocal() as session:
        count = session.query(SoftwareTool).count()
    assert count >= 15, f"expected >=15 tools, got {count}"


def test_specific_dtc_lookup(hub):
    """P0420 should exist with structured data."""
    from backend.knowledge_hub.schema import DTCCatalog
    from sqlalchemy import select
    with hub.SessionLocal() as session:
        dtc = session.execute(
            select(DTCCatalog).where(DTCCatalog.code == "P0420")
        ).scalar_one_or_none()
    assert dtc is not None, "P0420 debe existir en DTC catalog"
    assert dtc.description_es, "debe tener descripcion en español"
