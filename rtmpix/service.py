"""Cœur du service : rassemble les sources, calcule les écrans, pousse vers l'horloge.

Un seul objet `Service` détient l'état ; la boucle principale et le dashboard web y
accèdent tous les deux, sous verrou. L'horloge, elle, ne fait qu'afficher.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from datetime import datetime

from . import gtfs, render, stations as stations_mod
from .awtrix import Awtrix
from .calibration import Calibration
from .departures import build_boards
from .disruptions import DisruptionClient, relevant
from .realtime import PARIS, RealtimeService
from .routing import WalkRouter
from .velo import VeloClient

log = logging.getLogger(__name__)


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.RLock()

        self.calibration = Calibration.load(cfg.calibration_path)
        self.conn = gtfs.Database(cfg.db_path)
        self.router = WalkRouter(cfg, cfg.routing_cache_path)
        self.realtime = RealtimeService(cfg, self.conn)
        self.velo_client = VeloClient(cfg) if cfg.velo.enabled else None
        self.disruption_client = DisruptionClient(cfg) if cfg.disruptions.enabled else None
        self.awtrix = Awtrix(cfg) if cfg.awtrix.enabled else None

        self.stations: list = []
        self.boards: list = []
        self.velo_stations: list = []
        self.disruptions: list = []
        self.last_departures_at: datetime | None = None
        self.last_velo_at: datetime | None = None
        self.last_push_ok: bool | None = None

        self.reload_stations()

    # ---------------------------------------------------------------- stations

    def reload_stations(self, refresh_routing: bool = False) -> None:
        with self.lock:
            self.stations = stations_mod.find_nearby(
                self.conn, self.cfg, self.router, self.calibration, refresh=refresh_routing
            )
            log.info(
                "Stations retenues : %s",
                ", ".join(
                    f"{s.name} ({s.walk_s // 60}′{s.walk_s % 60:02d} + {s.access_s}s)"
                    for s in self.stations
                )
                or "aucune",
            )

    def set_access(self, station_name: str, seconds: int | None) -> None:
        """Règle le temps entrée -> quai d'une station (None efface la calibration)."""
        with self.lock:
            if seconds is None:
                self.calibration.access.pop(station_name, None)
            else:
                self.calibration.access[station_name] = max(0, int(seconds))
            self.calibration.save(self.cfg.calibration_path)
            self.reload_stations()

    def set_walk(self, station_name: str, seconds: int | None) -> None:
        """Fige un temps de marche mesuré au chrono (None rend la main au routeur)."""
        with self.lock:
            if seconds is None:
                self.calibration.walk.pop(station_name, None)
            else:
                self.calibration.walk[station_name] = max(0, int(seconds))
            self.calibration.save(self.cfg.calibration_path)
            self.reload_stations()

    def set_pace(self, factor: float) -> None:
        """1.0 = allure du routeur, 0.85 = tu marches 15 % plus vite."""
        with self.lock:
            self.calibration.pace_factor = max(0.4, min(2.5, float(factor)))
            self.calibration.save(self.cfg.calibration_path)
            self.reload_stations()

    # ----------------------------------------------------------------- sources

    def refresh_departures(self) -> None:
        now = datetime.now(PARIS)
        departures = self.realtime.fetch(self.stations)
        with self.lock:
            self.boards = build_boards(departures, self.stations, self.cfg, now)
            self.last_departures_at = now

    def refresh_velo(self) -> None:
        if self.velo_client is None:
            return
        try:
            found = self.velo_client.nearby()
        except Exception as exc:
            log.warning("LeVélo indisponible : %s", exc)
            return
        with self.lock:
            self.velo_stations = found
            self.last_velo_at = datetime.now(PARIS)

    def refresh_disruptions(self) -> None:
        if self.disruption_client is None:
            return
        found = self.disruption_client.fetch()
        my_lines = {b.line for b in self.boards} or {
            q.name for s in self.stations for q in s.quays
        }
        with self.lock:
            self.disruptions = relevant(
                found, {b.line for b in self.boards} or my_lines, self.cfg.disruptions.only_my_lines
            )

    # ------------------------------------------------------------------ sortie

    def build_apps(self, now: datetime | None = None) -> dict[str, dict]:
        now = now or datetime.now(PARIS)
        apps: dict[str, dict] = {}
        with self.lock:
            for board in self.boards:
                suffix, payload = render.board_app(board, now)
                apps[suffix] = payload
            for station in self.velo_stations:
                suffix, payload = render.velo_app(station)
                apps[suffix] = payload
            for disruption in self.disruptions[:2]:
                suffix, payload = render.disruption_app(disruption)
                apps[suffix] = payload
        return apps

    def push(self) -> None:
        if self.awtrix is None:
            return
        apps = self.build_apps()
        try:
            self.awtrix.sync(apps)
            self.last_push_ok = True
        except Exception as exc:
            log.warning("Envoi vers l'horloge échoué : %s", exc)
            self.last_push_ok = False

    # -------------------------------------------------------------------- état

    def snapshot(self) -> dict:
        """État complet sérialisable, consommé par le dashboard."""
        now = datetime.now(PARIS)
        with self.lock:
            return {
                "now": now.isoformat(timespec="seconds"),
                "source": self.realtime.last_source,
                "last_departures_at": (
                    self.last_departures_at.isoformat(timespec="seconds")
                    if self.last_departures_at
                    else None
                ),
                "last_velo_at": (
                    self.last_velo_at.isoformat(timespec="seconds") if self.last_velo_at else None
                ),
                "awtrix": {
                    "enabled": self.awtrix is not None,
                    "host": self.cfg.awtrix.host,
                    "last_push_ok": self.last_push_ok,
                },
                "pace_factor": self.calibration.pace_factor,
                "overhead_s": self.cfg.walk.overhead_s,
                "home": asdict(self.cfg.home),
                "stations": [
                    {
                        "name": s.name,
                        "modes": s.mode_label,
                        "crow_m": round(s.distance_m),
                        "route_m": round(s.route_walk_m),
                        "walk_s": s.walk_s,
                        "access_s": s.access_s,
                        "lead_s": s.lead_s(self.cfg.walk.overhead_s),
                        "engine": s.engine,
                        "walk_source": s.walk_source,
                        "access_source": s.access_source,
                        "quays": len(s.quays),
                    }
                    for s in self.stations
                ],
                "boards": [
                    {
                        **render.board_screen(board, now),
                        "terminus": board.terminus,
                        "station": board.station,
                        "walk_s": board.walk_s,
                        "access_s": board.access_s,
                        "lead_budget_s": board.lead_s,
                        "next": [
                            {
                                "at": d.when.strftime("%H:%M"),
                                "in_s": d.seconds_from(now),
                                "realtime": d.realtime,
                            }
                            for d in board.departures[:4]
                        ],
                    }
                    for board in self.boards
                ],
                "velo": [
                    {
                        **render.velo_screen(s),
                        "walk_s": s.walk_s,
                        "capacity": s.capacity,
                        "renting": s.renting,
                        "returning": s.returning,
                    }
                    for s in self.velo_stations
                ],
                "disruptions": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "critical": d.critical,
                        "lines": d.lines,
                        "content": d.content[:400],
                    }
                    for d in self.disruptions
                ],
            }
