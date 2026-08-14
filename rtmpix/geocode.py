"""Recherche d'un lieu par son nom, via Nominatim (OpenStreetMap).

Saisir des coordonnées à la main est pénible et source d'erreurs — quelques centaines de
mètres suffisent à changer l'arrêt le plus proche, donc les itinéraires proposés. On laisse
donc chercher « École Centrale Méditerranée » et on choisit dans une liste.

Nominatim est un service public gratuit avec des règles d'usage strictes : un appel par seconde
au plus, et un User-Agent identifiable. Ici la recherche est déclenchée à la main, quelques
fois dans la vie du service, et les résultats sont mis en cache.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

NOMINATIM = "https://nominatim.openstreetmap.org/search"
MIN_INTERVAL_S = 1.1   # la politique d'usage impose au plus une requête par seconde


@dataclass
class Place:
    label: str
    lat: float
    lon: float


class Geocoder:
    def __init__(self, cfg, cache_path: Path):
        self.timeout = cfg.sources.timeout_s
        # Un User-Agent identifiable est exigé par Nominatim ; un défaut générique se fait
        # refuser, et à juste titre.
        self.headers = {"User-Agent": cfg.sources.user_agent}
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self._last_call = 0.0
        self._cache: dict[str, list[dict]] = {}
        if cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}

    def search(self, query: str, limit: int = 5, viewbox: str | None = None) -> list[Place]:
        query = (query or "").strip()
        if len(query) < 3:
            return []

        key = f"{query.casefold()}|{limit}"
        if key in self._cache:
            return [Place(**item) for item in self._cache[key]]

        with self.lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

            params = {
                "q": query,
                "format": "json",
                "limit": limit,
                "addressdetails": 0,
                # Priorité aux résultats des Bouches-du-Rhône sans les y enfermer :
                # une destination hors métropole reste trouvable.
                "viewbox": viewbox or "5.10,43.60,5.80,43.10",
                "bounded": 0,
            }
            try:
                resp = requests.get(
                    NOMINATIM, params=params, headers=self.headers, timeout=self.timeout
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("Recherche de lieu impossible (%s)", exc)
                return []

        places = [
            {
                "label": item.get("display_name", "?"),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
            }
            for item in payload
            if item.get("lat") and item.get("lon")
        ]
        self._cache[key] = places
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return [Place(**item) for item in places]
