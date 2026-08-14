"""Réseau miniature pour tester la logique sans dépendre du GTFS réel.

Deux lignes et une correspondance suffisent à couvrir ce qui casse silencieusement : le
calcul à rebours, l'appariement géométrique des arrêts, et le passage de minuit.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rtmpix import gtfs

# Un hub où l'on change de mode, avec deux arrêts distincts à 40 m — exactement la
# situation de La Rose (quai « La Rose » / arrêt de bus « Métro La Rose »).
STOPS = [
    ("S_HOME", "Départ", 43.3000, 5.4000, "RTM:PNT:00000001", "00001"),
    ("S_HUB_M", "Le Hub", 43.3200, 5.4200, "RTM:PNT:00000002", "00002"),
    ("S_HUB_B", "Métro Le Hub", 43.32035, 5.42005, "RTM:PNT:00000003", "00003"),
    ("S_DEST", "Arrivée", 43.3400, 5.4400, "RTM:PNT:00000004", "00004"),
    ("S_FAR", "Ailleurs", 43.5000, 5.9000, "RTM:PNT:00000005", "00005"),
]

ROUTES = [
    ("R_METRO", "M9", "Métro d'essai", 1, "009FE3"),
    ("R_BUS", "B9", "Bus d'essai", 3, "E30613"),
]


def _hhmmss(hours: int, minutes: int) -> int:
    return hours * 3600 + minutes * 60


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Construit une base au schéma réel, remplie à la main."""
    path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(gtfs.SCHEMA)

    conn.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?)", STOPS)
    conn.executemany("INSERT INTO routes VALUES (?,?,?,?,?)", ROUTES)

    trips, stop_times = [], []

    # Métro : toutes les 10 minutes de 6h00 à 9h00, 20 minutes de trajet.
    for index, minute in enumerate(range(0, 181, 10)):
        trip = f"T_M{index}"
        trips.append((trip, "R_METRO", "SVC_ALL", "Le Hub", 0, 1))
        dep = _hhmmss(6, 0) + minute * 60
        stop_times.append((trip, "S_HOME", dep, dep, 0))
        stop_times.append((trip, "S_HUB_M", dep + 1200, dep + 1200, 1))

    # Bus : toutes les 15 minutes, 6 minutes de trajet.
    for index, minute in enumerate(range(0, 181, 15)):
        trip = f"T_B{index}"
        trips.append((trip, "R_BUS", "SVC_ALL", "Arrivée", 0, 1))
        dep = _hhmmss(6, 5) + minute * 60
        stop_times.append((trip, "S_HUB_B", dep, dep, 0))
        stop_times.append((trip, "S_DEST", dep + 360, dep + 360, 1))

    # Une course après minuit, pour vérifier le rollover (25:10 = 1h10 le lendemain).
    trips.append(("T_LATE", "R_METRO", "SVC_ALL", "Le Hub", 0, 1))
    stop_times.append(("T_LATE", "S_HOME", _hhmmss(25, 10), _hhmmss(25, 10), 0))
    stop_times.append(("T_LATE", "S_HUB_M", _hhmmss(25, 30), _hhmmss(25, 30), 1))

    conn.executemany("INSERT INTO trips VALUES (?,?,?,?,?,?)", trips)
    conn.executemany("INSERT INTO stop_times VALUES (?,?,?,?,?)", stop_times)

    # Service actif tous les jours, toute l'année.
    conn.execute("INSERT INTO calendar VALUES (?,?,?,?)", ("SVC_ALL", 0b1111111, 20200101, 20991231))
    conn.execute(
        "INSERT INTO route_stops VALUES (?,?,?,?)", ("R_METRO", 0, 0, "S_HOME")
    )
    conn.execute("INSERT INTO route_stops VALUES (?,?,?,?)", ("R_METRO", 0, 1, "S_HUB_M"))
    conn.execute("INSERT INTO route_stops VALUES (?,?,?,?)", ("R_BUS", 0, 0, "S_HUB_B"))
    conn.execute("INSERT INTO route_stops VALUES (?,?,?,?)", ("R_BUS", 0, 1, "S_DEST"))
    conn.executescript(gtfs.INDEXES_EARLY)
    conn.executescript(gtfs.INDEXES)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def db(db_path: Path):
    return gtfs.Database(db_path)
