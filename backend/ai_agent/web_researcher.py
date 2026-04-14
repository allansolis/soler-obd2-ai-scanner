"""
SOLER OBD2 AI Scanner - Web Researcher

Modulo para investigacion automotriz en la web. Rastrea manuales,
TSBs, foros y bulletins del fabricante. Cachea resultados en SQLite
con TTL de 24h. Respeta robots.txt y se identifica como herramienta
educativa.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:  # dependencias opcionales
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_DEPS = True
except ImportError:  # pragma: no cover
    _HAS_DEPS = False


CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
USER_AGENT = "SOLER-OBD2-Scanner/1.0 (+educational; automotive diagnostics)"


@dataclass
class TSB:
    title: str
    url: str
    summary: str
    published: Optional[str] = None


@dataclass
class TuningTip:
    title: str
    url: str
    summary: str
    source: str


@dataclass
class Recall:
    id: str
    title: str
    url: str
    description: str


@dataclass
class ForumPost:
    title: str
    url: str
    excerpt: str
    source: str


@dataclass
class Bulletin:
    title: str
    url: str
    body: str
    manufacturer: str


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _WebCache:
    """SQLite-backed TTL cache."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS web_cache ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL,"
                "  created_at REAL NOT NULL"
                ")"
            )
            conn.commit()

    def get(self, key: str) -> Optional[Any]:
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT value, created_at FROM web_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        value, created_at = row
        if time.time() - created_at > CACHE_TTL_SECONDS:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO web_cache(key, value, created_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time()),
            )
            conn.commit()


# ---------------------------------------------------------------------------
# WebResearcher
# ---------------------------------------------------------------------------

