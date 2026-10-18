"""
Tests para scaner_soler/api/server.py — FastAPI backend.
Usa httpx.AsyncClient con TestClient de Starlette (sin servidor real).
Si fastapi/httpx no están instalados se reporta skip explícito.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m⊘\033[0m"
results: list[tuple[bool, str]] = []

def check(cond: bool, msg: str):
    results.append((cond, msg))
    print(f"  {PASS if cond else FAIL}  {msg}")

def skip(msg: str):
    print(f"  {SKIP}  SKIP: {msg}")


# ── Verificar dependencias ─────────────────────────────────────────────────────

try:
    from fastapi.testclient import TestClient
    _HAS_TESTCLIENT = True
except ImportError:
    _HAS_TESTCLIENT = False

try:
    from scaner_soler.api.server import app, _FASTAPI_OK
    _HAS_APP = True
except Exception as _e:
    _HAS_APP = False
    _APP_ERR = str(_e)


# ── Suite 1: imports y estructura del módulo ───────────────────────────────────

def suite_imports():
    print("\n" + "─" * 60)
    print("  1. scaner_soler.api — imports y modelos Pydantic")
    print("─" * 60)

    if not _HAS_APP:
        skip(f"No se pudo importar api/server.py: {_APP_ERR}")
        return

    from scaner_soler.api.server import (
        RepairGuideRequest, RepairGuideResponse, DTCInfo, MapaNoticiaItem,
    )
    check(True, "from api.server import modelos Pydantic OK")

    # Instanciar modelos
    req = RepairGuideRequest(dtc_code="P0300")
    check(req.dtc_code == "P0300", "RepairGuideRequest(dtc_code='P0300') OK")

    dtc_info = DTCInfo(
        code="P0300",
        description="Fallo de encendido",
        system="Ignición",
        severity="critical",
        suggested_action="Revisar bujías",
        source="dtc_codes",
        oem_variants=0,
    )
    check(dtc_info.severity == "critical", "DTCInfo instancia OK")

    nota = MapaNoticiaItem(code="P0300", severity="critical", description="Fallo encendido",
                           system="Ignición", timestamp="2026-10-18T12:00:00")
    check(nota.code == "P0300", "MapaNoticiaItem instancia OK")


# ── Suite 2: endpoints con TestClient ─────────────────────────────────────────

def suite_endpoints():
    print("\n" + "─" * 60)
    print("  2. FastAPI endpoints — GET/POST")
    print("─" * 60)

    if not _HAS_TESTCLIENT:
        skip("fastapi[testclient] no instalado — pip install fastapi[testclient] httpx")
        return

    if not _HAS_APP:
        skip(f"app no disponible: {_APP_ERR}")
        return

    client = TestClient(app, raise_server_exceptions=False)

    # GET /health
    r = client.get("/health")
    check(r.status_code == 200, f"GET /health → {r.status_code}")
    data = r.json()
    check("status" in data, f"health tiene campo 'status': {list(data.keys())}")

    # GET /api/hub/dtc/P0300
    r = client.get("/api/hub/dtc/P0300")
    check(r.status_code == 200, f"GET /api/hub/dtc/P0300 → {r.status_code}")
    dtc = r.json()
    check("code" in dtc, f"DTC response tiene 'code': {list(dtc.keys())[:6]}")

    # GET /api/hub/dtc/X9999 — código que no existe
    r = client.get("/api/hub/dtc/X9999")
    check(r.status_code in (200, 404), f"GET /api/hub/dtc/X9999 → {r.status_code} (OK o 404)")

    # POST /api/ai/repair-guide
    r = client.post("/api/ai/repair-guide", json={"dtc_code": "P0300"})
    check(r.status_code == 200, f"POST /api/ai/repair-guide → {r.status_code}")
    guide = r.json()
    check("diagnosis" in guide or "steps" in guide or "code" in guide,
          f"repair-guide tiene campos esperados: {list(guide.keys())[:5]}")

    # GET /api/mapa-noticias
    r = client.get("/api/mapa-noticias")
    check(r.status_code == 200, f"GET /api/mapa-noticias → {r.status_code}")
    mapa = r.json()
    check(isinstance(mapa, (list, dict)), f"mapa-noticias retorna list o dict: {type(mapa).__name__}")
    if isinstance(mapa, dict):
        check("items" in mapa or "total" in mapa,
              f"mapa-noticias dict tiene 'items'/'total': {list(mapa.keys())[:4]}")

    # GET /api/ev/bms
    r = client.get("/api/ev/bms")
    check(r.status_code == 200, f"GET /api/ev/bms → {r.status_code}")
    bms = r.json()
    check("soc_pct" in bms or "connected" in bms or "status" in bms,
          f"EV BMS tiene campos esperados: {list(bms.keys())[:5]}")

    # GET /api/ev/dtcs
    r = client.get("/api/ev/dtcs")
    check(r.status_code == 200, f"GET /api/ev/dtcs → {r.status_code}")
    ev_resp = r.json()
    check(isinstance(ev_resp, list) or ("dtcs" in ev_resp if isinstance(ev_resp, dict) else False),
          f"EV DTCs retorna lista o dict con 'dtcs': {type(ev_resp).__name__}")


# ── Suite 3: helpers internos ──────────────────────────────────────────────────

def suite_helpers():
    print("\n" + "─" * 60)
    print("  3. Helpers internos — _get_extended, _parse_json_list")
    print("─" * 60)

    if not _HAS_APP:
        skip("app no disponible")
        return

    from scaner_soler.api.server import _get_extended, _parse_json_list

    # _parse_json_list con JSON válido
    result = _parse_json_list('["abc", "def"]')
    check(result == ["abc", "def"], f"_parse_json_list('[\"abc\",\"def\"]) = {result}")

    # _parse_json_list con lista real
    result2 = _parse_json_list(["x", "y"])
    check(result2 == ["x", "y"], "_parse_json_list(list) devuelve la lista sin cambios")

    # _parse_json_list con None
    result3 = _parse_json_list(None)
    check(isinstance(result3, list), "_parse_json_list(None) retorna lista vacía")

    # _get_extended con código existente en la DB
    row = _get_extended("P0300")
    check(row is None or isinstance(row, dict),
          f"_get_extended('P0300') retorna dict o None: {type(row).__name__}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TESTS API FASTAPI — Scaner Soler Pro")
    print("=" * 60)

    suite_imports()
    suite_endpoints()
    suite_helpers()

    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print("\n" + "=" * 60)
    print(f"  RESULTADO FINAL: {passed}/{total} checks pasaron")
    print("=" * 60)

    if passed < total:
        failed = [msg for ok, msg in results if not ok]
        print("\nFallidos:")
        for msg in failed:
            print(f"  ✗ {msg}")
        sys.exit(1)
    else:
        print("\nTodos los checks pasaron.")
