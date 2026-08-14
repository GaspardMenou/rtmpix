#!/usr/bin/env python3
"""Vérifie que les sources externes répondent encore comme prévu.

C'est le vrai point de fragilité du projet : `api.rtm.fr` n'est pas documentée,
`api-mobilite.rbgl.fr` est un service bénévole, l'URL du GTFS peut changer de clé, et les
routeurs publics ont leurs propres aléas. Mieux vaut l'apprendre par une alerte que par une
horloge qui affiche n'importe quoi un lundi matin.

    python scripts/check_sources.py [--markdown rapport.md]

On ne se contente pas d'un code 200 : on vérifie que les champs dont dépend le code sont
toujours là. Une API qui répond joyeusement sans le champ `ExpectedDepartureTime` est plus
dangereuse qu'une API éteinte.

Sort en code 1 uniquement si une source indispensable est réellement en panne.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree

import requests

TIMEOUT = 25
HEADERS = {
    "User-Agent": "rtmpix-ci (verification des sources; +https://github.com/GaspardMenou/rtmpix)"
}

GTFS_URL = (
    "https://app.mecatran.com/utw/ws/gtfsfeed/static/mamp-rtm"
    "?apiKey=16421b08630a7d065c6d250051780f484b673659"
)
RBGL = "https://api-mobilite.rbgl.fr/api/v1"
SPOTI = "https://api.rtm.fr/front/spoti/getStationDetails"
GBFS_STATUS = "https://gbfs.omega.fifteen.eu/gbfs/2.2/marseille/en/station_status.json"
GBFS_INFO = "https://gbfs.omega.fifteen.eu/gbfs/2.2/marseille/en/station_information.json"

# Castellane : desservie par le métro, donc animée toute la journée.
NETEX_REF = "RTM:PNT:00002313"
SPOTI_REF = "02313"

# Quatre états, parce que « ne répond pas » recouvre des situations très différentes.
OK = "ok"              # la source répond et sa structure est celle attendue
FAIL = "fail"          # panne ou contrat rompu sur une source indispensable → il faut agir
DEGRADED = "degraded"  # une source de repli est tombée ; le service tient, le filet est plus fin
BLOCKED = "blocked"    # accès refusé depuis un datacenter : ni panne, ni succès

MARKS = {OK: "OK  ", FAIL: "FAIL", DEGRADED: "warn", BLOCKED: "bloq"}
BADGES = {
    OK: "✅",
    FAIL: "❌ **panne**",
    DEGRADED: "⚠️ dégradé",
    BLOCKED: "🔒 accès refusé depuis la CI",
}


@dataclass
class Result:
    name: str
    state: str
    detail: str


def _classify(exc: Exception, required: bool) -> str:
    """Un refus d'accès n'est pas une panne.

    rbgl bloque les adresses des runners GitHub alors qu'il répond parfaitement depuis une
    connexion domestique : alerter là-dessus reviendrait à crier au loup chaque lundi.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403, 429):
        return BLOCKED
    return FAIL if required else DEGRADED


def check_gtfs() -> Result:
    """Le GTFS doit rester téléchargeable et contenir ce qu'on compile."""
    try:
        resp = requests.get(GTFS_URL, headers=HEADERS, timeout=180)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            expected = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt"}
            missing = expected - set(zf.namelist())
            if missing:
                return Result("GTFS RTM", FAIL, f"fichiers manquants : {sorted(missing)}")
            header = zf.read("stops.txt").decode("utf-8-sig").splitlines()[0]
            if "ext_netex_id" not in header:
                return Result(
                    "GTFS RTM", FAIL,
                    "la colonne ext_netex_id a disparu : le lien avec le temps réel est rompu",
                )
        return Result("GTFS RTM", OK, f"{len(resp.content) / 1e6:.1f} Mo, colonnes attendues présentes")
    except Exception as exc:
        return Result("GTFS RTM", _classify(exc, True), str(exc))


