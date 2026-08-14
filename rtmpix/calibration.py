"""Réglages mesurés au chronomètre, stockés à part de la config.

La config décrit l'intention, la calibration décrit le terrain. On les sépare pour que
`rtmpix calibrate` puisse écrire sans réécrire le YAML commenté de l'utilisateur.

Ce qui se calibre :
  pace_factor     ton allure par rapport à celle du routeur (0.85 = tu marches plus vite)
  access[gare]    temps entre l'entrée de la station et le quai
  walk[gare]      temps de marche mesuré, qui court-circuite complètement le routeur
  transfer[gare]  temps de correspondance réel (quai du métro → arrêt de bus)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Calibration:
    pace_factor: float = 1.0
    access: dict[str, int] = field(default_factory=dict)
    walk: dict[str, int] = field(default_factory=dict)
    transfer: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Calibration:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Calibration illisible (%s), valeurs par défaut.", path)
            return cls()
        return cls(
            pace_factor=float(raw.get("pace_factor", 1.0)),
            access={str(k): int(v) for k, v in (raw.get("access") or {}).items()},
            walk={str(k): int(v) for k, v in (raw.get("walk") or {}).items()},
            transfer={str(k): int(v) for k, v in (raw.get("transfer") or {}).items()},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")
