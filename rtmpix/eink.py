"""Rendu pour écran e-ink 7,5″ (800×480).

Un e-ink ne se rafraîchit que toutes les cinq à quinze minutes : **un compte à rebours n'y
a pas sa place**. On y affiche donc des valeurs stables — des heures absolues, « pars à
07:21 » plutôt que « dans 42 minutes » — et la vue d'ensemble de la journée. C'est le
complément de la matrice, pas son doublon : l'horloge dit l'urgence, l'e-ink dit le plan.

L'image est produite ici et servie par `web.py` ; le panneau n'a qu'à la récupérer et
l'afficher, qu'il s'agisse d'un TRMNL ou d'un XIAO ePaper piloté par un firmware maison.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

BLACK, WHITE = 0, 255

# Aucune police n'est embarquée : on prend la première disponible sur le système. Sur
# Debian, le paquet fonts-dejavu-core suffit (le script d'installation Proxmox l'ajoute).
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _font(size: int, bold: bool = False):
    for path in FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 : la police par défaut n'est pas redimensionnable
        return ImageFont.load_default()


class Canvas:
    """Petite couche de confort au-dessus de Pillow : mesure, troncature, filets."""

    def __init__(self, width: int, height: int):
        self.image = Image.new("L", (width, height), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.w, self.h = width, height

    def text(self, xy, content, size=16, bold=False, fill=BLACK, anchor=None, max_w=None):
        font = _font(size, bold)
        content = str(content)
        if max_w:
            content = self.truncate(content, font, max_w)
        self.draw.text(xy, content, font=font, fill=fill, anchor=anchor)
        return self.draw.textlength(content, font=font)

    def truncate(self, content: str, font, max_w: int) -> str:
        if self.draw.textlength(content, font=font) <= max_w:
            return content
        while content and self.draw.textlength(content + "…", font=font) > max_w:
            content = content[:-1]
        return content + "…"

    def width_of(self, content: str, size=16, bold=False) -> float:
        return self.draw.textlength(str(content), font=_font(size, bold))

    def line(self, xy0, xy1, fill=BLACK, width=1):
        self.draw.line([xy0, xy1], fill=fill, width=width)

    def box(self, xy, fill=None, outline=BLACK, width=1, radius=0):
        if radius:
            self.draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
        else:
            self.draw.rectangle(xy, fill=fill, outline=outline, width=width)

    def icon(self, kind: str, x: int, y: int, fill=BLACK):
        """Pictogrammes 18×18 tracés en pixels francs pour le panneau 1 bit."""
        d = self.draw
        if kind == "tram":
            d.line((x + 5, y + 3, x + 9, y, x + 13, y + 3), fill=fill, width=2)
            d.rounded_rectangle((x + 1, y + 4, x + 17, y + 14), radius=2, outline=fill, width=2)
            d.line((x + 6, y + 5, x + 6, y + 11), fill=fill, width=2)
            d.line((x + 12, y + 5, x + 12, y + 11), fill=fill, width=2)
            d.ellipse((x + 3, y + 14, x + 6, y + 17), fill=fill)
            d.ellipse((x + 12, y + 14, x + 15, y + 17), fill=fill)
        elif kind == "metro":
            d.ellipse((x + 1, y + 1, x + 17, y + 17), outline=fill, width=2)
            d.line((x + 4, y + 13, x + 4, y + 6, x + 9, y + 10,
                    x + 14, y + 6, x + 14, y + 13), fill=fill, width=2)
        elif kind == "bus":
            d.rounded_rectangle((x + 2, y + 2, x + 16, y + 14), radius=2, outline=fill, width=2)
            d.line((x + 3, y + 8, x + 15, y + 8), fill=fill, width=2)
            d.point((x + 5, y + 11), fill=fill)
            d.point((x + 13, y + 11), fill=fill)
            d.line((x + 4, y + 15, x + 4, y + 17), fill=fill, width=2)
            d.line((x + 14, y + 15, x + 14, y + 17), fill=fill, width=2)
        elif kind == "walk":
            d.ellipse((x + 7, y, x + 11, y + 4), fill=fill)
            d.line((x + 9, y + 5, x + 7, y + 11), fill=fill, width=2)
            d.line((x + 7, y + 8, x + 2, y + 11), fill=fill, width=2)
            d.line((x + 8, y + 8, x + 14, y + 10), fill=fill, width=2)
            d.line((x + 7, y + 11, x + 3, y + 17), fill=fill, width=2)
            d.line((x + 7, y + 11, x + 14, y + 17), fill=fill, width=2)
        elif kind == "bike":
            d.ellipse((x, y + 9, x + 7, y + 16), outline=fill, width=2)
            d.ellipse((x + 11, y + 9, x + 18, y + 16), outline=fill, width=2)
            d.line((x + 3, y + 13, x + 8, y + 6, x + 14, y + 13, x + 3, y + 13), fill=fill, width=2)
            d.line((x + 8, y + 6, x + 12, y + 6), fill=fill, width=2)
            d.line((x + 13, y + 5, x + 16, y + 5), fill=fill, width=2)
        elif kind == "calendar":
            d.rounded_rectangle((x + 1, y + 2, x + 17, y + 17), radius=2, outline=fill, width=2)
            d.line((x + 2, y + 7, x + 16, y + 7), fill=fill, width=2)
            d.line((x + 5, y, x + 5, y + 5), fill=fill, width=2)
            d.line((x + 13, y, x + 13, y + 5), fill=fill, width=2)
            d.rectangle((x + 5, y + 10, x + 8, y + 13), fill=fill)
        elif kind == "clock":
            d.ellipse((x + 1, y + 1, x + 17, y + 17), outline=fill, width=2)
            d.line((x + 9, y + 4, x + 9, y + 9, x + 13, y + 11), fill=fill, width=2)


DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]


def _french_date(moment: datetime) -> str:
    return f"{DAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}"


def _next_catchable(board: dict) -> str:
    """Premier passage atteignable depuis l'appartement, marche et quai compris."""
    return next((n["at"] for n in board.get("next", [])
                 if n.get("in_s", -1) >= board.get("lead_budget_s", 0)), "—")


