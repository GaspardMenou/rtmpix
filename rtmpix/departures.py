"""Agrégation des passages en « tableaux » par ligne et sens, avec compte à rebours.

Le chiffre qui compte n'est pas « le métro passe dans 4 min » — inutile si l'arrêt est à
7 minutes à pied et 2 minutes de couloirs — mais « il te reste X minutes avant de partir ».
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from .realtime import Departure


@dataclass
class Board:
    line: str
    terminus: str
    station: str
    lead_s: int              # marche + accès au quai + préparation, en secondes
    walk_s: int = 0
    access_s: int = 0
    color: str | None = None
    departures: list[Departure] = field(default_factory=list)

    @property
    def realtime(self) -> bool:
        """Vrai si le prochain passage est une mesure terrain et non du théorique."""
        return bool(self.departures) and self.departures[0].realtime

    def leave_in(self, now: datetime) -> list[int]:
        """Secondes restantes avant de devoir partir, pour chaque passage à venir."""
        return [d.seconds_from(now) - self.lead_s for d in self.departures]

    def catchable(self, now: datetime) -> list[int]:
        """Idem, en ne gardant que ce qui est encore attrapable."""
        return [s for s in self.leave_in(now) if s >= 0]


def _fold(value: str) -> str:
    """Comparaison tolérante aux accents et à la casse (« Fourragère » vs « fourragere »)."""
    stripped = unicodedata.normalize("NFD", value)
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").casefold().strip()


def _matches_filter(dep: Departure, patterns: list[str]) -> bool:
    """`lines` accepte "M1" (toute la ligne) ou "M1>Fourragere" (un sens précis)."""
    if not patterns:
        return True
    for pattern in patterns:
        line, _, terminus = pattern.partition(">")
        if _fold(dep.line) != _fold(line):
            continue
        if not terminus or _fold(terminus) in _fold(dep.terminus):
            return True
    return False


def build_boards(departures: list[Departure], stations, cfg, now: datetime) -> list[Board]:
    """Regroupe les passages par (ligne, terminus) et trie par urgence de départ."""
    by_name = {s.name: s for s in stations}
    horizon_s = cfg.transit.horizon_min * 60

    grouped: dict[tuple[str, str, str], Board] = {}
    for dep in departures:
        if not dep.line or not _matches_filter(dep, cfg.transit.lines):
            continue
        # Une rame dont le terminus est la station où l'on se trouve y arrive, elle n'en
        # part pas : « T1 → Noailles » affiché à Noailles n'emmène nulle part.
        if dep.terminus and _fold(dep.terminus) == _fold(dep.station):
            continue
        delta = dep.seconds_from(now)
        if delta < 0 or delta > horizon_s:
            continue

        key = (dep.station, dep.line, dep.terminus)
        board = grouped.get(key)
        if board is None:
            station = by_name.get(dep.station)
            board = Board(
                line=dep.line,
                terminus=dep.terminus,
                station=dep.station,
                lead_s=station.lead_s(cfg.walk.overhead_s) if station else cfg.walk.overhead_s,
                walk_s=station.walk_s if station else 0,
                access_s=station.access_s if station else 0,
                color=dep.color,
            )
            grouped[key] = board
        board.departures.append(dep)
        if board.color is None and dep.color:
            board.color = dep.color

    boards = list(grouped.values())
    for board in boards:
        board.departures.sort(key=lambda d: d.when)
        # Deux sources peuvent annoncer le même passage à quelques secondes près.
        deduped: list[Departure] = []
        for dep in board.departures:
            if deduped and abs((dep.when - deduped[-1].when).total_seconds()) < 30:
                continue
            deduped.append(dep)
        board.departures = deduped[:4]

    # La même ligne peut être accessible depuis deux stations du rayon. Deux écrans pour
    # un seul trajet ne servent à rien : on garde la station qui laisse le plus de marge.
    best: dict[tuple[str, str], Board] = {}
    for board in boards:
        key = (_fold(board.line), _fold(board.terminus))
        rival = best.get(key)
        if rival is None or _margin(board, now) > _margin(rival, now):
            best[key] = board
    boards = list(best.values())

    def sort_key(board: Board) -> tuple[int, int]:
        catchable = board.catchable(now)
        # Les lignes encore attrapables d'abord, la plus urgente en tête.
        return (0, catchable[0]) if catchable else (1, board.lead_s)

    boards.sort(key=sort_key)
    return boards[: cfg.transit.max_lines]


def _margin(board: Board, now: datetime) -> int:
    """Marge offerte par le prochain passage attrapable ; -1 s'il n'y en a aucun."""
    catchable = board.catchable(now)
    return catchable[0] if catchable else -1
