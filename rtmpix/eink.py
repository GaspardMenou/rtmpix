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


DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]


def _french_date(moment: datetime) -> str:
    return f"{DAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}"


def render(state: dict, width: int = 800, height: int = 480) -> Image.Image:
    """Compose le tableau de bord complet à partir d'un instantané du service."""
    c = Canvas(width, height)
    now = datetime.now()
    margin = 22
    right_col_x = int(width * 0.60)

    # ------------------------------------------------------------------ en-tête
    c.text((margin, 18), _french_date(now), size=22, bold=True)
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
            c.text((margin, y), "PARS À", size=17, bold=True)
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
            badge_w = max(34, int(c.width_of(leg["line"], size=15, bold=True)) + 16)
            c.box((margin, y, margin + badge_w, y + 24), fill=BLACK, outline=BLACK, radius=5)
            c.text((margin + badge_w / 2, y + 12), leg["line"], size=15, bold=True,
                   fill=WHITE, anchor="mm")
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

    elif journeys:
        c.text((margin, y), "Aucun cours à venir", size=30, bold=True)
        y += 44
        upcoming = (journeys[0].get("upcoming") or [])[:3]
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
    y += 26

    for board in (state.get("boards") or [])[:4]:
        badge_w = max(32, int(c.width_of(board["line"], size=14, bold=True)) + 14)
        c.box((x, y, x + badge_w, y + 22), fill=BLACK, outline=BLACK, radius=4)
        c.text((x + badge_w / 2, y + 11), board["line"], size=14, bold=True,
               fill=WHITE, anchor="mm")
        c.text((x + badge_w + 10, y + 3), board.get("terminus", ""), size=13,
               max_w=width - x - badge_w - margin - 10)
        # Heures absolues : sur e-ink, un « dans 4 min » serait faux avant même d'être lu.
        times = "  ".join(n["at"] for n in (board.get("next") or [])[:4])
        theo = "" if board.get("realtime") else "  (théorique)"
        c.text((x + badge_w + 10, y + 24), times + theo, size=15, bold=True,
               max_w=width - x - badge_w - margin - 10)
        y += 52

    velo = state.get("velo") or []
    if velo and y < height - 130:
        y += 6
        c.text((x, y), "LEVÉLO", size=13, bold=True)
        y += 24
        for station in velo[:2]:
            c.text((x, y), station["name"], size=13, max_w=width - x - margin)
            c.text((x, y + 18), f"{station['bikes']} vélos · {station['docks']} bornes",
                   size=16, bold=True)
            y += 46

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
