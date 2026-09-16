"""
Scaner Soler Pro — cliente HTTP para el backend FastAPI.

Si el backend no está disponible, todos los métodos retornan None
o {"error": "backend_offline"} sin lanzar excepciones.
"""
from __future__ import annotations

import logging
from typing import Any

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

log = logging.getLogger(__name__)

_TIMEOUT = 3  # segundos


class BackendClient:
    """Cliente ligero para el backend FastAPI en http://localhost:8000."""

    BASE_URL = "http://localhost:8000"

    # ------------------------------------------------------------------ #
    # helpers internos                                                     #
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict | None = None) -> Any:
        if not _REQUESTS_OK:
            return None
        try:
            resp = requests.get(
                f"{self.BASE_URL}{path}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.debug("BackendClient GET %s => %s", path, exc)
            return None

    def _post(self, path: str, payload: dict) -> Any:
        if not _REQUESTS_OK:
            return None
        try:
            resp = requests.post(
                f"{self.BASE_URL}{path}", json=payload, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.debug("BackendClient POST %s => %s", path, exc)
            return None

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def is_online(self) -> bool:
        """Verifica si el backend responde en /health."""
        if not _REQUESTS_OK:
            return False
        try:
            resp = requests.get(f"{self.BASE_URL}/health", timeout=_TIMEOUT)
            return resp.ok
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """Conecta el emulador si el backend está online pero no conectado."""
        if not self.is_online():
            return False
        try:
            st = requests.get(f"{self.BASE_URL}/api/status", timeout=_TIMEOUT)
            if st.ok and st.json().get("connected"):
                return True
            # Conectar al emulador
            r = requests.post(f"{self.BASE_URL}/api/connect",
                              json={"use_emulator": True}, timeout=_TIMEOUT)
            return r.ok
        except Exception:
            return False

    def chat(self, message: str, context: dict | None = None) -> str | None:
        """POST /api/ai/chat — devuelve el texto de respuesta o None."""
        payload: dict = {"message": message}
        if context:
            payload["context"] = context
        result = self._post("/api/ai/chat", payload)
        if result is None:
            return None
        # Acepta {"response": "..."} o {"message": "..."} o string directo
        if isinstance(result, dict):
            return result.get("response") or result.get("message") or str(result)
        return str(result)

    def get_dtc_info(self, code: str) -> dict:
        """GET /api/hub/dtc/{code}."""
        result = self._get(f"/api/hub/dtc/{code}")
        if result is None:
            return {"error": "backend_offline", "code": code}
        return result

    def get_repair_guide(self, dtc_code: str, make: str = "") -> str | None:
        """POST /api/ai/repair-guide — guía de reparación para un DTC."""
        result = self._post("/api/ai/repair-guide", {
            "dtc_code": dtc_code,
            "vehicle_make": make,
        })
        if result is None:
            return None
        if isinstance(result, dict):
            return result.get("guide") or result.get("response") or str(result)
        return str(result)

    def get_expert_advice(
        self,
        scenario: str,
        dtc_codes: list[str] | None = None,
        make: str = "",
    ) -> dict:
        """POST /api/expert/advise — consejo experto para un escenario."""
        result = self._post("/api/expert/advise", {
            "scenario": scenario,
            "dtc_codes": dtc_codes or [],
            "vehicle_make": make,
        })
        if result is None:
            return {"error": "backend_offline"}
        return result

    def search_hub(self, query: str, make: str = "") -> list[dict]:
        """GET /api/hub/search?q={query}&make={make}."""
        result = self._get("/api/hub/search", params={"q": query, "make": make})
        if result is None:
            return []
        if isinstance(result, list):
            return result
        # A veces viene {"results": [...]}
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    def get_vehicle_context(self, make: str, model: str) -> dict:
        """GET /api/hub/vehicle/{make}/{model}."""
        result = self._get(f"/api/hub/vehicle/{make}/{model}")
        if result is None:
            return {"error": "backend_offline"}
        return result

    def get_live_sensors(self) -> dict:
        """GET /api/sensors — sensores del emulador OBD."""
        self.ensure_connected()
        result = self._get("/api/sensors")
        if result is None:
            return {"error": "backend_offline"}
        return result

    def get_health_score(self) -> dict:
        """GET /api/health-score — score de salud del motor."""
        self.ensure_connected()
        result = self._get("/api/health-score")
        if result is None:
            return {"error": "backend_offline"}
        return result
