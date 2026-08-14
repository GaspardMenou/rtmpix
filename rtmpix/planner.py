"""Itinéraires avec correspondance, et heure limite de départ.

Deux temps, parce qu'ils n'ont pas le même coût :

1. **Découverte** (une fois, au démarrage) — quelles suites de lignes relient le domicile à
   la destination, avec au plus une correspondance. On travaille sur `route_stops`, la
   séquence d'arrêts de référence de chaque ligne : quelques milliers de lignes de table,
   pas les 1,3 M d'horaires.

2. **Calcul** (à chaque tour) — pour un itinéraire donné, la dernière minute possible pour
   partir sans être en retard. Le calcul se fait **à rebours** depuis l'heure du cours :
   dernier bus qui arrive à temps, donc dernier métro qui permet de l'attraper, donc
   dernière minute pour sortir de chez soi. C'est la question réellement posée.

Une correspondance ne se détecte pas par le nom : à La Rose, le quai du métro s'appelle
« La Rose » et l'arrêt de bus « Métro La Rose », et ils sont distants de 3 à 500 m selon le
quai. On la détecte donc géométriquement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .geo import haversine_m, walk_seconds
from .realtime import PARIS, active_services

log = logging.getLogger(__name__)


@dataclass
class Leg:
    """Un tronçon en véhicule : monter à un arrêt, descendre à un autre, sur une ligne."""

    route_id: str
    line: str
    direction_id: int
    from_stop: str
    from_name: str
    to_stop: str
    to_name: str
    color: str | None = None
    headsign: str = ""
    typical_s: int = 0      # temps de parcours médian
    daily_runs: int = 0     # nombre de courses, pour départager les itinéraires


@dataclass
class Pattern:
    """Un itinéraire complet : marche, tronçons, correspondances, marche."""

    legs: list[Leg]
    walk_in_s: int
    walk_out_s: int
    transfers_s: list[int] = field(default_factory=list)

    @property
    def label(self) -> str:
        return " › ".join(leg.line for leg in self.legs)

    @property
    def ride_s(self) -> int:
        return sum(leg.typical_s for leg in self.legs) + sum(self.transfers_s)

    @property
    def total_s(self) -> int:
        return self.walk_in_s + self.ride_s + self.walk_out_s

    def describe(self) -> str:
        parts = [f"{self.walk_in_s // 60}′ à pied"]
        for i, leg in enumerate(self.legs):
            parts.append(f"{leg.line} {leg.from_name} → {leg.to_name}")
            if i < len(self.transfers_s):
                parts.append(f"corresp. {self.transfers_s[i] // 60}′")
        parts.append(f"{self.walk_out_s // 60}′ à pied")
        return " · ".join(parts)


@dataclass
class Plan:
    """Un itinéraire daté : quand partir, quand arriver."""

    pattern: Pattern
    leave_at: datetime          # sortir de chez soi
    board_at: datetime          # départ du premier véhicule
    arrive_at: datetime         # arrivée à destination, à pied compris
    legs: list[tuple[datetime, datetime]]   # (départ, arrivée) de chaque tronçon
    feasible: bool = True


def _load_stops(db) -> dict[str, tuple[str, float, float]]:
    return {
        row["stop_id"]: (row["name"], row["lat"], row["lon"])
        for row in db.execute("SELECT stop_id, name, lat, lon FROM stops")
    }


def _stops_within(stops, lat: float, lon: float, radius_m: int) -> list[tuple[str, float]]:
    out = []
    for stop_id, (_, slat, slon) in stops.items():
        distance = haversine_m(lat, lon, slat, slon)
        if distance <= radius_m:
            out.append((stop_id, distance))
    out.sort(key=lambda x: x[1])
    return out


def _leg_stats(db, route_id: str, direction_id: int, from_stop: str, to_stop: str) -> tuple[int, int]:
    """Temps de parcours médian et nombre de courses, pour départager les itinéraires."""
    rows = db.execute(
        """
        SELECT s2.arrival_s - s1.departure_s AS d
        FROM stop_times s1
        JOIN stop_times s2 ON s2.trip_id = s1.trip_id AND s2.seq > s1.seq
        JOIN trips t ON t.trip_id = s1.trip_id
        WHERE s1.stop_id = ? AND s2.stop_id = ? AND t.route_id = ? AND t.direction_id = ?
        """,
        (from_stop, to_stop, route_id, direction_id),
    ).fetchall()
    durations = sorted(r["d"] for r in rows if r["d"] and r["d"] > 0)
    if not durations:
        return 0, 0
    return durations[len(durations) // 2], len(durations)


def discover(db, cfg, router, origin, destination, calibration) -> list[Pattern]:
    """Itinéraires domicile → destination, directs ou avec une correspondance."""
    stops = _load_stops(db)

    origins = _stops_within(stops, origin["lat"], origin["lon"], cfg.transit.radius_m)
    dests = _stops_within(
        stops,
        destination["lat"],
        destination["lon"],
        destination.get("radius_m") or cfg.journeys.destination_radius_m,
    )
    if not origins or not dests:
        log.warning("Aucun arrêt autour du domicile ou de la destination.")
        return []

    # On plafonne le nombre d'arrêts candidats : au-delà, on énumère des itinéraires que
    # personne n'emprunterait, et chacun coûte des requêtes de routage.
    origins = origins[: cfg.journeys.max_origin_stops]
    dests = dests[: cfg.journeys.max_dest_stops]
    origin_ids = {s for s, _ in origins}
    dest_ids = {s for s, _ in dests}

    # Estimation à vol d'oiseau pour classer les itinéraires : le routeur ne sera sollicité
    # que sur les quelques survivants, à la toute fin.
    def walk_to(stop_id: str, from_lat, from_lon) -> int:
        _, slat, slon = stops[stop_id]
        return walk_seconds(
            haversine_m(from_lat, from_lon, slat, slon), cfg.walk.speed_mps, cfg.walk.detour_factor
        )

    def walk_from(stop_id: str, to_lat, to_lon) -> int:
        _, slat, slon = stops[stop_id]
        return walk_seconds(
            haversine_m(slat, slon, to_lat, to_lon), cfg.walk.speed_mps, cfg.walk.detour_factor
        )

    patterns: list[Pattern] = []

    # ------------------------------------------------------------------ directs
    placeholders_o = ",".join("?" * len(origin_ids))
    placeholders_d = ",".join("?" * len(dest_ids))
    direct = db.execute(
        f"""
        SELECT a.route_id, a.direction_id, a.stop_id AS o, b.stop_id AS d,
               r.short_name, r.color
        FROM route_stops a
        JOIN route_stops b
          ON b.route_id = a.route_id AND b.direction_id = a.direction_id AND b.seq > a.seq
        JOIN routes r ON r.route_id = a.route_id
        WHERE a.stop_id IN ({placeholders_o}) AND b.stop_id IN ({placeholders_d})
        """,
        (*origin_ids, *dest_ids),
    ).fetchall()

    for row in direct:
        typical, runs = _leg_stats(db, row["route_id"], row["direction_id"], row["o"], row["d"])
        if not runs:
            continue
        leg = Leg(
            route_id=row["route_id"], line=row["short_name"] or "?",
            direction_id=row["direction_id"],
            from_stop=row["o"], from_name=stops[row["o"]][0],
            to_stop=row["d"], to_name=stops[row["d"]][0],
            color=row["color"], typical_s=typical, daily_runs=runs,
        )
        patterns.append(
            Pattern(
                legs=[leg],
                walk_in_s=walk_to(row["o"], origin["lat"], origin["lon"]),
                walk_out_s=walk_from(row["d"], destination["lat"], destination["lon"]),
            )
        )

    # --------------------------------------------------- une correspondance
    # Tout ce qu'on peut atteindre depuis chez soi sans changer.
    reachable = db.execute(
        f"""
        SELECT DISTINCT a.route_id, a.direction_id, a.stop_id AS o, b.stop_id AS x, b.seq
        FROM route_stops a
        JOIN route_stops b
          ON b.route_id = a.route_id AND b.direction_id = a.direction_id AND b.seq > a.seq
        WHERE a.stop_id IN ({placeholders_o})
        """,
        tuple(origin_ids),
    ).fetchall()

    # Tout ce qui mène à destination sans changer.
    feeding = db.execute(
        f"""
        SELECT DISTINCT a.route_id, a.direction_id, a.stop_id AS y, b.stop_id AS d, a.seq
        FROM route_stops a
        JOIN route_stops b
          ON b.route_id = a.route_id AND b.direction_id = a.direction_id AND b.seq > a.seq
        WHERE b.stop_id IN ({placeholders_d})
        """,
        tuple(dest_ids),
    ).fetchall()

    # Appariement géométrique des arrêts de correspondance.
    radius = cfg.journeys.transfer_radius_m
    feed_by_stop: dict[str, list] = {}
    for row in feeding:
        feed_by_stop.setdefault(row["y"], []).append(row)

    seen: set[tuple] = set()
    for first in reachable:
        x_name, xlat, xlon = stops[first["x"]]
        for y_stop, rows in feed_by_stop.items():
            if y_stop == first["x"]:
                distance = 0.0
            else:
                _, ylat, ylon = stops[y_stop]
                distance = haversine_m(xlat, xlon, ylat, ylon)
                if distance > radius:
                    continue
            for second in rows:
                if second["route_id"] == first["route_id"]:
                    continue  # changer pour reprendre la même ligne n'a pas de sens
                # `y` (l'arrêt où l'on reprend) doit faire partie de la clé : sans lui, le
                # premier arrêt de reprise rencontré masquait tous les autres, y compris
                # celui juste en face de la sortie du métro.
                key = (first["route_id"], first["direction_id"], first["o"], first["x"],
                       second["route_id"], second["direction_id"], y_stop, second["d"])
                if key in seen:
                    continue
                seen.add(key)

                t1, runs1 = _leg_stats(db, first["route_id"], first["direction_id"],
                                       first["o"], first["x"])
                t2, runs2 = _leg_stats(db, second["route_id"], second["direction_id"],
                                       y_stop, second["d"])
                if not runs1 or not runs2:
                    continue

                r1 = db.execute("SELECT short_name, color FROM routes WHERE route_id = ?",
                                (first["route_id"],)).fetchone()
                r2 = db.execute("SELECT short_name, color FROM routes WHERE route_id = ?",
                                (second["route_id"],)).fetchone()

                transfer_walk = walk_seconds(distance, cfg.walk.speed_mps, cfg.walk.detour_factor)
                transfer = max(cfg.journeys.min_transfer_s, transfer_walk)
                station_name = stops[first["x"]][0]
                override = calibration.transfer.get(station_name)
                if override is not None:
                    transfer = int(override)

                patterns.append(
                    Pattern(
                        legs=[
                            Leg(first["route_id"], r1["short_name"] or "?", first["direction_id"],
                                first["o"], stops[first["o"]][0], first["x"], x_name,
                                r1["color"], typical_s=t1, daily_runs=runs1),
                            Leg(second["route_id"], r2["short_name"] or "?", second["direction_id"],
                                y_stop, stops[y_stop][0], second["d"], stops[second["d"]][0],
                                r2["color"], typical_s=t2, daily_runs=runs2),
                        ],
                        walk_in_s=walk_to(first["o"], origin["lat"], origin["lon"]),
                        walk_out_s=walk_from(second["d"], destination["lat"], destination["lon"]),
                        transfers_s=[transfer],
                    )
                )

    # Beaucoup d'itinéraires se valent ou sont franchement mauvais. On classe sur le temps
    # total en incluant l'attente moyenne : une ligne deux fois plus fréquente fait gagner
    # la moitié de son intervalle.
    def score(p: Pattern) -> float:
        wait = sum(_expected_wait_s(leg) for leg in p.legs)
        return p.total_s + wait

    patterns.sort(key=score)
    kept = _dedupe(patterns, cfg.journeys.max_options)

    # Seulement maintenant : la marche réelle par les rues, pour les itinéraires retenus.
    for p in kept:
        first, last = p.legs[0].from_stop, p.legs[-1].to_stop
        _, olat, olon = stops[first]
        _, dlat, dlon = stops[last]
        leg_in = router.leg(origin["lat"], origin["lon"], olat, olon)
        leg_out = router.leg(dlat, dlon, destination["lat"], destination["lon"])
        p.walk_in_s = int(round(leg_in.duration_s * calibration.pace_factor))
        p.walk_out_s = int(round(leg_out.duration_s * calibration.pace_factor))
    router.save()

    for p in kept:
        log.info("  itinéraire %-10s %s (≈ %d′)", p.label, p.describe(), round(score(p) / 60))
    return kept


def _expected_wait_s(leg: Leg) -> int:
    """Attente moyenne : la moitié de l'intervalle, estimé sur une amplitude de 18 h."""
    if leg.daily_runs <= 0:
        return 3600
    # daily_runs couvre toute la période de validité du GTFS ; on ramène à une journée.
    per_day = max(1.0, leg.daily_runs / 7.0)
    headway = (18 * 3600) / per_day
    return int(min(headway / 2, 1800))


