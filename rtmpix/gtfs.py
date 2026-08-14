"""Téléchargement du GTFS RTM et compilation en base SQLite.

Le GTFS RTM pèse ~10 Mo compressé, dont 89 Mo de `stop_times.txt` (1,34 M de lignes).
On ne relit jamais ces CSV à chaud : on les compile une fois en SQLite indexée, en ne
gardant que les modes de transport demandés (métro/tram par défaut, ce qui écarte
l'essentiel du volume).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import sqlite3
import threading
import zipfile
from datetime import date, datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE stops (
    stop_id  TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    netex_id TEXT,              -- RTM:PNT:00002313, clé commune avec les API temps réel
    spoti    TEXT               -- 02313, les 5 derniers chiffres, pour l'API SPOTI directe
);
CREATE TABLE routes (
    route_id   TEXT PRIMARY KEY,
    short_name TEXT,
    long_name  TEXT,
    route_type INTEGER,
    color      TEXT
);
CREATE TABLE trips (
    trip_id      TEXT PRIMARY KEY,
    route_id     TEXT NOT NULL,
    service_id   TEXT NOT NULL,
    headsign     TEXT,
    direction_id INTEGER,
    last_seq     INTEGER
);
CREATE TABLE stop_times (
    trip_id     TEXT NOT NULL,
    stop_id     TEXT NOT NULL,
    departure_s INTEGER NOT NULL,
    arrival_s   INTEGER NOT NULL,   -- nécessaire dès qu'on enchaîne : on arrive avant de repartir
    seq         INTEGER NOT NULL
);
-- Séquence d'arrêts représentative de chaque ligne et sens, extraite de la course la plus
-- complète. Sert à découvrir les itinéraires possibles sans balayer les 1,3 M d'horaires.
CREATE TABLE route_stops (
    route_id     TEXT NOT NULL,
    direction_id INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    stop_id      TEXT NOT NULL,
    PRIMARY KEY (route_id, direction_id, seq)
);
CREATE TABLE calendar (
    service_id TEXT PRIMARY KEY,
    days       INTEGER NOT NULL,   -- masque de bits, lundi = bit 0
    start_date INTEGER NOT NULL,
    end_date   INTEGER NOT NULL
);
CREATE TABLE calendar_dates (
    service_id     TEXT NOT NULL,
    date           INTEGER NOT NULL,
    exception_type INTEGER NOT NULL
);
CREATE TABLE stop_modes (
    stop_id    TEXT NOT NULL,
    route_type INTEGER NOT NULL,
    PRIMARY KEY (stop_id, route_type)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Cet index doit exister AVANT les agrégations par course : sans lui, le calcul de
# `last_seq` dégénère en un scan complet par trip (97 s contre moins d'une seconde).
INDEXES_EARLY = """
CREATE INDEX idx_stop_times_trip ON stop_times (trip_id, seq);
"""

INDEXES = """
CREATE INDEX idx_stop_times_lookup ON stop_times (stop_id, departure_s);
CREATE INDEX idx_stop_times_arrival ON stop_times (stop_id, arrival_s);
CREATE INDEX idx_trips_service ON trips (service_id);
CREATE INDEX idx_trips_route ON trips (route_id, direction_id);
CREATE INDEX idx_caldates ON calendar_dates (date, service_id);
CREATE INDEX idx_stops_name ON stops (name);
CREATE INDEX idx_route_stops_stop ON route_stops (stop_id);
"""

DAY_COLUMNS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def parse_gtfs_time(value: str) -> int | None:
    """'25:03:00' -> 90180. Les horaires après minuit dépassent volontairement 24 h."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def date_to_int(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def download(url: str, dest: Path) -> tuple[bytes, str]:
    """Télécharge le zip et renvoie (contenu, sha256)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("Téléchargement du GTFS…")
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    digest = hashlib.sha256(resp.content).hexdigest()
    dest.write_bytes(resp.content)
    log.info("GTFS téléchargé : %.1f Mo (sha %s)", len(resp.content) / 1e6, digest[:12])
    return resp.content, digest


def _reader(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    raw = zf.read(name).decode("utf-8-sig")
    return csv.DictReader(io.StringIO(raw))


def build_db(zip_bytes: bytes, db_path: Path, route_types: list[int], digest: str) -> None:
    """Compile le zip GTFS en SQLite, filtré sur les modes demandés."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".sqlite.tmp")
    tmp_path.unlink(missing_ok=True)

    keep_types = set(route_types)
    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)
    # Base reconstruite de zéro à chaque fois : la durabilité n'a aucun intérêt ici.
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        keep_routes: set[str] = set()
        rows = []
        for r in _reader(zf, "routes.txt"):
            rtype = int(r["route_type"] or -1)
            if rtype not in keep_types:
                continue
            keep_routes.add(r["route_id"])
            rows.append(
                (r["route_id"], r.get("route_short_name"), r.get("route_long_name"),
                 rtype, (r.get("route_color") or "").strip() or None)
            )
        conn.executemany("INSERT INTO routes VALUES (?,?,?,?,?)", rows)
        log.info("routes retenues : %d", len(keep_routes))

        keep_trips: set[str] = set()
        rows = []
        for t in _reader(zf, "trips.txt"):
            if t["route_id"] not in keep_routes:
                continue
            keep_trips.add(t["trip_id"])
            direction = t.get("direction_id") or "0"
            rows.append(
                (t["trip_id"], t["route_id"], t["service_id"],
                 (t.get("trip_headsign") or "").strip(), int(direction))
            )
        conn.executemany("INSERT INTO trips VALUES (?,?,?,?,?,NULL)", rows)
        log.info("trips retenus : %d", len(keep_trips))

        rows = []
        used_stops: set[str] = set()
        inserted = 0
        for st in _reader(zf, "stop_times.txt"):
            if st["trip_id"] not in keep_trips:
                continue
            dep = parse_gtfs_time(st.get("departure_time") or st.get("arrival_time") or "")
            if dep is None:
                continue  # arrêt sans horaire précis : inexploitable pour un compte à rebours
            arr = parse_gtfs_time(st.get("arrival_time") or "")
            used_stops.add(st["stop_id"])
            rows.append((st["trip_id"], st["stop_id"], dep, arr if arr is not None else dep,
                         int(st["stop_sequence"])))
            if len(rows) >= 50_000:
                conn.executemany("INSERT INTO stop_times VALUES (?,?,?,?,?)", rows)
                inserted += len(rows)
                rows.clear()
        if rows:
            conn.executemany("INSERT INTO stop_times VALUES (?,?,?,?,?)", rows)
            inserted += len(rows)
        log.info("stop_times retenus : %d", inserted)
        conn.executescript(INDEXES_EARLY)

        # Dernier arrêt de chaque course : on n'y « part » pas, on y descend.
        conn.execute(
            "UPDATE trips SET last_seq = ("
            "  SELECT MAX(seq) FROM stop_times st WHERE st.trip_id = trips.trip_id)"
        )
        # Modes desservis par arrêt : détermine le temps d'accès entrée -> quai par défaut.
        conn.execute(
            "INSERT OR IGNORE INTO stop_modes "
            "SELECT DISTINCT st.stop_id, r.route_type FROM stop_times st "
            "JOIN trips t ON t.trip_id = st.trip_id "
            "JOIN routes r ON r.route_id = t.route_id"
        )

        # Itinéraire de référence par ligne et sens : la course la plus complète. Les
        # courses partielles (terminus avancé, services scolaires) en sont un sous-ensemble.
        conn.execute(
            """
            INSERT OR IGNORE INTO route_stops (route_id, direction_id, seq, stop_id)
            SELECT t.route_id, t.direction_id, st.seq, st.stop_id
            FROM stop_times st
            JOIN trips t ON t.trip_id = st.trip_id
            WHERE t.trip_id IN (
                SELECT trip_id FROM (
                    SELECT trip_id, ROW_NUMBER() OVER (
                        PARTITION BY route_id, direction_id ORDER BY last_seq DESC, trip_id
                    ) AS rn
                    FROM trips
                ) WHERE rn = 1
            )
            """
        )

        rows = []
        for s in _reader(zf, "stops.txt"):
            if s["stop_id"] not in used_stops:
                continue
            try:
                lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
            except (TypeError, ValueError):
                continue
            netex = (s.get("ext_netex_id") or "").strip() or None
            # Le code SPOTI est le suffixe numérique du NeTEx sur 5 chiffres. Vérifié sur
            # les 2756 arrêts du réseau : aucune collision (le code max vaut 4811).
            spoti = netex.split(":")[-1][-5:] if netex else None
            rows.append(
                (s["stop_id"], (s.get("stop_name") or "").strip(), lat, lon, netex, spoti)
            )
        conn.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?)", rows)
        log.info("stops retenus : %d", len(rows))

        rows = []
        for c in _reader(zf, "calendar.txt"):
            mask = 0
            for bit, col in enumerate(DAY_COLUMNS):
                if (c.get(col) or "0") == "1":
                    mask |= 1 << bit
            rows.append((c["service_id"], mask, int(c["start_date"]), int(c["end_date"])))
        conn.executemany("INSERT INTO calendar VALUES (?,?,?,?)", rows)

        rows = [
            (c["service_id"], int(c["date"]), int(c["exception_type"]))
            for c in _reader(zf, "calendar_dates.txt")
        ]
        conn.executemany("INSERT INTO calendar_dates VALUES (?,?,?)", rows)

        feed_version = ""
        if "feed_info.txt" in zf.namelist():
            for fi in _reader(zf, "feed_info.txt"):
                feed_version = fi.get("feed_version") or ""
                break

    conn.executescript(INDEXES)
    conn.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [
            ("sha256", digest),
            ("feed_version", feed_version),
            ("built_at", datetime.now().isoformat(timespec="seconds")),
            ("route_types", ",".join(str(t) for t in sorted(keep_types))),
        ],
    )
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    tmp_path.replace(db_path)
    log.info("Base compilée : %s (%.1f Mo)", db_path, db_path.stat().st_size / 1e6)


def db_meta(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.DatabaseError:
        return {}
    finally:
        conn.close()


def ensure_db(cfg, force: bool = False) -> bool:
    """Télécharge et recompile si nécessaire. Renvoie True si la base a changé."""
    meta = db_meta(cfg.db_path)
    stored_types = meta.get("route_types", "")
    wanted_types = ",".join(str(t) for t in sorted(set(cfg.transit.route_types)))

    content, digest = download(cfg.gtfs.url, cfg.zip_path)
    if not force and meta.get("sha256") == digest and stored_types == wanted_types:
        log.info("GTFS inchangé (%s), rien à recompiler.", meta.get("feed_version", "?"))
        return False

    build_db(content, cfg.db_path, cfg.transit.route_types, digest)
    return True


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class Database:
    """Une connexion par thread.

    SQLite refuse qu'un objet connexion traverse les threads, et le dashboard interroge la
    base depuis le thread de Flask pendant que la boucle principale l'interroge aussi.
    Comme la base est ouverte en lecture seule et n'est jamais modifiée en service,
    plusieurs connexions concurrentes sont sans danger.
    """

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.path)
            self._local.conn = conn
        return conn

    def execute(self, *args, **kwargs):
        return self.conn.execute(*args, **kwargs)
