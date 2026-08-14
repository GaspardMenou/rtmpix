"""Chargement et validation de la configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Temps entre l'entrée de la station et le quai, par mode GTFS. Le métro est le seul mode
# où ça pèse vraiment : couloirs, escalators, correspondances. Ces valeurs ne sont que des
# points de départ — le dashboard sert à les corriger station par station, au chrono.
DEFAULT_ACCESS_S = {
    0: 20,   # tram : on monte depuis le trottoir
    1: 90,   # métro : très variable, de 30 s à La Rose à 150 s à Réformés
    2: 120,  # train
    3: 10,   # bus
    4: 60,   # ferry
}


@dataclass
class Home:
    lat: float
    lon: float
    label: str = "Maison"


@dataclass
class Walk:
    # Moteur de routage piéton : valhalla (gère le dénivelé), osrm, ou haversine (hors ligne).
    engine: str = "valhalla"
    pace_factor: float = 1.0
    # Utilisés uniquement par le repli haversine, quand aucun routeur n'est joignable.
    speed_mps: float = 1.30
    detour_factor: float = 1.40
    door_delay_s: int = 60   # enfiler ses chaussures, descendre l'escalier de l'immeuble
    margin_s: int = 30       # marge avant fermeture des portes

    @property
    def overhead_s(self) -> int:
        return self.door_delay_s + self.margin_s


@dataclass
class Transit:
    radius_m: int = 900
    route_types: list[int] = field(default_factory=lambda: [0, 1])
    # Nombre de stations réellement interrogées à chaque tour. Le rayon peut en trouver
    # quinze ; en solliciter quinze toutes les trente secondes serait discourtois autant
    # qu'inutile — les plus proches sont les seules qu'on ira prendre.
    max_stations: int = 3
    max_lines: int = 4
    horizon_min: int = 90
    lines: list[str] = field(default_factory=list)
    access_s: dict[str, int] = field(default_factory=dict)


@dataclass
class Destination:
    """Un lieu où l'on doit arriver à l'heure, éventuellement piloté par un agenda."""

    name: str
    lat: float
    lon: float
    calendar: str = ""          # URL iCal ou chemin d'un fichier local
    location_filter: str = ""   # ne retenir que les séances dont le lieu contient ceci
    radius_m: int | None = None


@dataclass
class Journeys:
    enabled: bool = False
    destination_radius_m: int = 600   # rayon de recherche d'arrêts autour de la destination
    transfer_radius_m: int = 350      # au-delà, ce n'est plus une correspondance
    min_transfer_s: int = 120         # plancher : descendre, traverser, trouver le quai
    # Deux plafonds distincts : on garde beaucoup de candidats pour que le calcul horaire
    # puisse les départager à l'instant T, mais on n'en affiche que quelques-uns.
    max_patterns: int = 8             # itinéraires conservés pour le calcul
    max_options: int = 3              # itinéraires présentés
    # Plafonds exprimés en ARRÊTS et non en quais : un arrêt compte souvent deux quais,
    # et une école peut être desservie par plusieurs arrêts aux lignes différentes.
    max_origin_stations: int = 8
    max_dest_stations: int = 8
    arrive_margin_s: int = 300        # être sur place cinq minutes avant le début
    show_window_min: int = 150        # au-delà, le compte à rebours n'a pas sa place à l'écran
    calendar_refresh_s: int = 1800
    destinations: list[Destination] = field(default_factory=list)


@dataclass
class Reliability:
    """Marges de sécurité, mesurées plutôt que supposées.

    Un bus n'est pas un métro : il subit le trafic, se met en retard, et lui arrive aussi
    de passer en avance — auquel cas on le rate depuis le trottoir. On observe les écarts
    entre horaire annoncé et horaire réel, ligne par ligne, et on en déduit la marge.
    """

    enabled: bool = True
    percentile: int = 80        # on absorbe le retard rencontré 4 fois sur 5
    min_samples: int = 20       # en deçà, la mesure ne vaut rien : on garde le défaut du mode
    retention_days: int = 30
    # Marges par mode GTFS tant qu'une ligne n'a pas assez d'observations (secondes).
    default_margin_s: dict[int, int] = field(
        default_factory=lambda: {0: 60, 1: 30, 2: 120, 3: 150, 4: 120}
    )


@dataclass
class Sources:
    realtime: str = "rbgl"
    rbgl_base: str = "https://api-mobilite.rbgl.fr/api/v1"
    spoti_url: str = "https://api.rtm.fr/front/spoti/getStationDetails"
    timeout_s: int = 8
    user_agent: str = "rtmpix/0.1 (horloge perso)"


@dataclass
class Disruptions:
    enabled: bool = True
    refresh_s: int = 300
    only_my_lines: bool = True
    critical_only: bool = False


@dataclass
class Velo:
    enabled: bool = True
    radius_m: int = 700
    stations: int = 1


@dataclass
class Awtrix:
    host: str
    enabled: bool = True
    timeout_s: int = 5
    app_prefix: str = "rtm"
    duration_s: int = 8
    lifetime_s: int = 180


@dataclass
class Web:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8723


@dataclass
class Eink:
    """Panneau e-ink 7,5″ : TRMNL, XIAO ePaper, ou tout ce qui sait afficher une image."""

    enabled: bool = True
    width: int = 800
    height: int = 480
    rotate: int = 0        # 0, 90, 180 ou 270 selon le montage du panneau
    refresh_s: int = 900   # cadence annoncée au panneau ; il dort entre deux réveils


@dataclass
class Refresh:
    departures_s: int = 30   # interrogation des sources
    push_s: int = 10         # réémission vers l'horloge, pour que le compte à rebours descende
    velo_s: int = 60
    gtfs_check_hour: int = 4


@dataclass
class Gtfs:
    url: str
    data_dir: Path = Path("./data")


@dataclass
class VeloGbfs:
    station_information: str
    station_status: str


@dataclass
class Config:
    home: Home
    walk: Walk
    transit: Transit
    journeys: Journeys
    reliability: Reliability
    sources: Sources
    disruptions: Disruptions
    velo: Velo
    awtrix: Awtrix
    web: Web
    eink: Eink
    refresh: Refresh
    gtfs: Gtfs
    velo_gbfs: VeloGbfs

    @property
    def db_path(self) -> Path:
        return self.gtfs.data_dir / "rtm.sqlite"

    @property
    def zip_path(self) -> Path:
        return self.gtfs.data_dir / "rtm-gtfs.zip"

    @property
    def routing_cache_path(self) -> Path:
        return self.gtfs.data_dir / "routing-cache.json"

    @property
    def calibration_path(self) -> Path:
        return self.gtfs.data_dir / "calibration.json"

    @property
    def punctuality_path(self) -> Path:
        return self.gtfs.data_dir / "punctuality.sqlite"


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Section '{key}' invalide dans la config")
    return value


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"Config introuvable : {path}\n"
            "Copie config.example.yaml en config.yaml et renseigne au minimum "
            "home.lat / home.lon et awtrix.host."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    home_raw = _section(raw, "home")
    if "lat" not in home_raw or "lon" not in home_raw:
        raise SystemExit("home.lat et home.lon sont obligatoires.")

    awtrix_raw = _section(raw, "awtrix")
    if awtrix_raw.get("enabled", True) and not awtrix_raw.get("host"):
        raise SystemExit("awtrix.host est obligatoire (IP de l'Ulanzi TC001).")
    awtrix_raw.setdefault("host", "")

    gtfs_raw = _section(raw, "gtfs")
    data_dir = Path(gtfs_raw.get("data_dir", "./data"))
    if not data_dir.is_absolute():
        data_dir = (path.parent / data_dir).resolve()

    sources = Sources(**_section(raw, "sources"))
    if sources.realtime not in ("rbgl", "spoti", "gtfs"):
        raise SystemExit("sources.realtime doit valoir rbgl, spoti ou gtfs.")

    walk = Walk(**_section(raw, "walk"))
    if walk.engine not in ("valhalla", "osrm", "haversine"):
        raise SystemExit("walk.engine doit valoir valhalla, osrm ou haversine.")

    journeys_raw = dict(_section(raw, "journeys"))
    destinations = []
    for item in journeys_raw.pop("destinations", None) or []:
        if not isinstance(item, dict) or "lat" not in item or "lon" not in item:
            raise SystemExit("Chaque journeys.destinations doit avoir au moins name, lat et lon.")
        destinations.append(Destination(**item))
    journeys = Journeys(**journeys_raw, destinations=destinations)
    if journeys.enabled and not destinations:
        raise SystemExit("journeys.enabled vaut true mais aucune destination n'est définie.")

    return Config(
        home=Home(**home_raw),
        walk=walk,
        transit=Transit(**_section(raw, "transit")),
        journeys=journeys,
        reliability=Reliability(**_section(raw, "reliability")),
        sources=sources,
        disruptions=Disruptions(**_section(raw, "disruptions")),
        velo=Velo(**_section(raw, "velo")),
        awtrix=Awtrix(**awtrix_raw),
        web=Web(**_section(raw, "web")),
        eink=Eink(**_section(raw, "eink")),
        refresh=Refresh(**_section(raw, "refresh")),
        gtfs=Gtfs(url=gtfs_raw["url"], data_dir=data_dir),
        velo_gbfs=VeloGbfs(**_section(raw, "velo_gbfs")),
    )