def _dedupe(patterns: list[Pattern], limit: int) -> list[Pattern]:
    """Un seul itinéraire par combinaison de lignes : le meilleur."""
    out: list[Pattern] = []
    seen: set[str] = set()
    for p in patterns:
        if p.label in seen:
            continue
        seen.add(p.label)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def _service_days(db, target: datetime) -> list[tuple[date, datetime]]:
    """Jours de service à considérer, avec leur minuit de référence.

    Une course partie à 25:10 la veille circule encore à 01:10 : les deux jours comptent.
    """
    out = []
    for offset in (0, -1):
        day = (target + timedelta(days=offset)).date()
        midnight = datetime(day.year, day.month, day.day, tzinfo=PARIS)
        out.append((day, midnight))
    return out


def _last_arrival_before(db, leg: Leg, limit: datetime) -> tuple[datetime, datetime] | None:
    """Dernière course de ce tronçon arrivant au plus tard à `limit`. (départ, arrivée)."""
    best = None
    for day, midnight in _service_days(db, limit):
        services = active_services(db, day)
        if not services:
            continue
        limit_s = int((limit - midnight).total_seconds())
        if limit_s < 0:
            continue
        placeholders = ",".join("?" * len(services))
        row = db.execute(
            f"""
            SELECT s1.departure_s AS dep, s2.arrival_s AS arr
            FROM stop_times s1
            JOIN stop_times s2 ON s2.trip_id = s1.trip_id AND s2.seq > s1.seq
            JOIN trips t ON t.trip_id = s1.trip_id
            WHERE s1.stop_id = ? AND s2.stop_id = ?
              AND t.route_id = ? AND t.direction_id = ?
              AND t.service_id IN ({placeholders})
              AND s2.arrival_s <= ?
            ORDER BY s2.arrival_s DESC
            LIMIT 1
            """,
            (leg.from_stop, leg.to_stop, leg.route_id, leg.direction_id, *services, limit_s),
        ).fetchone()
        if row is None:
            continue
        candidate = (midnight + timedelta(seconds=row["dep"]), midnight + timedelta(seconds=row["arr"]))
        if best is None or candidate[1] > best[1]:
            best = candidate
    return best


