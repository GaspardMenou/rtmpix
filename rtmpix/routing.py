"""Temps de marche réel par les rues, avec cache disque.

Le trajet appart → station ne bouge pas : on l'interroge une fois auprès d'un moteur de
routage piéton, on met le résultat en cache, et on n'y revient plus (`--refresh` force le
recalcul). Ce qui varie d'un jour à l'autre, ce n'est pas la géométrie mais l'allure —
c'est `walk.pace_factor` qui l'ajuste, et il se calibre au chronomètre.

Deux moteurs publics, sans clé :
  valhalla — tient compte du dénivelé, ce qui compte réellement à Marseille
  osrm     — plus rapide, terrain plat supposé
  haversine— repli hors ligne : vol d'oiseau majoré d'un facteur de détour
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from .geo import haversine_m, walk_seconds

log = logging.getLogger(__name__)

OSRM_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"
VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"


@dataclass
class Leg:
    distance_m: float
    duration_s: int
    engine: str


def _key(from_lat, from_lon, to_lat, to_lon) -> str:
    """~1 m de résolution : suffisant pour identifier un trajet, stable au rechargement."""
    return f"{from_lat:.5f},{from_lon:.5f}->{to_lat:.5f},{to_lon:.5f}"


class WalkRouter:
    def __init__(self, cfg, cache_path: Path):
        self.cfg = cfg
        self.engine = cfg.walk.engine
        self.timeout = cfg.sources.timeout_s
        self.headers = {"User-Agent": cfg.sources.user_agent}
        self.cache_path = cache_path
        self.cache: dict[str, dict] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("Cache de routage illisible, on repart de zéro.")

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")

    def leg(self, from_lat, from_lon, to_lat, to_lon, refresh: bool = False) -> Leg:
        key = _key(from_lat, from_lon, to_lat, to_lon)
        if not refresh and key in self.cache:
            entry = self.cache[key]
            return Leg(entry["distance_m"], entry["duration_s"], entry["engine"])

        leg = self._query(from_lat, from_lon, to_lat, to_lon)
        self.cache[key] = {
            "distance_m": leg.distance_m,
            "duration_s": leg.duration_s,
            "engine": leg.engine,
        }
        return leg

    def _query(self, from_lat, from_lon, to_lat, to_lon) -> Leg:
        engines = [self.engine] + [e for e in ("valhalla", "osrm") if e != self.engine]
        for engine in engines:
            if engine == "haversine":
                break
            try:
                if engine == "valhalla":
                    return self._valhalla(from_lat, from_lon, to_lat, to_lon)
                if engine == "osrm":
                    return self._osrm(from_lat, from_lon, to_lat, to_lon)
            except Exception as exc:
                log.warning("Routeur %s indisponible (%s), repli.", engine, exc)

        distance = haversine_m(from_lat, from_lon, to_lat, to_lon)
        return Leg(
            distance_m=distance,
            duration_s=walk_seconds(distance, self.cfg.walk.speed_mps, self.cfg.walk.detour_factor),
            engine="haversine",
        )

    def _osrm(self, from_lat, from_lon, to_lat, to_lon) -> Leg:
        url = f"{OSRM_URL}/{from_lon},{from_lat};{to_lon},{to_lat}"
        resp = requests.get(
            url, params={"overview": "false"}, headers=self.headers, timeout=self.timeout
        )
        resp.raise_for_status()
        route = resp.json()["routes"][0]
        return Leg(float(route["distance"]), int(round(route["duration"])), "osrm")

    def _valhalla(self, from_lat, from_lon, to_lat, to_lon) -> Leg:
        body = {
            "locations": [
                {"lat": from_lat, "lon": from_lon},
                {"lat": to_lat, "lon": to_lon},
            ],
            "costing": "pedestrian",
            "directions_options": {"units": "kilometers"},
        }
        resp = requests.post(VALHALLA_URL, json=body, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        # Le serveur public ajoute parfois du contenu après le document JSON.
        payload = json.JSONDecoder().raw_decode(resp.text)[0]
        summary = payload["trip"]["summary"]
        return Leg(float(summary["length"]) * 1000, int(round(summary["time"])), "valhalla")
