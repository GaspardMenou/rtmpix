"""Perturbations réseau RTM.

C'est la brique qui répond au « des fois il n'y a juste plus de métro » : quand une ligne
saute, l'info arrive ici avant que les horaires ne se vident.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Disruption:
    id: str
    title: str
    critical: bool
    lines: list[str]
    content: str = ""

    def concerns(self, lines: set[str]) -> bool:
        return bool(lines & set(self.lines))


def _clean(raw: str) -> str:
    """Le champ `content` arrive en HTML : on le ramène à du texte scrollable."""
    text = TAG_RE.sub(" ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class DisruptionClient:
    def __init__(self, cfg):
        self.base = cfg.sources.rbgl_base.rstrip("/")
        self.timeout = cfg.sources.timeout_s
        self.headers = {"User-Agent": cfg.sources.user_agent}
        self.critical_only = cfg.disruptions.critical_only

    def fetch(self) -> list[Disruption]:
        try:
            resp = requests.get(
                f"{self.base}/RTM/getDisruptions", headers=self.headers, timeout=self.timeout
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Perturbations indisponibles : %s", exc)
            return []

        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("disruptions") or []

        out = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            critical = bool(item.get("is_critical"))
            if self.critical_only and not critical:
                continue
            lines = [
                (line.get("code") or "").strip()
                for line in item.get("lines") or []
                if isinstance(line, dict) and line.get("code")
            ]
            out.append(
                Disruption(
                    id=str(item.get("id", "")),
                    title=_clean(item.get("title", "")),
                    critical=critical,
                    lines=lines,
                    content=_clean(item.get("content", "")),
                )
            )
        return out


def relevant(disruptions: list[Disruption], my_lines: set[str], only_mine: bool) -> list[Disruption]:
    if not only_mine:
        return disruptions
    return [d for d in disruptions if d.concerns(my_lines)]
