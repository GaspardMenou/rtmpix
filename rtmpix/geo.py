"""Distances et conversion distance -> temps de marche."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau en mètres."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def walk_seconds(distance_m: float, speed_mps: float, detour_factor: float) -> int:
    """Temps de marche estimé, en secondes.

    On majore la distance à vol d'oiseau par un facteur de détour : sans moteur de
    routage, c'est l'approximation la moins mauvaise. Un `walk_overrides` mesuré au
    chrono reste toujours meilleur.
    """
    return int(round(distance_m * detour_factor / speed_mps))
