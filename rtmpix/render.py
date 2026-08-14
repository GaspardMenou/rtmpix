"""Composition des écrans AWTRIX.

Contrainte de base : 32×8 pixels, soit environ huit caractères sans défilement. Ce qui
doit se lire d'un coup d'œil depuis le couloir tient sur un écran ; le reste défile.

Convention d'affichage :
  M2 7m    il te reste 7 minutes avant de devoir partir
  M2 ~7m   même chose, mais sur l'horaire théorique (le temps réel a décroché)
  M2 GO    c'est maintenant, ça clignote
  M2 --    plus rien d'attrapable dans l'horizon
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

# Palette d'urgence : la couleur porte l'information avant même qu'on ait lu le chiffre.
CALM = "22C55E"      # > 5 min, tranquille
SOON = "FACC15"      # 2 à 5 min, on range ses affaires
HURRY = "FB923C"     # < 2 min, on y va
NOW = "EF4444"       # maintenant ou jamais
DEAD = "4B5563"      # plus de service
WHITE = "FFFFFF"

LEAD_WINDOW_S = 600  # fenêtre de la barre de progression : 10 minutes


def urgency_color(seconds: int) -> str:
    if seconds < 60:
        return NOW
    if seconds < 120:
        return HURRY
    if seconds < 300:
        return SOON
    return CALM


def format_lead(seconds: int) -> str:
    """Compte à rebours compact : 'GO', '7m', '1h05'."""
    if seconds < 60:
        return "GO"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}"


def slug(value: str, length: int = 6) -> str:
    stripped = unicodedata.normalize("NFD", value)
    ascii_only = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    return "".join(c for c in ascii_only.lower() if c.isalnum())[:length] or "x"


def line_color(board) -> str:
    """Couleur officielle de la ligne, telle que publiée dans le GTFS."""
    if board.color:
        color = board.color.lstrip("#")
        if len(color) == 6:
            return color
    return WHITE


def board_screen(board, now: datetime) -> dict:
    """Décrit l'écran d'une ligne, indépendamment du transport (AWTRIX ou aperçu web)."""
    catchable = board.catchable(now)
    if not catchable:
        return {
            "line": board.line,
            "line_color": line_color(board),
            "value": "--",
            "value_color": DEAD,
            "lead_s": None,
            "realtime": board.realtime,
            "blink": False,
            "progress": 0,
        }

    lead = catchable[0]
    color = urgency_color(lead)
    prefix = "" if board.realtime else "~"
    return {
        "line": board.line,
        "line_color": line_color(board),
        "value": f"{prefix}{format_lead(lead)}",
        "value_color": color,
        "lead_s": lead,
        "realtime": board.realtime,
        "blink": lead < 60,
        "progress": max(0, min(100, int(100 * lead / LEAD_WINDOW_S))),
    }


def board_app(board, now: datetime) -> tuple[str, dict]:
    """Construit l'app AWTRIX d'une ligne. Renvoie (suffixe, payload)."""
    screen = board_screen(board, now)
    suffix = f"{slug(board.line, 4)}_{slug(board.terminus, 4)}"

    payload: dict = {
        "text": [
            {"t": f"{screen['line']} ", "c": screen["line_color"]},
            {"t": screen["value"], "c": screen["value_color"]},
        ],
        "noScroll": True,
    }
    if screen["lead_s"] is not None:
        payload["progress"] = screen["progress"]
        payload["progressC"] = f"#{screen['value_color']}"
        payload["progressBC"] = "#101010"
    if screen["blink"]:
        payload["blinkText"] = 500
    return suffix, payload


def velo_screen(station) -> dict:
    if not station.renting or station.bikes == 0:
        color = NOW
    elif station.bikes <= 2:
        color = HURRY
    else:
        color = CALM
    return {
        "bikes": station.bikes,
        "docks": station.docks,
        "color": color,
        "name": station.name,
    }


def velo_app(station) -> tuple[str, dict]:
    """Vélos disponibles et bornes libres à la station la plus proche."""
    screen = velo_screen(station)
    payload = {
        "text": [
            {"t": str(screen["bikes"]), "c": screen["color"]},
            {"t": "v ", "c": DEAD},
            {"t": str(screen["docks"]), "c": WHITE},
            {"t": "b", "c": DEAD},
        ],
        "noScroll": True,
    }
    return f"velo_{slug(station.name, 6)}", payload


def format_hour(moment: datetime) -> str:
    """8h00 s'écrit « 8h », 8h30 s'écrit « 8h30 » : on économise deux caractères sur trente-deux."""
    return f"{moment.hour}h" if moment.minute == 0 else f"{moment.hour}h{moment.minute:02d}"


def deadline_screen(journey, now: datetime) -> dict | None:
    """« Il te reste X avant de devoir partir pour être à l'heure en cours. »"""
    course = journey.course
    if course is None:
        return None

    plan = journey.best
    if plan is None:
        return {
            "state": "impossible",
            "course": course.short,
            "at": format_hour(course.start),
            "left_s": None,
            "value": "?",
            "color": DEAD,
            "route": "",
        }

    left = int((plan.leave_at - now).total_seconds())
    if left < 0:
        # Plus aucun itinéraire ne permet d'arriver à l'heure : le dire franchement.
        return {
            "state": "late",
            "course": course.short,
            "at": format_hour(course.start),
            "left_s": left,
            "value": "RETARD",
            "color": NOW,
            "route": plan.pattern.label,
        }

    return {
        "state": "ok",
        "course": course.short,
        "at": format_hour(course.start),
        "left_s": left,
        "value": format_lead(left),
        "color": urgency_color(left),
        "route": plan.pattern.label,
        "board_at": plan.board_at.strftime("%H:%M"),
        "arrive_at": plan.arrive_at.strftime("%H:%M"),
    }


