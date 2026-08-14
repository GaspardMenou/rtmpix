#!/usr/bin/env bash
# rtmpix — création d'un LXC Proxmox prêt à l'emploi.
#
# À lancer depuis le shell de l'hôte Proxmox :
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/install.sh)"
#
# Réglable par variables d'environnement :
#   CTID CT_HOSTNAME DISK CORES RAM BRIDGE STORAGE TEMPLATE_STORAGE PASSWORD REPO BRANCH

set -Eeuo pipefail

REPO="${REPO:-https://github.com/GaspardMenou/rtmpix}"
BRANCH="${BRANCH:-main}"
# HOSTNAME est déjà défini par bash (nom de l'hôte) : on utilise un nom distinct.
CT_HOSTNAME="${CT_HOSTNAME:-rtmpix}"
DISK="${DISK:-4}"
CORES="${CORES:-1}"
RAM="${RAM:-512}"
BRIDGE="${BRIDGE:-vmbr0}"
APP_DIR="/opt/rtmpix"

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; RST=$'\033[0m'
info() { echo "${BLU}  →${RST} $1"; }
ok()   { echo "${GRN}  ✓${RST} $1"; }
warn() { echo "${YLW}  !${RST} $1"; }
die()  { echo "${RED}  ✗ $1${RST}" >&2; exit 1; }

trap 'die "Interrompu ligne $LINENO. Le conteneur ${CTID:-?} peut être incomplet (pct destroy ${CTID:-?})."' ERR

echo
echo "${BLU}┌────────────────────────────────────────────┐${RST}"
echo "${BLU}│${RST}  ${GRN}rtmpix${RST} — départs RTM sur Ulanzi TC001   ${BLU}│${RST}"
echo "${BLU}└────────────────────────────────────────────┘${RST}"
echo

# ---------------------------------------------------------------- vérifications

[[ $EUID -eq 0 ]] || die "À lancer en root sur l'hôte Proxmox."
command -v pveversion >/dev/null 2>&1 || die "pveversion introuvable : ce script tourne sur l'hôte Proxmox, pas dans un conteneur."
info "$(pveversion | head -1)"

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
[[ -z "$(pct status "$CTID" 2>/dev/null || true)" ]] || die "Le CTID $CTID est déjà pris."

# Un stockage par usage : les templates et le disque racine ne vivent pas au même endroit.
pick_storage() {
  pvesm status -content "$1" 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}'
}
STORAGE="${STORAGE:-$(pick_storage rootdir)}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-$(pick_storage vztmpl)}"
[[ -n "$STORAGE" ]] || die "Aucun stockage actif pour les disques de conteneur (content=rootdir)."
[[ -n "$TEMPLATE_STORAGE" ]] || die "Aucun stockage actif pour les templates (content=vztmpl)."

echo
echo "  CTID ............ $CTID"
echo "  Nom ............. $CT_HOSTNAME"
echo "  Ressources ...... ${CORES} vCPU · ${RAM} Mo · ${DISK} Go"
echo "  Stockage ........ $STORAGE ${DIM}(templates : $TEMPLATE_STORAGE)${RST}"
echo "  Réseau .......... $BRIDGE, DHCP"
echo

if [[ -t 0 && "${ASSUME_YES:-0}" != "1" ]]; then
  read -rp "  Créer ce conteneur ? [O/n] " reply
  [[ -z "$reply" || "$reply" =~ ^[OoYy]$ ]] || die "Annulé."
fi
echo

# -------------------------------------------------------------------- template

info "Recherche du template Debian…"
pveam update >/dev/null 2>&1 || warn "Liste des templates non rafraîchie, on continue."
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-1[23]-standard' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || die "Aucun template Debian 12/13 disponible."

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  info "Téléchargement de $TEMPLATE…"
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE" >/dev/null
fi
ok "Template : $TEMPLATE"

# ------------------------------------------------------------------ conteneur

