"""Découverte des arrêts autour du domicile et budget de temps porte-à-quai.

Le GTFS RTM n'a pas de `parent_station` renseigné : « Castellane » existe en une dizaine
de `stop_id` distincts (un par quai, par sens, par mode). On regroupe donc par nom, et on
retient pour chaque groupe le quai le plus proche — c'est vers celui-là qu'on marche.

Le temps total avant de pouvoir monter dans la rame se décompose en trois morceaux :

    door_delay  +  walk  +  access
    (immeuble)     (rue)     (entrée de la station -> quai)

Seul `walk` se calcule ; `access` se mesure. À La Rose ou Saint-Just on est sur le quai en
trente secondes, à Réformés ou Préfecture il faut compter deux bonnes minutes de couloirs.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from .config import DEFAULT_ACCESS_S
from .geo import haversine_m

log = logging.getLogger(__name__)


@dataclass
class Quay:
    """Un quai : la plus petite unité qui a un sens pour le temps réel."""

    stop_id: str
    name: str
    lat: float
    lon: float
    netex_id: str | None
    spoti: str | None
    distance_m: float


@dataclass
class Station:
    name: str
    quays: list[Quay]
    distance_m: float          # à vol d'oiseau, pour information
    route_walk_m: float        # distance réelle par les rues
    walk_s: int                # temps de marche, allure appliquée
    access_s: int              # entrée de la station -> quai
    modes: set[int]
    engine: str = "?"
    access_source: str = "défaut"
    walk_source: str = "routeur"

    @property
    def netex_ids(self) -> list[str]:
        return [q.netex_id for q in self.quays if q.netex_id]

    @property
    def mode_label(self) -> str:
        labels = {0: "tram", 1: "métro", 2: "train", 3: "bus", 4: "ferry"}
        return "/".join(sorted(labels.get(m, str(m)) for m in self.modes)) or "?"

    def lead_s(self, overhead_s: int) -> int:
        """Tout ce qu'il faut avoir devant soi pour être sur le quai à l'heure."""
        return self.walk_s + self.access_s + overhead_s


def _default_access(modes: set[int]) -> int:
    """Le mode le plus lent de la station commande (une station métro+bus reste un métro)."""
    if not modes:
        return DEFAULT_ACCESS_S[3]
    return max(DEFAULT_ACCESS_S.get(m, 30) for m in modes)


def find_nearby(
    conn: sqlite3.Connection, cfg, router, calibration, refresh: bool = False, limit: bool = True
) -> list[Station]:
    """Stations desservies dans le rayon configuré, budget de marche calculé et mis en cache.

    `limit=False` renvoie tout ce que le rayon contient — utile pour `rtmpix stops`, qui
    sert justement à choisir quelles stations garder.
    """
    home = cfg.home
    # Pré-filtre grossier en SQL sur une boîte lat/lon, distance exacte ensuite en Python :
    # à cette latitude, 1° de longitude ~= 81 km, 1° de latitude ~= 111 km.
    dlat = cfg.transit.radius_m / 111_000
    dlon = cfg.transit.radius_m / 81_000
    rows = conn.execute(
        "SELECT stop_id, name, lat, lon, netex_id, spoti FROM stops "
        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (home.lat - dlat, home.lat + dlat, home.lon - dlon, home.lon + dlon),
    ).fetchall()

    groups: dict[str, list[Quay]] = {}
    for r in rows:
        dist = haversine_m(home.lat, home.lon, r["lat"], r["lon"])
        if dist > cfg.transit.radius_m:
            continue
        quay = Quay(r["stop_id"], r["name"], r["lat"], r["lon"], r["netex_id"], r["spoti"], dist)
        groups.setdefault(r["name"], []).append(quay)

    stations: list[Station] = []
    for name, quays in groups.items():
        quays.sort(key=lambda q: q.distance_m)
        nearest = quays[0]

        modes = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT route_type FROM stop_modes WHERE stop_id IN "
                f"({','.join('?' * len(quays))})",
                [q.stop_id for q in quays],
            )
        }

        # Marche : mesure chronométrée si elle existe, sinon routage mis en cache.
        measured = calibration.walk.get(name)
        if measured is not None:
            walk_s, route_m, engine, walk_source = int(measured), nearest.distance_m, "mesuré", "chrono"
        else:
            leg = router.leg(home.lat, home.lon, nearest.lat, nearest.lon, refresh=refresh)
            walk_s = int(round(leg.duration_s * calibration.pace_factor))
            route_m, engine, walk_source = leg.distance_m, leg.engine, "routeur"

        # Accès : calibration, puis config, puis défaut par mode.
        if name in calibration.access:
            access_s, access_source = int(calibration.access[name]), "chrono"
        elif name in cfg.transit.access_s:
            access_s, access_source = int(cfg.transit.access_s[name]), "config"
        else:
            access_s, access_source = _default_access(modes), "défaut"

        stations.append(
            Station(
                name=name,
                quays=quays,
                distance_m=nearest.distance_m,
                route_walk_m=route_m,
                walk_s=walk_s,
                access_s=access_s,
                modes=modes,
                engine=engine,
                access_source=access_source,
                walk_source=walk_source,
            )
        )

    stations.sort(key=lambda s: s.walk_s + s.access_s)
    router.save()
    return stations[: cfg.transit.max_stations] if limit else stations
