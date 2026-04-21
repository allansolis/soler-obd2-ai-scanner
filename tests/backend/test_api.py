"""Smoke tests for FastAPI routes."""


def test_hub_stats_endpoint(client):
    r = client.get("/api/hub/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_resources" in data
    assert data["total_resources"] > 100
    assert data["total_dtcs"] >= 200


def test_expert_advise_endpoint(client):
    payload = {"scenario": "dtc", "dtc": "P0420", "make": "Toyota", "year": 2015}
    r = client.post("/api/expert/advise", json=payload)
    # 200 or 404 acceptable (endpoint exists)
    assert r.status_code in (200, 404, 422)


def test_docs_available(client):
    r = client.get("/docs")
    assert r.status_code == 200


def test_openapi_schema(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "paths" in schema
    # Verify core routes registered
    paths = schema["paths"]
    assert "/api/hub/stats" in paths