info "Création du conteneur $CTID…"
CREATE_ARGS=(
  --hostname "$CT_HOSTNAME"
  --cores "$CORES"
  --memory "$RAM"
  --swap 256
  --rootfs "$STORAGE:$DISK"
  --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp"
  --features nesting=1
  --unprivileged 1
  --onboot 1
  --ostype debian
  --timezone host
  --description "rtmpix — départs RTM et LeVélo sur Ulanzi TC001"
)
[[ -n "${PASSWORD:-}" ]] && CREATE_ARGS+=(--password "$PASSWORD")

pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" "${CREATE_ARGS[@]}" >/dev/null
ok "Conteneur créé"

info "Démarrage…"
pct start "$CTID" >/dev/null

# Sans réseau, tout ce qui suit échoue de façon illisible : on l'attend explicitement.
for _ in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  sleep 2
done
pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 || die "Le conteneur n'a pas obtenu de réseau."
ok "Réseau prêt"

# ----------------------------------------------------------------- installation

info "Installation des paquets (une minute environ)…"
pct exec "$CTID" -- bash -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip git ca-certificates tzdata >/dev/null
" || die "Installation des paquets échouée."
ok "Paquets installés"

info "Récupération de rtmpix…"
pct exec "$CTID" -- bash -c "
  set -e
  git clone --depth 1 --branch '$BRANCH' '$REPO' '$APP_DIR' >/dev/null 2>&1
  cd '$APP_DIR'
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  [ -f config.yaml ] || cp config.example.yaml config.yaml
  id rtmpix >/dev/null 2>&1 || useradd --system --home '$APP_DIR' --shell /usr/sbin/nologin rtmpix
  mkdir -p '$APP_DIR/data'
  chown -R rtmpix:rtmpix '$APP_DIR'
" || die "Installation de l'application échouée."
ok "Application installée dans $APP_DIR"

info "Compilation initiale du GTFS RTM…"
pct exec "$CTID" -- bash -c "
  cd '$APP_DIR' && sudo -u rtmpix .venv/bin/python -m rtmpix --config config.yaml build
" >/dev/null 2>&1 || warn "Compilation à relancer à la main (rtmpix build)."

info "Service systemd…"
pct exec "$CTID" -- bash -c "cat > /etc/systemd/system/rtmpix.service <<'UNIT'
[Unit]
Description=rtmpix — départs RTM sur Ulanzi TC001
Documentation=$REPO
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=rtmpix
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m rtmpix --config $APP_DIR/config.yaml run
Restart=always
RestartSec=10
# Le service n'a besoin d'écrire que dans son propre dossier de données.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/data

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable rtmpix >/dev/null 2>&1"
ok "Service enregistré"

IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"

echo
echo "${GRN}┌────────────────────────────────────────────┐${RST}"
echo "${GRN}│${RST}  Installation terminée                     ${GRN}│${RST}"
echo "${GRN}└────────────────────────────────────────────┘${RST}"
echo
echo "  Conteneur ....... $CTID ($CT_HOSTNAME) sur ${IP:-?}"
echo "  Dashboard ....... ${BLU}http://${IP:-<ip>}:8723${RST}"
echo
echo "  ${YLW}Il reste deux choses à renseigner avant de démarrer :${RST}"
echo "    ${DIM}pct exec $CTID -- nano $APP_DIR/config.yaml${RST}"
echo "      home.lat / home.lon  → les coordonnées de ton appart"
echo "      awtrix.host          → l'IP de l'Ulanzi TC001"
echo
echo "  Puis :"
echo "    ${DIM}pct exec $CTID -- systemctl start rtmpix${RST}"
echo "    ${DIM}pct exec $CTID -- journalctl -u rtmpix -f${RST}"
echo
echo "  Repérer les stations autour de chez toi :"
echo "    ${DIM}pct exec $CTID -- $APP_DIR/.venv/bin/python -m rtmpix --config $APP_DIR/config.yaml stops${RST}"
echo
