"""Disponibilité LeVélo via le flux GBFS 2.2 de la Métropole.

Flux public, sans clé, rafraîchi toutes les 60 s. `station_information` est quasi
statique (on la garde en cache), `station_status` est le temps réel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from .geo import haversine_m, walk_seconds

log = logging.getLogger(__name__)


@dataclass
class VeloStation:
    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int
    distance_m: float
    walk_s: int
    bikes: int = 0
    docks: int = 0
    renting: bool = True
    returning: bool = True


class VeloClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.timeout = cfg.sources.timeout_s
        self.headers = {"User-Agent": cfg.sources.user_agent}
        self._info: dict[str, VeloStation] | None = None

    def _load_information(self) -> dict[str, VeloStation]:
        resp = requests.get(
            self.cfg.velo_gbfs.station_information, headers=self.headers, timeout=self.timeout
        )
        resp.raise_for_status()
        home = self.cfg.home
        stations: dict[str, VeloStation] = {}
        for s in resp.json()["data"]["stations"]:
            distance = haversine_m(home.lat, home.lon, s["lat"], s["lon"])
            if distance > self.cfg.velo.radius_m:
                continue
            stations[s["station_id"]] = VeloStation(
                station_id=s["station_id"],
                name=s.get("name", "?"),
                lat=s["lat"],
                lon=s["lon"],
                capacity=int(s.get("capacity") or 0),
                distance_m=distance,
                walk_s=walk_seconds(
                    distance, self.cfg.walk.speed_mps, self.cfg.walk.detour_factor
                ),
            )
        log.info("Stations LeVélo dans le rayon : %d", len(stations))
        return stations

    def nearby(self) -> list[VeloStation]:
        """Stations proches avec leur disponibilité courante, la plus proche d'abord."""
        if self._info is None:
            self._info = self._load_information()
        if not self._info:
            return []

        resp = requests.get(
            self.cfg.velo_gbfs.station_status, headers=self.headers, timeout=self.timeout
        )
        resp.raise_for_status()

        out = []
        for s in resp.json()["data"]["stations"]:
            station = self._info.get(s["station_id"])
            if station is None:
                continue
            station.bikes = int(s.get("num_bikes_available") or 0)
            station.docks = int(s.get("num_docks_available") or 0)
            station.renting = bool(s.get("is_renting", True)) and bool(s.get("is_installed", True))
            station.returning = bool(s.get("is_returning", True))
            out.append(station)

        out.sort(key=lambda s: s.walk_s)
        return out[: self.cfg.velo.stations]
