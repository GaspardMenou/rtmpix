"""Emploi du temps iCal.

Sert à une seule chose : connaître l'heure du prochain cours, donc l'heure d'arrivée à
tenir. Le fichier est mis en cache sur disque — le jour où le serveur de l'école tombe, on
continue avec la dernière version connue plutôt que d'afficher n'importe quoi.

Les exports ADE / Hyperplanning listent en général une occurrence par séance, mais certains
utilisent des règles de récurrence : `recurring_ical_events` développe les deux cas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")


@dataclass
class Course:
    summary: str
    start: datetime
    end: datetime
    location: str = ""

    @property
    def short(self) -> str:
        """Un intitulé qui tienne sur une matrice de 32 pixels."""
        text = self.summary.strip()
        for separator in (" - ", " – ", " : ", "|"):
            if separator in text:
                text = text.split(separator)[0].strip()
                break
        return text[:18]


class ScheduleClient:
    def __init__(self, url: str, cache_path: Path, timeout_s: int = 15, user_agent: str = "rtmpix"):
        self.url = url
        self.cache_path = cache_path
        self.timeout = timeout_s
        self.headers = {"User-Agent": user_agent}
        self._events: list[Course] = []
        self._fetched_at: datetime | None = None

    # ------------------------------------------------------------------ chargement

    def _raw(self) -> bytes | None:
        """Contenu iCal, depuis le réseau si possible, sinon depuis le cache."""
        source = self.url
        if source.startswith(("http://", "https://")):
            try:
                resp = requests.get(source, headers=self.headers, timeout=self.timeout)
                resp.raise_for_status()
                if b"BEGIN:VCALENDAR" not in resp.content[:2048]:
                    raise ValueError("la réponse n'est pas un fichier iCal")
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_bytes(resp.content)
                return resp.content
            except (requests.RequestException, ValueError) as exc:
                log.warning("Emploi du temps injoignable (%s), on garde le cache.", exc)
        else:
            path = Path(source).expanduser()
            if path.exists():
                return path.read_bytes()
            log.warning("Fichier iCal introuvable : %s", path)

        if self.cache_path.exists():
            return self.cache_path.read_bytes()
        return None

    def refresh(self, horizon_days: int = 14) -> int:
        """Recharge l'agenda et renvoie le nombre de séances retenues."""
        raw = self._raw()
        if not raw:
            self._events = []
            return 0

        try:
            import icalendar
            import recurring_ical_events
        except ImportError:
            log.error("icalendar / recurring-ical-events manquants : pip install -r requirements.txt")
            return 0

        try:
            calendar = icalendar.Calendar.from_ical(raw)
        except Exception as exc:
            log.error("iCal illisible : %s", exc)
            return 0

        now = datetime.now(PARIS)
        window_start = now - timedelta(days=1)
        window_end = now + timedelta(days=horizon_days)

        courses: list[Course] = []
        try:
            occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)
        except Exception as exc:
            log.warning("Développement des récurrences impossible (%s), lecture directe.", exc)
            occurrences = calendar.walk("VEVENT")

        for event in occurrences:
            start = _as_datetime(event.get("DTSTART"))
            end = _as_datetime(event.get("DTEND")) or (start + timedelta(hours=1) if start else None)
            if start is None or end is None:
                continue
            courses.append(
                Course(
                    summary=str(event.get("SUMMARY", "Cours")),
                    start=start,
                    end=end,
                    location=str(event.get("LOCATION", "")),
                )
            )

        courses.sort(key=lambda c: c.start)
        self._events = courses
        self._fetched_at = now
        log.info("Emploi du temps : %d séances sur %d jours", len(courses), horizon_days)
        return len(courses)

    # --------------------------------------------------------------------- lecture

    @property
    def events(self) -> list[Course]:
        return self._events

    def next_course(self, now: datetime | None = None, location_filter: str = "") -> Course | None:
        """Prochaine séance à venir — celle qui fixe l'heure à laquelle il faut être là."""
        now = now or datetime.now(PARIS)
        needle = location_filter.casefold().strip()
        for course in self._events:
            if course.start <= now:
                continue
            if needle and needle not in f"{course.location} {course.summary}".casefold():
                continue
            return course
        return None

    def upcoming(self, limit: int = 5, now: datetime | None = None) -> list[Course]:
        now = now or datetime.now(PARIS)
        return [c for c in self._events if c.end > now][:limit]


def _as_datetime(prop) -> datetime | None:
    """Normalise DTSTART/DTEND en datetime aware Europe/Paris.

    Une propriété iCal peut porter une date seule (journée entière) : on la ramène à
    minuit, faute de quoi la comparaison avec l'heure courante échoue.
    """
    if prop is None:
        return None
    value = getattr(prop, "dt", prop)
    if isinstance(value, datetime):
        return value.astimezone(PARIS) if value.tzinfo else value.replace(tzinfo=PARIS)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=PARIS)
    return None