def _vehicle_icon(item: dict) -> str:
    mode = item.get("mode")
    if mode == 0 or (mode is None and str(item.get("line", "")).startswith("T")):
        return "tram"
    if mode == 1 or (mode is None and str(item.get("line", "")).startswith("M")):
        return "metro"
    return "bus"


def render(state: dict, width: int = 800, height: int = 480) -> Image.Image:
    """Compose le tableau de bord complet à partir d'un instantané du service."""
    c = Canvas(width, height)
    now = datetime.now()
    margin = 22
    right_col_x = int(width * 0.60)

    # ------------------------------------------------------------------ en-tête
    c.icon("calendar", margin, 21)
    c.text((margin + 26, 18), _french_date(now), size=22, bold=True)
    source = state.get("source", "?")
    label = {"rbgl": "temps réel", "spoti": "temps réel", "gtfs": "horaires théoriques"}.get(
        source, "hors ligne"
    )
    c.text((width - margin, 20), f"{label} · {now:%H:%M}", size=15, anchor="ra")
    c.line((margin, 48), (width - margin, 48), width=2)

    # -------------------------------------------------- colonne gauche : départ
    y = 72
    journeys = state.get("journeys") or []
    active = next((j for j in journeys if j.get("deadline")), None)

    if active and active["deadline"]["state"] in ("ok", "late"):
        deadline = active["deadline"]
        option = (active.get("options") or [{}])[0]

        if deadline["state"] == "late":
            c.text((margin, y), "TROP TARD", size=52, bold=True)
            y += 62
            c.text((margin, y), f"pour {deadline['course']} à {deadline['at']}", size=18)
            y += 34
        else:
            c.icon("clock", margin, y + 1)
            c.text((margin + 25, y), "PARS À", size=17, bold=True)
            leave = option.get("leave_at", "—")
            c.text((margin, y + 18), leave, size=86, bold=True)
            y += 118
            course = active.get("course") or {}
            # Ici on a la place : l'intitulé complet, tronqué à la largeur réelle et non
            # au compte de caractères imposé par la matrice de 32 pixels.
            c.text((margin, y), f"{course.get('summary', '')} · {deadline['at']}",
                   size=19, bold=True, max_w=right_col_x - margin - 20)
            y += 28
            if course.get("location"):
                c.text((margin, y), course["location"], size=14,
                       max_w=right_col_x - margin - 20)
                y += 24

        # Détail de l'itinéraire, tronçon par tronçon.
        y += 10
        for leg in option.get("legs") or []:
            badge_w = max(56, int(c.width_of(leg["line"], size=15, bold=True)) + 37)
            c.box((margin, y, margin + badge_w, y + 24), fill=BLACK, outline=BLACK, radius=5)
            c.icon(_vehicle_icon(leg), margin + 5, y + 3, fill=WHITE)
            c.text((margin + badge_w - 6, y + 12), leg["line"], size=15, bold=True,
                   fill=WHITE, anchor="rm")
            c.text((margin + badge_w + 12, y + 3),
                   f"{leg['dep']}  {leg['from']}", size=15,
                   max_w=right_col_x - margin - badge_w - 40)
            c.text((margin + badge_w + 12, y + 24),
                   f"{leg['arr']}  {leg['to']}", size=15,
                   max_w=right_col_x - margin - badge_w - 40)
            y += 52
        if option.get("arrive_at"):
            c.text((margin, y), f"arrivée {option['arrive_at']}", size=17, bold=True)
            y += 30
        # Les autres itinéraires servent de plan B quand une ligne saute.
        others = (active.get("options") or [])[1:3]
        if others:
            c.text((margin, y + 4), "sinon : " + " · ".join(
                f"{o['label']} pars {o['leave_at']}" for o in others
            ), size=13, max_w=right_col_x - margin - 20)
            y += 22
    elif journeys:
        journey = journeys[0]
        c.text((margin, y), journey.get("name", "Destination"), size=30, bold=True,
               max_w=right_col_x - margin - 20)
        y += 52
        fastest = (journey.get("fastest_now") or [])[:1]
        if fastest:
            plan = fastest[0]
            c.text((margin, y), "PROCHAIN TRAJET", size=13, bold=True)
            c.text((margin, y + 25), plan["label"], size=30, bold=True)
            c.text((margin, y + 70),
                   f"Départ {plan['leave_at']} · arrivée {plan['arrive_at']}", size=17)
            y += 112
        else:
            c.text((margin, y), "Aucun trajet disponible", size=18)
            y += 35
        upcoming = (journey.get("upcoming") or [])[:3]
        for course in upcoming:
            c.text((margin, y), f"{course['start']} · {course['summary'][:34]}", size=14)
            y += 22
    else:
        home = state.get("home") or {}
        c.text((margin, y), home.get("label", "Départs"), size=34, bold=True)

    # ------------------------------------------------ colonne droite : départs
    x = right_col_x
    y = 72
    c.line((x - 20, 60), (x - 20, height - 74), fill=BLACK)
    c.text((x, y), "PROCHAINS PASSAGES", size=13, bold=True)
    y += 30
    col_w = (width - margin - x - 8) // 2
    boards = state.get("boards") or []
    trams = [b for b in boards if b.get("line", "").startswith("T")]
    shown = (trams + [b for b in boards if b not in trams])[:4]
    for i, board in enumerate(shown):
        bx = x + (i % 2) * (col_w + 8)
        by = y + (i // 2) * 84
        c.box((bx, by, bx + col_w, by + 76), outline=BLACK, radius=4)
        badge_w = max(48, int(c.width_of(board["line"], size=13, bold=True)) + 29)
        c.box((bx + 7, by + 7, bx + 7 + badge_w, by + 29), fill=BLACK,
              outline=BLACK, radius=4)
        c.icon(_vehicle_icon(board), bx + 10, by + 9, fill=WHITE)
        c.text((bx + 7 + badge_w - 5, by + 18), board["line"], size=13,
               bold=True, fill=WHITE, anchor="rm")
        if not board.get("realtime"):
            c.text((bx + col_w - 8, by + 10), "théo.", size=11, anchor="ra")
        c.text((bx + 8, by + 31), board.get("terminus", ""), size=12,
               max_w=col_w - 16)
        # Une seule heure absolue par ligne et direction.
        next_time = _next_catchable(board)
        c.text((bx + 8, by + 49), next_time, size=22, bold=True)

    y += 178
    other_boards = [b for b in boards if b not in shown]
    if other_boards:
        c.text((x, y), "AUTRES DÉPARTS", size=12, bold=True)
        y += 20
        for board in other_boards[:3]:
            next_time = _next_catchable(board)
            c.icon(_vehicle_icon(board), x, y)
            c.text((x + 22, y), f"{board['line']} → {board.get('terminus', '')}  {next_time}",
                   size=13, max_w=width - x - margin - 22)
            y += 19

    if shown and y < height - 105:
        first = shown[0]
        c.icon("walk", x, y)
        c.text((x + 22, y), f"À pied : {first.get('station', '')} · "
               f"{first.get('walk_s', 0) // 60}′{first.get('walk_s', 0) % 60:02d}",
               size=13, max_w=width - x - margin - 22)
        y += 22

    velo = state.get("velo") or []
    if velo and y < height - 80:
        station = velo[0]
        c.icon("bike", x, y)
        c.text((x + 22, y), f"LeVélo {station['name']} : {station['bikes']} vélos",
               size=13, max_w=width - x - margin - 22)

    # ----------------------------------------------------------- pied : alertes
    disruptions = state.get("disruptions") or []
    c.line((margin, height - 62), (width - margin, height - 62), width=1)
    if disruptions:
        first = disruptions[0]
        mark = "!" if first.get("critical") else "·"
        c.box((margin, height - 50, margin + 22, height - 28), fill=BLACK, outline=BLACK, radius=4)
        c.text((margin + 11, height - 39), mark, size=15, bold=True, fill=WHITE, anchor="mm")
        c.text((margin + 32, height - 47), first["title"], size=15, bold=True,
               max_w=width - margin * 2 - 40)
        if len(disruptions) > 1:
            c.text((width - margin, height - 26), f"+{len(disruptions) - 1} autre(s)",
                   size=12, anchor="ra")
    else:
        c.text((margin, height - 46), "Aucune perturbation sur tes lignes", size=14)

    return c.image


def to_bmp_1bit(image: Image.Image) -> bytes:
    """BMP monochrome, le format que les panneaux e-ink attendent."""
    import io

    buffer = io.BytesIO()
    # Tramage de Floyd-Steinberg : sans intérêt ici puisque tout est déjà noir ou blanc,
    # mais correct si un jour on ajoute des aplats de gris.
    image.convert("1").save(buffer, format="BMP")
    return buffer.getvalue()


def to_png(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.convert("1").save(buffer, format="PNG")
    return buffer.getvalue()


def to_packed_1bpp(image: Image.Image) -> bytes:
    """Buffer brut 1 bit par pixel, 1 = noir.

    C'est ce qu'un firmware ESP32 minimal peut pousser directement dans le contrôleur du
    panneau, sans décoder ni BMP ni PNG.
    """
    mono = image.convert("1")
    width, height = mono.size
    pixels = mono.load()
    out = bytearray()
    for y in range(height):
        byte = 0
        bits = 0
        for x in range(width):
            byte = (byte << 1) | (0 if pixels[x, y] else 1)
            bits += 1
            if bits == 8:
                out.append(byte)
                byte = 0
                bits = 0
        if bits:
            out.append(byte << (8 - bits))
    return bytes(out)
