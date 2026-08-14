"""Cœur du service : rassemble les sources, calcule les écrans, pousse vers l'horloge.

Un seul objet `Service` détient l'état ; la boucle principale et le dashboard web y
accèdent tous les deux, sous verrou. L'horloge, elle, ne fait qu'afficher.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import gtfs, planner, render, stations as stations_mod
from .awtrix import Awtrix
from .calibration import Calibration
from .departures import build_boards
from .disruptions import DisruptionClient, relevant
from .realtime import PARIS, RealtimeService
from .routing import WalkRouter
from .schedule import Course, ScheduleClient
from .velo import VeloClient

log = logging.getLogger(__name__)


@dataclass
class JourneyState:
    """Une destination, ses itinéraires possibles, et le prochain rendez-vous à tenir."""

    destination: object
    patterns: list = field(default_factory=list)
    schedule: ScheduleClient | None = None
    course: Course | None = None
    plans: list = field(default_factory=list)

    @property
    def best(self):
        """L'itinéraire qui laisse partir le plus tard — la réponse à « j'ai jusqu'à quand ? »."""
        return self.plans[0] if self.plans else None


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
        self.journeys: list[JourneyState] = []

        self.reload_stations()
        self.setup_journeys()

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

    def set_transfer(self, station_name: str, seconds: int | None) -> None:
        """Temps de correspondance réel à une station (None revient au calcul automatique)."""
        with self.lock:
            if seconds is None:
                self.calibration.transfer.pop(station_name, None)
            else:
                self.calibration.transfer[station_name] = max(0, int(seconds))
            self.calibration.save(self.cfg.calibration_path)
            self.setup_journeys()

    # ----------------------------------------------------------------- trajets

    def setup_journeys(self) -> None:
        """Découvre les itinéraires vers chaque destination. Coûteux : fait au démarrage."""
        if not self.cfg.journeys.enabled:
            self.journeys = []
            return

        origin = {"lat": self.cfg.home.lat, "lon": self.cfg.home.lon}
        found: list[JourneyState] = []
        for destination in self.cfg.journeys.destinations:
            log.info("Itinéraires vers %s :", destination.name)
            patterns = planner.discover(
                self.conn,
                self.cfg,
                self.router,
                origin,
                {"lat": destination.lat, "lon": destination.lon, "radius_m": destination.radius_m},
                self.calibration,
            )
            schedule = None
            if destination.calendar:
                cache = self.cfg.gtfs.data_dir / f"ical-{render.slug(destination.name, 12)}.ics"
                schedule = ScheduleClient(
                    destination.calendar, cache,
                    timeout_s=self.cfg.sources.timeout_s,
                    user_agent=self.cfg.sources.user_agent,
                )
                schedule.refresh()
            found.append(JourneyState(destination=destination, patterns=patterns, schedule=schedule))

        with self.lock:
            self.journeys = found

    def refresh_schedules(self) -> None:
        for journey in self.journeys:
            if journey.schedule is not None:
                journey.schedule.refresh()

    def refresh_journeys(self) -> None:
        """Recalcule, pour chaque destination, la dernière minute possible pour partir."""
        if not self.journeys:
            return
        now = datetime.now(PARIS)
        margin = timedelta(seconds=self.cfg.journeys.arrive_margin_s)

        for journey in self.journeys:
            course = (
                journey.schedule.next_course(now, journey.destination.location_filter)
                if journey.schedule
                else None
            )
            plans = []
            if course is not None:
                arrive_by = course.start - margin
                for pattern in journey.patterns:
                    plan = planner.latest_departure(
                        self.conn, pattern, arrive_by, self.cfg.walk.overhead_s
                    )
                    if plan is not None:
                        plans.append(plan)
                # Le meilleur itinéraire est celui qui autorise le départ le plus tardif.
                # À départ égal, on départage comme le ferait un humain : le moins de
                # marche d'abord, l'arrivée la plus tôt ensuite.
                plans.sort(
                    key=lambda p: (
                        -p.leave_at.timestamp(),
                        p.pattern.walk_in_s + p.pattern.walk_out_s,
                        p.arrive_at.timestamp(),
                    )
                )
            with self.lock:
                journey.course = course
                journey.plans = plans

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
            # L'échéance passe en tête : c'est l'information la plus contraignante.
            for journey in self.journeys:
                built = render.deadline_app(journey, now, self.cfg.journeys.show_window_min)
                if built is not None:
                    apps[built[0]] = {**built[1], "pos": 0}
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
                "journeys": [self._journey_snapshot(j, now) for j in self.journeys],
            }

    def _journey_snapshot(self, journey: JourneyState, now: datetime) -> dict:
        screen = render.deadline_screen(journey, now)
        return {
            "name": journey.destination.name,
            "has_calendar": journey.schedule is not None,
            "course": (
                {
                    "summary": journey.course.summary,
                    "short": journey.course.short,
                    "start": journey.course.start.strftime("%a %d/%m %H:%M"),
                    "start_h": render.format_hour(journey.course.start),
                    "location": journey.course.location,
                }
                if journey.course
                else None
            ),
            "upcoming": (
                [
                    {
                        "summary": c.summary,
                        "start": c.start.strftime("%a %d/%m %H:%M"),
                        "location": c.location,
                    }
                    for c in journey.schedule.upcoming(4, now)
                ]
                if journey.schedule
                else []
            ),
            "deadline": screen,
            "options": [
                {
                    "label": plan.pattern.label,
                    "describe": plan.pattern.describe(),
                    "leave_at": plan.leave_at.strftime("%H:%M"),
                    "leave_in_s": int((plan.leave_at - now).total_seconds()),
                    "board_at": plan.board_at.strftime("%H:%M"),
                    "arrive_at": plan.arrive_at.strftime("%H:%M"),
                    "walk_in_s": plan.pattern.walk_in_s,
                    "walk_out_s": plan.pattern.walk_out_s,
                    "transfers_s": plan.pattern.transfers_s,
                    "legs": [
                        {
                            "line": leg.line,
                            "color": leg.color,
                            "from": leg.from_name,
                            "to": leg.to_name,
                            "dep": timed[0].strftime("%H:%M"),
                            "arr": timed[1].strftime("%H:%M"),
                        }
                        for leg, timed in zip(plan.pattern.legs, plan.legs)
                    ],
                }
                for plan in journey.plans
            ],
            "patterns": [
                {"label": p.label, "describe": p.describe(), "total_s": p.total_s}
                for p in journey.patterns
            ],
        }
