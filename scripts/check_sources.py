#!/usr/bin/env python3
"""Vérifie que les sources externes répondent encore comme prévu.

C'est le vrai point de fragilité du projet : `api.rtm.fr` n'est pas documentée,
`api-mobilite.rbgl.fr` est un service bénévole, l'URL du GTFS peut changer de clé, et les
routeurs publics ont leurs propres aléas. Mieux vaut l'apprendre par une alerte que par une
horloge qui affiche n'importe quoi un lundi matin.

    python scripts/check_sources.py [--markdown rapport.md]

Sort en code 1 dès qu'une source obligatoire est en défaut.
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
HEADERS = {"User-Agent": "rtmpix-ci (verification des sources; +https://github.com/GaspardMenou/rtmpix)"}

GTFS_URL = "https://app.mecatran.com/utw/ws/gtfsfeed/static/mamp-rtm?apiKey=16421b08630a7d065c6d250051780f484b673659"
RBGL = "https://api-mobilite.rbgl.fr/api/v1"
SPOTI = "https://api.rtm.fr/front/spoti/getStationDetails"
GBFS_STATUS = "https://gbfs.omega.fifteen.eu/gbfs/2.2/marseille/en/station_status.json"
GBFS_INFO = "https://gbfs.omega.fifteen.eu/gbfs/2.2/marseille/en/station_information.json"

# Castellane : desservie par le métro, donc active toute la journée.
NETEX_REF = "RTM:PNT:00002313"
SPOTI_REF = "02313"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    required: bool = True


def check_gtfs() -> Result:
    """Le GTFS doit rester téléchargeable et contenir les fichiers qu'on compile."""
    try:
        resp = requests.get(GTFS_URL, headers=HEADERS, timeout=180)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = set(zf.namelist())
            missing = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
                       "calendar.txt"} - names
            if missing:
                return Result("GTFS RTM", False, f"fichiers manquants : {sorted(missing)}")
            header = zf.read("stops.txt").decode("utf-8-sig").splitlines()[0]
            if "ext_netex_id" not in header:
                return Result(
                    "GTFS RTM", False,
                    "la colonne ext_netex_id a disparu : le lien avec le temps réel est rompu",
                )
        return Result("GTFS RTM", True, f"{len(resp.content) / 1e6:.1f} Mo, colonnes attendues présentes")
    except Exception as exc:
        return Result("GTFS RTM", False, str(exc))


def check_rbgl_departures() -> Result:
    try:
        resp = requests.get(f"{RBGL}/RTM/getStopMonitoring",
                            params={"ext_netex_id": NETEX_REF}, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        departures = payload.get("departures")
        if departures is None:
            return Result("rbgl getStopMonitoring", False, "champ 'departures' absent de la réponse")
        if departures:
            first = departures[0]
            for key in ("line", "AimedDepartureTime"):
                if key not in first:
                    return Result("rbgl getStopMonitoring", False, f"champ '{key}' absent")
        return Result("rbgl getStopMonitoring", True, f"{len(departures)} passage(s) à Castellane")
    except Exception as exc:
        return Result("rbgl getStopMonitoring", False, str(exc))


def check_rbgl_disruptions() -> Result:
    try:
        resp = requests.get(f"{RBGL}/RTM/getDisruptions", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("disruptions") or []
        if not isinstance(payload, list):
            return Result("rbgl getDisruptions", False, "la réponse n'est pas une liste")
        return Result("rbgl getDisruptions", True, f"{len(payload)} perturbation(s)")
    except Exception as exc:
        return Result("rbgl getDisruptions", False, str(exc))


def check_spoti() -> Result:
    """Source de repli : sa perte n'est pas bloquante mais mérite d'être sue."""
    try:
        resp = requests.get(SPOTI, params={"nomPtReseau": SPOTI_REF},
                            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        tree = ElementTree.fromstring(resp.content)
        ns = "{http://ws/webbus/org/}"
        passages = tree.findall(f"{ns}passage")
        if tree.findtext(f"{ns}comLieu") is None:
            return Result("SPOTI api.rtm.fr", False, "structure XML inattendue", required=False)
        return Result("SPOTI api.rtm.fr", True, f"{len(passages)} passage(s)", required=False)
    except Exception as exc:
        return Result("SPOTI api.rtm.fr", False, str(exc), required=False)


def check_gbfs() -> Result:
    try:
        status = requests.get(GBFS_STATUS, headers=HEADERS, timeout=TIMEOUT)
        status.raise_for_status()
        info = requests.get(GBFS_INFO, headers=HEADERS, timeout=TIMEOUT)
        info.raise_for_status()
        stations = status.json()["data"]["stations"]
        first = stations[0]
        for key in ("station_id", "num_bikes_available", "num_docks_available"):
            if key not in first:
                return Result("GBFS LeVélo", False, f"champ '{key}' absent")
        named = info.json()["data"]["stations"][0]
        if "lat" not in named or "name" not in named:
            return Result("GBFS LeVélo", False, "station_information incomplet")
        return Result("GBFS LeVélo", True, f"{len(stations)} stations")
    except Exception as exc:
        return Result("GBFS LeVélo", False, str(exc))


def check_router(name: str, fn) -> Result:
    try:
        return fn()
    except Exception as exc:
        return Result(name, False, str(exc), required=False)


def check_valhalla() -> Result:
    body = {
        "locations": [{"lat": 43.29517, "lon": 5.38107}, {"lat": 43.28514, "lon": 5.38433}],
        "costing": "pedestrian",
        "directions_options": {"units": "kilometers"},
    }
    resp = requests.post("https://valhalla1.openstreetmap.de/route", json=body,
                         headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = json.JSONDecoder().raw_decode(resp.text)[0]
    summary = payload["trip"]["summary"]
    return Result("Valhalla piéton", True,
                  f"{round(summary['length'] * 1000)} m en {round(summary['time'])} s",
                  required=False)


def check_osrm() -> Result:
    resp = requests.get(
        "https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
        "5.38107,43.29517;5.38433,43.28514",
        params={"overview": "false"}, headers=HEADERS, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    route = resp.json()["routes"][0]
    return Result("OSRM piéton", True,
                  f"{round(route['distance'])} m en {round(route['duration'])} s", required=False)


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
        check_router("Valhalla piéton", check_valhalla),
        check_router("OSRM piéton", check_osrm),
    ]

    print(f"Vérification des sources — {datetime.now():%Y-%m-%d %H:%M}\n")
    for r in results:
        mark = "OK  " if r.ok else ("FAIL" if r.required else "warn")
        print(f"  [{mark}] {r.name:<26} {r.detail}")

    broken = [r for r in results if not r.ok and r.required]
    degraded = [r for r in results if not r.ok and not r.required]

    if args.markdown:
        lines = [
            "## Sources externes en défaut",
            "",
            f"Vérification du {datetime.now():%d/%m/%Y à %H:%M} UTC.",
            "",
            "| Source | État | Détail |",
            "|---|---|---|",
        ]
        for r in results:
            state = "✅" if r.ok else ("❌ **bloquant**" if r.required else "⚠️ dégradé")
            lines.append(f"| {r.name} | {state} | {r.detail[:160]} |")
        lines += [
            "",
            "Une source bloquante en défaut empêche l'affichage des passages ; les sources",
            "dégradées ne coupent que le repli ou le routage piéton (le cache prend le relais).",
        ]
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    if broken:
        print(f"\n{len(broken)} source(s) obligatoire(s) en défaut.")
        return 1
    if degraded:
        print(f"\n{len(degraded)} source(s) de repli en défaut, service assuré.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