def _first_departure_after(db, leg: Leg, earliest: datetime) -> tuple[datetime, datetime] | None:
    """Première course de ce tronçon partant à `earliest` ou après."""
    best = None
    for day, midnight in _service_days(db, earliest):
        services = active_services(db, day)
        if not services:
            continue
        from_s = int((earliest - midnight).total_seconds())
        placeholders = ",".join("?" * len(services))
        row = db.execute(
            f"""
            SELECT s1.departure_s AS dep, s2.arrival_s AS arr
            FROM stop_times s1
            JOIN stop_times s2 ON s2.trip_id = s1.trip_id AND s2.seq > s1.seq
            JOIN trips t ON t.trip_id = s1.trip_id
            WHERE s1.stop_id = ? AND s2.stop_id = ?
              AND t.route_id = ? AND t.direction_id = ?
              AND t.service_id IN ({placeholders})
              AND s1.departure_s >= ?
            ORDER BY s1.departure_s ASC
            LIMIT 1
            """,
            (leg.from_stop, leg.to_stop, leg.route_id, leg.direction_id, *services, from_s),
        ).fetchone()
        if row is None:
            continue
        candidate = (midnight + timedelta(seconds=row["dep"]), midnight + timedelta(seconds=row["arr"]))
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def latest_departure(db, pattern: Pattern, arrive_by: datetime, overhead_s: int) -> Plan | None:
    """La dernière minute pour sortir de chez soi sans arriver en retard.

    Calcul à rebours : on part de l'heure d'arrivée voulue, on retire la marche finale,
    on cherche la dernière course qui arrive à temps, on remonte de correspondance en
    correspondance jusqu'à la porte de l'appartement.
    """
    cursor = arrive_by - timedelta(seconds=pattern.walk_out_s)
    timed: list[tuple[datetime, datetime]] = []

    for index in range(len(pattern.legs) - 1, -1, -1):
        leg = pattern.legs[index]
        found = _last_arrival_before(db, leg, cursor)
        if found is None:
            return None
        timed.insert(0, found)
        cursor = found[0]
        if index > 0:
            cursor -= timedelta(seconds=pattern.transfers_s[index - 1])

    board_at = timed[0][0]
    leave_at = board_at - timedelta(seconds=pattern.walk_in_s + overhead_s)
    arrive_at = timed[-1][1] + timedelta(seconds=pattern.walk_out_s)
    return Plan(pattern, leave_at, board_at, arrive_at, timed)


def earliest_arrival(db, pattern: Pattern, leave_at: datetime, overhead_s: int) -> Plan | None:
    """En partant à `leave_at`, à quelle heure on arrive au plus tôt."""
    cursor = leave_at + timedelta(seconds=overhead_s + pattern.walk_in_s)
    timed: list[tuple[datetime, datetime]] = []

    for index, leg in enumerate(pattern.legs):
        found = _first_departure_after(db, leg, cursor)
        if found is None:
            return None
        timed.append(found)
        cursor = found[1]
        if index < len(pattern.transfers_s):
            cursor += timedelta(seconds=pattern.transfers_s[index])

    arrive_at = timed[-1][1] + timedelta(seconds=pattern.walk_out_s)
    return Plan(pattern, leave_at, timed[0][0], arrive_at, timed)
