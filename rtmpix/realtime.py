"""Récupération des prochains passages, avec repli en cascade.

Trois sources, de la meilleure à la plus dégradée :

1. `rbgl`  — api-mobilite.rbgl.fr, qui fusionne le temps réel SPOTI et le théorique GTFS
             et renvoie du JSON propre avec couleurs de ligne. Source par défaut.
2. `spoti` — api.rtm.fr, le système qui alimente les écrans de quai. C'est la source
             d'origine du point 1, mais en XML et à la minute près.
3. `gtfs`  — les horaires théoriques compilés en local. Fonctionne sans réseau, et ne
             sait évidemment rien des rames supprimées.

Le champ `realtime` de chaque départ dit si c'est une mesure terrain ou du théorique :
c'est lui qui permet d'afficher « le réel a décroché » plutôt que de mentir.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from .gtfs import date_to_int

log = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
SPOTI_NS = "{http://ws/webbus/org/}"


@dataclass
class Departure:
    station: str
    line: str
    terminus: str
    when: datetime
    realtime: bool
    color: str | None = None

    def seconds_from(self, now: datetime) -> int:
        return int((self.when - now).total_seconds())


class RealtimeError(Exception):
    pass


MAX_PARALLEL = 4


def _gather(tasks, worker, source: str) -> list[Departure]:
    """Interroge les quais en parallèle, en tolérant les échecs isolés.

    Un quai qui ne répond pas ne doit pas priver l'écran des autres lignes. En revanche,
    si *tous* échouent, c'est la source entière qui est morte : on lève, et l'appelant
    bascule sur la suivante.
    """
    if not tasks:
        return []

    out: list[Departure] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(tasks))) as pool:
        for result in pool.map(lambda t: _safe(worker, t), tasks):
            departures, error = result
            if error:
                failures.append(error)
            else:
                out.extend(departures)

    if len(failures) == len(tasks):
        raise RealtimeError(f"{source}: {failures[0]}")
    if failures:
        log.debug("%s : %d quai(s) muet(s) sur %d", source, len(failures), len(tasks))
    return out


def _safe(worker, task) -> tuple[list[Departure], str | None]:
    try:
        return worker(task), None
    except Exception as exc:
        return [], str(exc)


class Provider:
    name = "?"

    def fetch(self, stations) -> list[Departure]:
        raise NotImplementedError


class RbglProvider(Provider):
    """api-mobilite.rbgl.fr — JSON, temps réel + théorique fusionnés."""

    name = "rbgl"

    def __init__(self, cfg):
        self.base = cfg.sources.rbgl_base.rstrip("/")
        self.timeout = cfg.sources.timeout_s
        self.headers = {"User-Agent": cfg.sources.user_agent}

    def fetch(self, stations) -> list[Departure]:
        tasks = [(station, netex) for station in stations for netex in station.netex_ids]
        return _gather(tasks, self._one, "rbgl")

    def _one(self, task) -> list[Departure]:
        station, netex = task
        resp = requests.get(
            f"{self.base}/RTM/getStopMonitoring",
            params={"ext_netex_id": netex},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()

        out = []
        for dep in payload.get("departures") or []:
            expected = dep.get("ExpectedDepartureTime")
            stamp = expected or dep.get("AimedDepartureTime")
            if not stamp:
                continue
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=PARIS)
            out.append(
                Departure(
                    station=station.name,
                    line=(dep.get("line") or "").strip(),
                    terminus=(dep.get("terminus") or dep.get("trip_headsign") or "").strip(),
                    when=when,
                    realtime=expected is not None,
                    color=(dep.get("color") or "").strip() or None,
                )
            )
        return out


class SpotiProvider(Provider):
    """api.rtm.fr — le SPOTI brut, en XML, à la minute."""

    name = "spoti"

    def __init__(self, cfg, colors: dict[str, str] | None = None):
        self.url = cfg.sources.spoti_url
        self.timeout = cfg.sources.timeout_s
        self.headers = {"User-Agent": cfg.sources.user_agent}
        self.colors = colors or {}

    def fetch(self, stations) -> list[Departure]:
        tasks = [(s, q) for s in stations for q in s.quays if q.spoti]
        return _gather(tasks, self._one, "spoti")

    def _one(self, task) -> list[Departure]:
        station, quay = task
        now = datetime.now(PARIS)
        resp = requests.get(
            self.url,
            params={"nomPtReseau": quay.spoti},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        tree = ElementTree.fromstring(resp.content)

        out = []
        for passage in tree.findall(f"{SPOTI_NS}passage"):
            line = passage.findtext(f"{SPOTI_NS}nomLigneCial", "").strip()
            hhmm = passage.findtext(f"{SPOTI_NS}heurePassageReel", "").strip()
            when = _hhmm_to_datetime(hhmm, now)
            if when is None:
                continue
            out.append(
                Departure(
                    station=station.name,
                    line=line,
                    terminus=passage.findtext(f"{SPOTI_NS}destination", "").strip(),
                    when=when,
                    realtime=passage.findtext(f"{SPOTI_NS}passageReel", "false") == "true",
                    color=self.colors.get(line),
                )
            )
        return out


class GtfsProvider(Provider):
    """Horaires théoriques locaux. Le filet de sécurité quand tout le reste tombe."""

    name = "gtfs"

    def __init__(self, conn: sqlite3.Connection, horizon_min: int = 90):
        self.conn = conn
        self.horizon_s = horizon_min * 60

    def fetch(self, stations) -> list[Departure]:
        now = datetime.now(PARIS)
        out: list[Departure] = []
        stop_ids = {q.stop_id: st for st in stations for q in st.quays}
        if not stop_ids:
            return out

        # Une course partie à 25:10 hier est toujours en service à 01:10 aujourd'hui :
        # il faut donc interroger la veille comme le jour courant.
        for day_offset in (0, -1):
            day = (now + timedelta(days=day_offset)).date()
            services = active_services(self.conn, day)
            if not services:
                continue
            midnight = datetime(day.year, day.month, day.day, tzinfo=PARIS)
            from_s = int((now - midnight).total_seconds())
            if from_s < 0:
                continue
            to_s = from_s + self.horizon_s

            placeholders_stops = ",".join("?" * len(stop_ids))
            placeholders_svc = ",".join("?" * len(services))
            rows = self.conn.execute(
                f"""
                SELECT st.stop_id, st.departure_s, r.short_name, r.color, t.headsign
                FROM stop_times st
                JOIN trips t  ON t.trip_id = st.trip_id
                JOIN routes r ON r.route_id = t.route_id
                WHERE st.stop_id IN ({placeholders_stops})
                  AND st.departure_s BETWEEN ? AND ?
                  AND t.service_id IN ({placeholders_svc})
                  AND st.seq < t.last_seq
                ORDER BY st.departure_s
                LIMIT 200
                """,
                (*stop_ids.keys(), from_s, to_s, *services),
            ).fetchall()

            for row in rows:
                station = stop_ids[row["stop_id"]]
                out.append(
                    Departure(
                        station=station.name,
                        line=(row["short_name"] or "").strip(),
                        terminus=(row["headsign"] or "").strip(),
                        when=midnight + timedelta(seconds=row["departure_s"]),
                        realtime=False,
                        color=row["color"],
                    )
                )
        return out


def active_services(conn: sqlite3.Connection, day) -> list[str]:
    """service_id circulant à une date donnée (calendar, corrigé par calendar_dates)."""
    day_int = date_to_int(day)
    weekday_bit = 1 << day.weekday()  # weekday() : lundi = 0, comme notre masque
    services = {
        row[0]
        for row in conn.execute(
            "SELECT service_id FROM calendar "
            "WHERE start_date <= ? AND end_date >= ? AND (days & ?) != 0",
            (day_int, day_int, weekday_bit),
        )
    }
    for service_id, exception_type in conn.execute(
        "SELECT service_id, exception_type FROM calendar_dates WHERE date = ?", (day_int,)
    ):
        if exception_type == 1:
            services.add(service_id)
        elif exception_type == 2:
            services.discard(service_id)
    return sorted(services)


def _hhmm_to_datetime(hhmm: str, now: datetime) -> datetime | None:
    """'00:12' juste après minuit désigne demain, pas ce matin."""
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when < now - timedelta(minutes=5):
        when += timedelta(days=1)
    return when


def route_colors(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["short_name"]: row["color"]
        for row in conn.execute(
            "SELECT short_name, color FROM routes WHERE short_name IS NOT NULL"
        )
        if row["color"]
    }


class RealtimeService:
    """Essaie les sources dans l'ordre et retient celle qui a répondu."""

    def __init__(self, cfg, conn: sqlite3.Connection):
        colors = route_colors(conn)
        available = {
            "rbgl": lambda: RbglProvider(cfg),
            "spoti": lambda: SpotiProvider(cfg, colors),
            "gtfs": lambda: GtfsProvider(conn, cfg.transit.horizon_min),
        }
        order = [cfg.sources.realtime] + [k for k in ("rbgl", "spoti", "gtfs") if k != cfg.sources.realtime]
        self.providers = [available[name]() for name in order]
        self.last_source: str = "?"

    def fetch(self, stations: Iterable) -> list[Departure]:
        stations = list(stations)
        for provider in self.providers:
            try:
                departures = provider.fetch(stations)
            except RealtimeError as exc:
                log.warning("Source %s indisponible (%s), repli.", provider.name, exc)
                continue
            except Exception as exc:  # une source tierce peut renvoyer n'importe quoi
                log.warning("Source %s en erreur inattendue (%s), repli.", provider.name, exc)
                continue
            if departures:
                if self.last_source != provider.name:
                    log.info("Source des passages : %s", provider.name)
                self.last_source = provider.name
                return departures
            log.debug("Source %s n'a rien renvoyé, repli.", provider.name)
        self.last_source = "aucune"
        return []