def deadline_app(journey, now: datetime, window_min: int) -> tuple[str, dict] | None:
    """Écran du compte à rebours. Absent tant que l'échéance est lointaine."""
    screen = deadline_screen(journey, now)
    if screen is None:
        return None
    suffix = f"go_{slug(journey.destination.name, 6)}"

    if screen["state"] == "late":
        return suffix, {
            "text": f"RETARD {screen['at']} {screen['course']}",
            "color": NOW,
            "scrollSpeed": 80,
            "blinkText": 700,
        }
    if screen["state"] == "impossible":
        return None
    if screen["left_s"] > window_min * 60:
        return None  # rien d'utile à afficher trois heures à l'avance

    text = f"{screen['at']} {screen['value']}"
    payload: dict = {
        "text": [
            {"t": f"{screen['at']} ", "c": DEAD},
            {"t": screen["value"], "c": screen["color"]},
        ],
        "noScroll": len(text) <= 8,
        "progress": max(0, min(100, int(100 * screen["left_s"] / (window_min * 60)))),
        "progressC": f"#{screen['color']}",
        "progressBC": "#101010",
    }
    if screen["left_s"] < 60:
        payload["blinkText"] = 500
    return suffix, payload


def disruption_app(disruption) -> tuple[str, dict]:
    """Une perturbation, en défilement. Le titre suffit : il dit la ligne et le fait."""
    return (
        f"alert_{slug(disruption.id, 8)}",
        {
            "text": disruption.title,
            "color": NOW if disruption.critical else HURRY,
            "scrollSpeed": 80,
            "repeat": 1,
        },
    )


def preview(board, now: datetime) -> str:
    """Rendu texte pour la console, en mode `once`."""
    catchable = board.catchable(now)
    source = "réel" if board.realtime else "théo"
    times = ", ".join(d.when.strftime("%H:%M") for d in board.departures[:3]) or "—"
    state = f"pars dans {format_lead(catchable[0])}" if catchable else "plus attrapable"
    return (
        f"  {board.line:>4} → {board.terminus[:22]:<22} "
        f"{board.station[:16]:<16} "
        f"(marche {board.walk_s // 60}′{board.walk_s % 60:02d} + quai {board.access_s}s)  "
        f"{state:<18} [{source}]  {times}"
    )