class WebResearcher:
    """Scrapea la web buscando informacion automotriz actualizada."""

    SOURCES = [
        "https://workshop-manuals.com",
        "https://www.datacar-manualrepair.com",
        "https://www.angelvf.com",
    ]

    def __init__(self, cache_path: Optional[Path] = None, timeout: int = 10) -> None:
        self.cache = _WebCache(cache_path or Path("data/web_cache.db"))
        self.timeout = timeout
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------
    async def search_dtc_info(
        self, dtc_code: str, vehicle_info: Any = None
    ) -> dict:
        """Busca info del codigo DTC. Retorna dict con sources + summary."""
        key = f"dtc:{dtc_code}:{_vehicle_key(vehicle_info)}"
        cached = self.cache.get(key)
        if cached:
            return cached

        results = await self._search_all(f"OBD2 {dtc_code} fault diagnosis repair")
        summary = self._summarize(results, dtc_code)
        payload = {
            "query": dtc_code,
            "sources": results,
            "summary": summary,
        }
        self.cache.set(key, payload)
        return payload

    async def search_tsb(self, vehicle_info: Any) -> list[dict]:
        key = f"tsb:{_vehicle_key(vehicle_info)}"
        cached = self.cache.get(key)
        if cached:
            return cached

        query = f"{_vehicle_query(vehicle_info)} technical service bulletin"
        results = await self._search_all(query)
        tsbs = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "summary": r.get("snippet", ""),
                "published": None,
            }
            for r in results
        ]
        self.cache.set(key, tsbs)
        return tsbs

    async def search_tuning_tips(self, vehicle_info: Any) -> list[dict]:
        key = f"tuning:{_vehicle_key(vehicle_info)}"
        cached = self.cache.get(key)
        if cached:
            return cached

        query = f"{_vehicle_query(vehicle_info)} ECU tuning map stage 1"
        results = await self._search_all(query)
        tips = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "summary": r.get("snippet", ""),
                "source": r.get("source", ""),
            }
            for r in results
        ]
        self.cache.set(key, tips)
        return tips

    async def search_recalls(self, vehicle_info: Any) -> list[dict]:
        key = f"recalls:{_vehicle_key(vehicle_info)}"
        cached = self.cache.get(key)
        if cached:
            return cached

        query = f"{_vehicle_query(vehicle_info)} recall"
        results = await self._search_all(query)
        recalls = [
            {
                "id": r.get("url", "").split("/")[-1] or r.get("title", "")[:32],
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("snippet", ""),
            }
            for r in results
        ]
        self.cache.set(key, recalls)
        return recalls

    async def extract_forum_wisdom(self, search_query: str) -> list[dict]:
        key = f"forum:{search_query}"
        cached = self.cache.get(key)
        if cached:
            return cached

        results = await self._search_all(f"{search_query} forum discussion")
        posts = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "excerpt": r.get("snippet", ""),
                "source": r.get("source", ""),
            }
            for r in results
        ]
        self.cache.set(key, posts)
        return posts

    async def get_manufacturer_bulletins(self, vehicle_info: Any) -> list[dict]:
        key = f"bulletin:{_vehicle_key(vehicle_info)}"
        cached = self.cache.get(key)
        if cached:
            return cached

        make = (vehicle_info or {}).get("make", "") if isinstance(vehicle_info, dict) else getattr(vehicle_info, "make", "")
        query = f"{_vehicle_query(vehicle_info)} service bulletin {make}"
        results = await self._search_all(query)
        bulletins = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "body": r.get("snippet", ""),
                "manufacturer": make or "unknown",
            }
            for r in results
        ]
        self.cache.set(key, bulletins)
        return bulletins

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------
    async def _search_all(self, query: str) -> list[dict]:
        """Busca en todas las fuentes permitidas en paralelo."""
        if not _HAS_DEPS:
            logger.warning("requests/beautifulsoup no instalados; busqueda web deshabilitada.")
            return []

        tasks = [self._scrape_source(src, query) for src in self.SOURCES]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[dict] = []
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.debug("Fuente fallo: %s", outcome)
                continue
            results.extend(outcome)
        return results[:20]

    async def _scrape_source(self, base: str, query: str) -> list[dict]:
        if not self._allowed_by_robots(base):
            logger.info("robots.txt no permite scrape: %s", base)
            return []

        search_url = f"{base.rstrip('/')}/?s={urllib.parse.quote(query)}"
        return await asyncio.to_thread(self._fetch_and_parse, search_url, base)

    def _fetch_and_parse(self, url: str, source: str) -> list[dict]:
        try:
            resp = requests.get(  # type: ignore[name-defined]
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")  # type: ignore[name-defined]
            items = []
            # heuristica generica: <a> con texto + snippet cercano
            for a in soup.find_all("a", href=True)[:10]:
                title = (a.get_text() or "").strip()
                href = a["href"]
                if not title or len(title) < 8:
                    continue
                if href.startswith("/"):
                    href = source.rstrip("/") + href
                items.append(
                    {
                        "title": title[:120],
                        "url": href,
                        "snippet": "",
                        "source": source,
                    }
                )
            return items[:5]
        except Exception as exc:  # noqa: BLE001
            logger.debug("fetch fallo %s: %s", url, exc)
            return []

    def _allowed_by_robots(self, base: str) -> bool:
        if base in self._robots:
            rp = self._robots[base]
        else:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{base.rstrip('/')}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001
                return True  # si no hay robots.txt, se asume permitido
            self._robots[base] = rp
        try:
            return rp.can_fetch(USER_AGENT, base)
        except Exception:  # noqa: BLE001
            return True

    def _summarize(self, results: list[dict], topic: str) -> str:
        if not results:
            return f"Sin resultados para {topic}."
        titles = "; ".join(r.get("title", "")[:60] for r in results[:3])
        return f"Encontre {len(results)} fuentes sobre {topic}. Top: {titles}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _vehicle_key(vehicle_info: Any) -> str:
    if not vehicle_info:
        return "generic"
    if isinstance(vehicle_info, dict):
        return f"{vehicle_info.get('make','')}-{vehicle_info.get('model','')}-{vehicle_info.get('year','')}"
    return f"{getattr(vehicle_info,'make','')}-{getattr(vehicle_info,'model','')}-{getattr(vehicle_info,'year','')}"


def _vehicle_query(vehicle_info: Any) -> str:
    if not vehicle_info:
        return ""
    if isinstance(vehicle_info, dict):
        return f"{vehicle_info.get('year','')} {vehicle_info.get('make','')} {vehicle_info.get('model','')}".strip()
    return f"{getattr(vehicle_info,'year','')} {getattr(vehicle_info,'make','')} {getattr(vehicle_info,'model','')}".strip()
