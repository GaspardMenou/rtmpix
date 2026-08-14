"""Point d'entrée : construction de la base, inspection, et boucle de service."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import date, datetime

from . import gtfs, render, web
from .config import load_config
from .realtime import PARIS
from .service import Service

log = logging.getLogger("rtmpix")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_build(cfg, args) -> int:
    changed = gtfs.ensure_db(cfg, force=args.force)
    meta = gtfs.db_meta(cfg.db_path)
    print(f"Base : {cfg.db_path}")
    print(f"  version du flux : {meta.get('feed_version', '?')}")
    print(f"  compilée le     : {meta.get('built_at', '?')}")
    print(f"  modes retenus   : {meta.get('route_types', '?')}")
    print("  état            :", "recompilée" if changed else "déjà à jour")
    return 0


def cmd_stops(cfg, args) -> int:
    if not cfg.db_path.exists():
        print("Base absente : lance d'abord `rtmpix build`.", file=sys.stderr)
        return 1
    from .calibration import Calibration
    from .routing import WalkRouter
    from .stations import find_nearby

    # Sans plafond : cette commande sert justement à voir tout ce que le rayon contient.
    found = find_nearby(
        gtfs.Database(cfg.db_path),
        cfg,
        WalkRouter(cfg, cfg.routing_cache_path),
        Calibration.load(cfg.calibration_path),
        limit=False,
    )
    print(f"Depuis {cfg.home.label} ({cfg.home.lat}, {cfg.home.lon}) — rayon {cfg.transit.radius_m} m\n")
    print(f"{'Station':<28} {'Mode':<12} {'Vol oiseau':>10} {'Par rue':>9} {'Marche':>8} {'Quai':>6} {'Total':>8}")
    print("-" * 88)
    for i, s in enumerate(found):
        total = s.lead_s(cfg.walk.overhead_s)
        mark = "›" if i < cfg.transit.max_stations else " "
        print(
            f"{mark}{s.name[:27]:<27} {s.mode_label[:12]:<12} {round(s.distance_m):>8} m "
            f"{round(s.route_walk_m):>7} m {s.walk_s // 60:>5}′{s.walk_s % 60:02d} "
            f"{s.access_s:>4}s {total // 60:>5}′{total % 60:02d}"
        )
    print(f"\n(total = marche + quai + {cfg.walk.overhead_s}s de préparation)")
    print(f"(› = les {cfg.transit.max_stations} stations réellement interrogées ; "
          f"ajuste transit.max_stations)")
    return 0


def cmd_once(cfg, args) -> int:
    if not cfg.db_path.exists():
        print("Base absente : lance d'abord `rtmpix build`.", file=sys.stderr)
        return 1
    service = Service(cfg)
    service.refresh_departures()
    service.refresh_velo()
    service.refresh_disruptions()

    now = datetime.now(PARIS)
    print(f"\n{now.strftime('%H:%M:%S')} — source : {service.realtime.last_source}\n")
    if service.boards:
        for board in service.boards:
            print(render.preview(board, now))
    else:
        print("  Aucun passage dans l'horizon.")

    if service.velo_stations:
        print()
        for v in service.velo_stations:
            print(f"  🚲 {v.name[:28]:<28} {v.bikes} vélos / {v.docks} bornes libres  ({v.walk_s // 60}′ à pied)")

    if service.disruptions:
        print()
        for d in service.disruptions:
            mark = "⚠" if d.critical else "·"
            print(f"  {mark} [{'/'.join(d.lines) or '?'}] {d.title}")

    if args.push:
        service.push()
        print(f"\nEnvoi vers l'horloge : {'ok' if service.last_push_ok else 'échec'}")
    return 0


def cmd_check(cfg, args) -> int:
    from .awtrix import Awtrix
    from .disruptions import DisruptionClient
    from .velo import VeloClient

    ok = True
    print("Base GTFS       :", "présente" if cfg.db_path.exists() else "ABSENTE (rtmpix build)")
    ok &= cfg.db_path.exists()

    if cfg.awtrix.enabled:
        stats = Awtrix(cfg).stats()
        print(f"Horloge {cfg.awtrix.host:<15}:", "ok" if stats else "INJOIGNABLE")
        if stats:
            print(f"  version {stats.get('version', '?')} · batterie {stats.get('bat', '?')}%")
        ok &= bool(stats)

    if cfg.velo.enabled:
        try:
            found = VeloClient(cfg).nearby()
            print(f"LeVélo          : ok ({len(found)} station(s) dans le rayon)")
        except Exception as exc:
            print(f"LeVélo          : ÉCHEC ({exc})")
            ok = False

    if cfg.disruptions.enabled:
        try:
            count = len(DisruptionClient(cfg).fetch())
            print(f"Perturbations   : ok ({count} en cours sur le réseau)")
        except Exception as exc:
            print(f"Perturbations   : ÉCHEC ({exc})")
            ok = False

    return 0 if ok else 1


def cmd_run(cfg, args) -> int:
    if not cfg.db_path.exists():
        log.info("Base absente, compilation initiale.")
        gtfs.ensure_db(cfg)

    service = Service(cfg)
    web.serve_in_background(service)

    stop = False

    def handle_stop(signum, frame):
        nonlocal stop
        log.info("Arrêt demandé.")
        stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    next_departures = next_velo = next_disruptions = next_push = 0.0
    last_gtfs_check: date | None = None

    while not stop:
        tick = time.monotonic()
        try:
            if tick >= next_departures:
                service.refresh_departures()
                next_departures = tick + cfg.refresh.departures_s
            if tick >= next_velo:
                service.refresh_velo()
                next_velo = tick + cfg.refresh.velo_s
            if tick >= next_disruptions:
                service.refresh_disruptions()
                next_disruptions = tick + cfg.disruptions.refresh_s
            if tick >= next_push:
                # On repousse plus souvent qu'on ne récupère : le compte à rebours doit
                # descendre à l'écran même entre deux interrogations des sources.
                service.push()
                next_push = tick + cfg.refresh.push_s

            today = datetime.now(PARIS)
            if (
                today.hour == cfg.refresh.gtfs_check_hour
                and last_gtfs_check != today.date()
            ):
                last_gtfs_check = today.date()
                if gtfs.ensure_db(cfg):
                    log.info("Nouveau GTFS, rechargement.")
                    service.conn = gtfs.Database(cfg.db_path)
                    service.reload_stations()
        except Exception:
            log.exception("Erreur dans la boucle, on continue.")

        time.sleep(1)

    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rtmpix", description="Départs RTM et LeVélo sur Ulanzi TC001")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="télécharge et compile le GTFS")
    p_build.add_argument("--force", action="store_true", help="recompile même si le flux n'a pas changé")
    sub.add_parser("stops", help="liste les stations proches et le budget de temps")
    p_once = sub.add_parser("once", help="une passe, affichée en console")
    p_once.add_argument("--push", action="store_true", help="envoie aussi vers l'horloge")
    sub.add_parser("check", help="teste les sources et l'horloge")
    sub.add_parser("run", help="boucle de service + dashboard")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(args.config)

    handlers = {
        "build": cmd_build,
        "stops": cmd_stops,
        "once": cmd_once,
        "check": cmd_check,
        "run": cmd_run,
    }
    return handlers[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
