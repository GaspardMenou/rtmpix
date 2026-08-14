"""Dashboard local de réglage.

Sans authentification : à garder sur le réseau du LXC. Il sert à trois choses — voir ce
que l'horloge affiche, chronométrer les temps d'accès aux quais, et régler l'allure.
"""

from __future__ import annotations

import logging
import threading

from flask import Flask, jsonify, render_template, request

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
