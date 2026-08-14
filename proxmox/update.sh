#!/usr/bin/env bash
# Mise à jour de rtmpix, à lancer À L'INTÉRIEUR du conteneur :
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/update.sh)"
#
# config.yaml et data/ ne sont jamais touchés.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/rtmpix}"
GRN=$'\033[32m'; BLU=$'\033[34m'; RED=$'\033[31m'; RST=$'\033[0m'
info() { echo "${BLU}  →${RST} $1"; }
ok()   { echo "${GRN}  ✓${RST} $1"; }
die()  { echo "${RED}  ✗ $1${RST}" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "À lancer en root dans le conteneur."
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR n'est pas un dépôt git — installation manuelle ?"

info "Arrêt du service…"
systemctl stop rtmpix 2>/dev/null || true

info "Récupération des sources…"
git -C "$APP_DIR" fetch --quiet origin
git -C "$APP_DIR" reset --hard --quiet "origin/$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"

info "Dépendances…"
"$APP_DIR/.venv/bin/pip" install -q --upgrade -r "$APP_DIR/requirements.txt"

chown -R rtmpix:rtmpix "$APP_DIR"

info "Redémarrage…"
systemctl daemon-reload
systemctl start rtmpix

sleep 2
systemctl is-active --quiet rtmpix && ok "rtmpix $(git -C "$APP_DIR" rev-parse --short HEAD) en service" \
  || die "Le service n'a pas redémarré : journalctl -u rtmpix -n 50"
