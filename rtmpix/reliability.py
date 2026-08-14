"""Observatoire de ponctualité : mesurer plutôt que supposer.

Un métro roule sur une voie réservée, un bus est dans le trafic. Mais de combien ? Plutôt
que d'inscrire une constante au jugé, on mesure : l'API renvoie pour chaque passage à la
fois `AimedDepartureTime` (théorique) et `ExpectedDepartureTime` (réel), et leur écart est
exactement la ponctualité du moment. Le service voit défiler ces couples en permanence ; il
suffit de les garder.

Deux risques distincts, et symétriques :

* **le retard** — le véhicule arrive après l'heure : on vise donc une correspondance ou une
  arrivée plus tôt que nécessaire, à hauteur du retard rencontré 4 fois sur 5 ;
* **l'avance** — le bus passe avant l'heure et on le rate depuis le trottoir : on se
  présente au quai plus tôt, à hauteur de l'avance observée.

Tant qu'une ligne n'a pas assez d'observations, on retombe sur une marge par mode.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    line        TEXT NOT NULL,
    route_type  INTEGER,
    aimed       TEXT NOT NULL,   -- horaire théorique : identifie la course
    deviation_s INTEGER NOT NULL,-- positif = retard, négatif = avance
    observed_at TEXT NOT NULL,
    PRIMARY KEY (line, aimed)    -- une course compte une fois, pas une fois par rafraîchissement
);
CREATE INDEX IF NOT EXISTS idx_obs_line ON observations (line, observed_at);
"""


@dataclass
class LineStats:
    line: str
    samples: int
    median_s: int
    late_s: int      # percentile haut : le retard qu'on absorbe
    early_s: int     # avance observée, en valeur positive


class Punctuality:
    """Journal des écarts théorique/réel, par ligne."""

    def __init__(self, path: Path, cfg):
        self.path = path
        self.cfg = cfg.reliability
        self.lock = threading.Lock()
        self._cache: dict[str, LineStats] = {}
        self._cache_at: datetime | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------------------------------------------------------- écriture

    def record(self, observations: list[tuple[str, int | None, datetime, int]]) -> int:
        """Enregistre des (ligne, route_type, horaire théorique, écart en secondes)."""
        if not self.cfg.enabled or not observations:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (line, route_type, aimed.isoformat(), int(deviation), now)
            for line, route_type, aimed, deviation in observations
            # Au-delà d'une demi-heure d'écart, c'est un artefact de données, pas un retard.
            if abs(deviation) <= 1800
        ]
        if not rows:
            return 0
        with self.lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO observations (line, route_type, aimed, deviation_s, observed_at) "
                "VALUES (?,?,?,?,?) "
                # Le dernier relevé avant le passage est le plus fiable : il remplace les précédents.
                "ON CONFLICT(line, aimed) DO UPDATE SET "
                "deviation_s = excluded.deviation_s, observed_at = excluded.observed_at",
                rows,
            )
        self._cache_at = None
        return len(rows)

    def purge(self) -> int:
        if not self.cfg.enabled:
            return 0
        limit = (datetime.now() - timedelta(days=self.cfg.retention_days)).isoformat()
        with self.lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM observations WHERE observed_at < ?", (limit,))
            return cur.rowcount

    # ----------------------------------------------------------------- lecture

    def stats(self, refresh: bool = False) -> dict[str, LineStats]:
        """Statistiques par ligne, recalculées au plus une fois par minute."""
        if not self.cfg.enabled:
            return {}
        now = datetime.now()
        if not refresh and self._cache_at and (now - self._cache_at).total_seconds() < 60:
            return self._cache

        since = (now - timedelta(days=self.cfg.retention_days)).isoformat()
        out: dict[str, LineStats] = {}
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT line, deviation_s FROM observations WHERE observed_at >= ? ORDER BY line",
                (since,),
            ).fetchall()

        by_line: dict[str, list[int]] = {}
        for row in rows:
            by_line.setdefault(row["line"], []).append(row["deviation_s"])

        for line, values in by_line.items():
            values.sort()
            out[line] = LineStats(
                line=line,
                samples=len(values),
                median_s=_percentile(values, 50),
                late_s=max(0, _percentile(values, self.cfg.percentile)),
                early_s=max(0, -_percentile(values, 100 - self.cfg.percentile)),
            )

        self._cache = out
        self._cache_at = now
        return out

    def margins(self, line: str, route_type: int | None) -> tuple[int, int]:
        """(marge de retard, marge d'avance) en secondes, pour un tronçon donné.

        Mesurée si la ligne a assez d'observations, sinon repli sur le mode.
        """
        if not self.cfg.enabled:
            return 0, 0
        stats = self.stats().get(line)
        if stats and stats.samples >= self.cfg.min_samples:
            return stats.late_s, stats.early_s
        default = self.cfg.default_margin_s.get(route_type if route_type is not None else 3, 60)
        return int(default), 0


def _percentile(sorted_values: list[int], p: float) -> int:
    """Percentile par rang le plus proche, sur une liste déjà triée."""
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, max(0, round(p / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]
