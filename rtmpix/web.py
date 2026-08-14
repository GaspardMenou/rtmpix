"""Dashboard local de réglage.

Sans authentification : à garder sur le réseau du LXC. Il sert à trois choses — voir ce
que l'horloge affiche, chronométrer les temps d'accès aux quais, et régler l'allure.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

log = logging.getLogger(__name__)


def create_app(service) -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    @app.get("/")
    def index():
        return render_template("dashboard.html", home=service.cfg.home)

    @app.get("/api/state")
    def state():
        return jsonify(service.snapshot())

    @app.post("/api/calibration")
    def calibration():
        payload = request.get_json(silent=True) or {}
        station = payload.get("station")

        if "pace_factor" in payload:
            service.set_pace(payload["pace_factor"])
        if station and "access_s" in payload:
            value = payload["access_s"]
            service.set_access(station, None if value in ("", None) else int(value))
        if station and "walk_s" in payload:
            value = payload["walk_s"]
            service.set_walk(station, None if value in ("", None) else int(value))
        if station and "transfer_s" in payload:
            value = payload["transfer_s"]
            service.set_transfer(station, None if value in ("", None) else int(value))
            service.refresh_journeys()

        return jsonify(service.snapshot())

    @app.get("/api/geocode")
    def geocode():
        """Cherche un lieu par son nom : saisir des coordonnées à la main est ingrat."""
        places = service.geocoder.search(request.args.get("q", ""), limit=5)
        return jsonify([{"label": p.label, "lat": p.lat, "lon": p.lon} for p in places])

    @app.post("/api/destinations")
    def add_destination():
        payload = request.get_json(silent=True) or {}
        try:
            lat = float(payload.get("lat"))
            lon = float(payload.get("lon"))
        except (TypeError, ValueError):
            return jsonify({"error": "Coordonnées invalides."}), 400

        error = service.add_destination(
            name=payload.get("name", ""),
            lat=lat,
            lon=lon,
            calendar=payload.get("calendar", ""),
            location_filter=payload.get("location_filter", ""),
        )
        if error:
            return jsonify({"error": error}), 400
        # La découverte tourne en tâche de fond : l'état revient avec « en cours ».
        return jsonify(service.snapshot())

    @app.delete("/api/destinations/<name>")
    def remove_destination(name):
        error = service.remove_destination(name)
        if error:
            return jsonify({"error": error}), 400
        return jsonify(service.snapshot())

    @app.post("/api/reroute")
    def reroute():
        """Recalcule tous les trajets piétons en ignorant le cache."""
        service.reload_stations(refresh_routing=True)
        return jsonify(service.snapshot())

    @app.post("/api/push")
    def push():
        service.push()
        return jsonify({"ok": service.last_push_ok})

    # ------------------------------------------------------------------- e-ink

    def _render_eink():
        from . import eink

        cfg = service.cfg.eink
        image = eink.render(service.snapshot(), cfg.width, cfg.height)
        if cfg.rotate:
            image = image.rotate(cfg.rotate, expand=True)
        return image

    @app.get("/eink.png")
    def eink_png():
        from . import eink

        return Response(eink.to_png(_render_eink()), mimetype="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.get("/eink.bmp")
    def eink_bmp():
        from . import eink

        return Response(eink.to_bmp_1bit(_render_eink()), mimetype="image/bmp",
                        headers={"Cache-Control": "no-store"})

    @app.get("/eink.raw")
    def eink_raw():
        """Buffer 1 bit par pixel, pour un firmware qui ne veut décoder aucun format."""
        from . import eink

        return Response(eink.to_packed_1bpp(_render_eink()),
                        mimetype="application/octet-stream",
                        headers={"Cache-Control": "no-store"})

    # Protocole TRMNL « BYOS » : le panneau demande où trouver son image et quand revenir.
    # Écrit d'après la documentation publique, non vérifié sur un appareil réel.
    @app.get("/api/setup")
    @app.get("/api/setup/")
    def trmnl_setup():
        return jsonify({
            "status": 200,
            "api_key": "rtmpix-local",
            "friendly_id": "RTMPIX",
            "image_url": f"{request.url_root.rstrip('/')}/eink.bmp",
            "message": "rtmpix",
        })

    @app.get("/api/display")
    def trmnl_display():
        stamp = datetime.now().strftime("%Y%m%d%H%M")
        return jsonify({
            "status": 0,
            "image_url": f"{request.url_root.rstrip('/')}/eink.bmp?v={stamp}",
            "filename": f"rtmpix-{stamp}.bmp",
            "refresh_rate": service.cfg.eink.refresh_s,
            "reset_firmware": False,
            "update_firmware": False,
        })

    return app


def serve_in_background(service) -> threading.Thread | None:
    cfg = service.cfg.web
    if not cfg.enabled:
        return None
    app = create_app(service)

    def run() -> None:
        # Serveur de développement Flask : largement suffisant pour un usage local.
        app.run(host=cfg.host, port=cfg.port, threaded=True, use_reloader=False)

    thread = threading.Thread(target=run, name="rtmpix-web", daemon=True)
    thread.start()
    log.info("Dashboard sur http://%s:%d", cfg.host, cfg.port)
    return thread
