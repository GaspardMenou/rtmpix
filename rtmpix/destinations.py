"""Destinations ajoutées depuis le dashboard.

Même principe que la calibration : le YAML décrit l'intention de départ et n'est jamais
réécrit — on n'écrase pas les commentaires de quelqu'un — tandis que ce qui se règle en
cours de route vit dans un fichier JSON à part. Les deux listes sont fusionnées au
démarrage, celles du fichier venant après celles de la configuration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import Destination

log = logging.getLogger(__name__)


def load(path: Path) -> list[Destination]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Destinations illisibles (%s), ignorées.", path)
        return []

    out = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(
                Destination(
                    name=str(item["name"]),
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                    calendar=str(item.get("calendar") or ""),
                    location_filter=str(item.get("location_filter") or ""),
                    radius_m=item.get("radius_m"),
                )
            )
        except (KeyError, TypeError, ValueError):
            log.warning("Destination invalide ignorée : %r", item)
    return out


def save(path: Path, destinations: list[Destination]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": d.name,
            "lat": d.lat,
            "lon": d.lon,
            "calendar": d.calendar,
            "location_filter": d.location_filter,
            "radius_m": d.radius_m,
        }
        for d in destinations
    ]
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


def merge(from_config: list[Destination], from_file: list[Destination]) -> list[Destination]:
    """Les deux sources réunies, sans doublon de nom (la config a le dernier mot)."""
    seen = {d.name.casefold() for d in from_config}
    return list(from_config) + [d for d in from_file if d.name.casefold() not in seen]