def check_rbgl_departures() -> Result:
    try:
        resp = requests.get(f"{RBGL}/RTM/getStopMonitoring",
                            params={"ext_netex_id": NETEX_REF}, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        departures = resp.json().get("departures")
        if departures is None:
            return Result("rbgl getStopMonitoring", FAIL, "champ 'departures' absent de la réponse")
        if departures:
            for key in ("line", "AimedDepartureTime"):
                if key not in departures[0]:
                    return Result("rbgl getStopMonitoring", FAIL, f"champ '{key}' absent")
        return Result("rbgl getStopMonitoring", OK, f"{len(departures)} passage(s) à Castellane")
    except Exception as exc:
        return Result("rbgl getStopMonitoring", _classify(exc, True), str(exc))


def check_rbgl_disruptions() -> Result:
    try:
        resp = requests.get(f"{RBGL}/RTM/getDisruptions", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("disruptions") or []
        if not isinstance(payload, list):
            return Result("rbgl getDisruptions", FAIL, "la réponse n'est pas une liste")
        return Result("rbgl getDisruptions", OK, f"{len(payload)} perturbation(s)")
    except Exception as exc:
        return Result("rbgl getDisruptions", _classify(exc, True), str(exc))


def check_spoti() -> Result:
    """Source de repli : sa perte n'interrompt rien, mais mérite d'être sue."""
    try:
        resp = requests.get(SPOTI, params={"nomPtReseau": SPOTI_REF},
                            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        tree = ElementTree.fromstring(resp.content)
        ns = "{http://ws/webbus/org/}"
        if tree.findtext(f"{ns}comLieu") is None:
            return Result("SPOTI api.rtm.fr", DEGRADED, "structure XML inattendue")
        return Result("SPOTI api.rtm.fr", OK, f"{len(tree.findall(f'{ns}passage'))} passage(s)")
    except Exception as exc:
        return Result("SPOTI api.rtm.fr", _classify(exc, False), str(exc))


def check_gbfs() -> Result:
    try:
        status = requests.get(GBFS_STATUS, headers=HEADERS, timeout=TIMEOUT)
        status.raise_for_status()
        info = requests.get(GBFS_INFO, headers=HEADERS, timeout=TIMEOUT)
        info.raise_for_status()
        stations = status.json()["data"]["stations"]
        for key in ("station_id", "num_bikes_available", "num_docks_available"):
            if key not in stations[0]:
                return Result("GBFS LeVélo", FAIL, f"champ '{key}' absent")
        named = info.json()["data"]["stations"][0]
        if "lat" not in named or "name" not in named:
            return Result("GBFS LeVélo", FAIL, "station_information incomplet")
        return Result("GBFS LeVélo", OK, f"{len(stations)} stations")
    except Exception as exc:
        return Result("GBFS LeVélo", _classify(exc, True), str(exc))


def check_valhalla() -> Result:
    body = {
        "locations": [{"lat": 43.29517, "lon": 5.38107}, {"lat": 43.28514, "lon": 5.38433}],
        "costing": "pedestrian",
        "directions_options": {"units": "kilometers"},
    }
    try:
        resp = requests.post("https://valhalla1.openstreetmap.de/route", json=body,
                             headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        # Le serveur public ajoute parfois du contenu après le document JSON.
        summary = json.JSONDecoder().raw_decode(resp.text)[0]["trip"]["summary"]
        return Result("Valhalla piéton", OK,
                      f"{round(summary['length'] * 1000)} m en {round(summary['time'])} s")
    except Exception as exc:
        return Result("Valhalla piéton", _classify(exc, False), str(exc))


def check_osrm() -> Result:
    try:
        resp = requests.get(
            "https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
            "5.38107,43.29517;5.38433,43.28514",
            params={"overview": "false"}, headers=HEADERS, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        route = resp.json()["routes"][0]
        return Result("OSRM piéton", OK,
                      f"{round(route['distance'])} m en {round(route['duration'])} s")
    except Exception as exc:
        return Result("OSRM piéton", _classify(exc, False), str(exc))


def write_markdown(path: str, results: list[Result]) -> None:
    lines = [
        "## État des sources externes",
        "",
        f"Vérification du {datetime.now():%d/%m/%Y à %H:%M} UTC.",
        "",
        "| Source | État | Détail |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {BADGES[r.state]} | {r.detail[:160]} |")
    lines += [
        "",
        "Une source **en panne** empêche l'affichage des passages. Une source **dégradée**",
        "ne coupe qu'un repli ou le routage piéton, dont le cache prend le relais.",
        "Un **accès refusé** vient des adresses de runners GitHub et ne dit rien de l'état",
        "réel du service ; à vérifier depuis une connexion domestique.",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", help="écrit un rapport Markdown dans ce fichier")
    args = parser.parse_args()

    results = [
        check_gtfs(),
        check_rbgl_departures(),
        check_rbgl_disruptions(),
        check_spoti(),
        check_gbfs(),
        check_valhalla(),
        check_osrm(),
    ]

    print(f"Vérification des sources — {datetime.now():%Y-%m-%d %H:%M}\n")
    for r in results:
        print(f"  [{MARKS[r.state]}] {r.name:<26} {r.detail}")

    broken = [r for r in results if r.state == FAIL]
    degraded = [r for r in results if r.state == DEGRADED]
    blocked = [r for r in results if r.state == BLOCKED]

    if args.markdown:
        write_markdown(args.markdown, results)

    print()
    if blocked:
        print(f"{len(blocked)} source(s) inaccessibles depuis cette machine (403/429) : "
              "à vérifier depuis une connexion domestique.")
    if degraded:
        print(f"{len(degraded)} source(s) de repli en défaut, service assuré.")
    if broken:
        print(f"{len(broken)} source(s) indispensable(s) en panne.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
