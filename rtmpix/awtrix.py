"""Client HTTP AWTRIX 3 (Ulanzi TC001).

L'horloge ne contient aucune logique : elle affiche des « custom apps » qu'on pousse en
JSON. Une app dont on cesse d'envoyer les mises à jour disparaît d'elle-même au bout de
`lifetime` secondes — c'est ce qui évite d'afficher un horaire figé si le service tombe.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)


class Awtrix:
    def __init__(self, cfg):
        self.base = f"http://{cfg.awtrix.host}"
        self.timeout = cfg.awtrix.timeout_s
        self.prefix = cfg.awtrix.app_prefix
        self.lifetime = cfg.awtrix.lifetime_s
        self.duration = cfg.awtrix.duration_s
        self._pushed: set[str] = set()

    def app_name(self, suffix: str) -> str:
        return f"{self.prefix}_{suffix}"

    def stats(self) -> dict[str, Any] | None:
        try:
            resp = requests.get(f"{self.base}/api/stats", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Horloge injoignable sur %s : %s", self.base, exc)
            return None

    def push(self, suffix: str, payload: dict[str, Any]) -> bool:
        name = self.app_name(suffix)
        body = {
            "duration": self.duration,
            "lifetime": self.lifetime,
            "lifetimeMode": 1,  # 1 = marque l'app en rouge au lieu de la supprimer d'un coup
            **payload,
        }
        try:
            resp = requests.post(
                f"{self.base}/api/custom", params={"name": name}, json=body, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Envoi de %s échoué : %s", name, exc)
            return False
        self._pushed.add(name)
        return True

    def remove(self, suffix: str) -> None:
        """Un POST au corps vide supprime l'app côté horloge."""
        name = self.app_name(suffix)
        try:
            requests.post(
                f"{self.base}/api/custom",
                params={"name": name},
                data="",
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.debug("Suppression de %s échouée : %s", name, exc)
        self._pushed.discard(name)

    def sync(self, apps: dict[str, dict[str, Any]]) -> None:
        """Pousse le jeu d'apps courant et retire celles qui n'ont plus lieu d'être."""
        wanted = {self.app_name(s) for s in apps}
        for suffix, payload in apps.items():
            self.push(suffix, payload)
        for stale in list(self._pushed - wanted):
            self.remove(stale.removeprefix(f"{self.prefix}_"))

    def notify(self, payload: dict[str, Any]) -> bool:
        try:
            resp = requests.post(f"{self.base}/api/notify", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Notification échouée : %s", exc)
            return False
