#!/usr/bin/env bash
# rtmpix — LXC Proxmox dédié, faisant tourner le service dans Docker.
#
# À lancer depuis le shell de l'hôte Proxmox :
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/install-docker.sh)"
#
# Variante de install.sh : même conteneur, mais le service tourne dans Docker plutôt qu'en
# systemd. À préférer si tu gères déjà tes services en conteneurs — la mise à jour se
# résume alors à `docker compose pull && up -d`.
#
# Sur la sécurité, une précision qui va à rebours de l'intuition : faire tourner Docker
# dans un LXC impose `nesting=1`, qui ASSOUPLIT le profil AppArmor du conteneur. On ajoute
# une couche d'isolation tout en desserrant celle du dessous ; le résultat net vaut à peu
# près un LXC non privilégié sans nesting. Le gain réel de cette variante est la
# reproductibilité, pas le cloisonnement.
#
# Ce script garde donc le conteneur NON PRIVILÉGIÉ et n'y touche pas à AppArmor. Beaucoup
# de tutoriels conseillent `lxc.apparmor.profile: unconfined` pour faire tourner Docker en
# LXC : c'est inutile ici, et cela supprimerait pour de bon l'isolation recherchée.
#
# Réglable par variables d'environnement :
#   CTID CT_HOSTNAME DISK CORES RAM BRIDGE STORAGE TEMPLATE_STORAGE PASSWORD REPO BRANCH

set -Eeuo pipefail

REPO="${REPO:-https://github.com/GaspardMenou/rtmpix}"
BRANCH="${BRANCH:-main}"
# HOSTNAME est déjà défini par bash (nom de l'hôte) : on utilise un nom distinct.
CT_HOSTNAME="${CT_HOSTNAME:-rtmpix}"
# Plus grand que la variante systemd : l'image Docker et le cache de couches s'ajoutent
# aux 194 Mo de la base GTFS compilée.
DISK="${DISK:-8}"
CORES="${CORES:-2}"
RAM="${RAM:-1024}"
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
echo "${BLU}│${RST}  ${GRN}rtmpix${RST} — LXC + Docker                   ${BLU}│${RST}"
echo "${BLU}└────────────────────────────────────────────┘${RST}"
echo

# ---------------------------------------------------------------- vérifications

[[ $EUID -eq 0 ]] || die "À lancer en root sur l'hôte Proxmox."
command -v pveversion >/dev/null 2>&1 || die "pveversion introuvable : ce script tourne sur l'hôte Proxmox, pas dans un conteneur."
info "$(pveversion | head -1)"

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
[[ -z "$(pct status "$CTID" 2>/dev/null || true)" ]] || die "Le CTID $CTID est déjà pris."

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
echo "  Isolation ....... non privilégié, nesting + keyctl, AppArmor conservé"
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
# keyctl=1 est ce qui permet à Docker de tourner dans un conteneur NON privilégié sans
# désactiver AppArmor ; nesting=1 autorise l'imbrication de conteneurs.
CREATE_ARGS=(
  --hostname "$CT_HOSTNAME"
  --cores "$CORES"
  --memory "$RAM"
  --swap 512
  --rootfs "$STORAGE:$DISK"
  --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp"
  --features "nesting=1,keyctl=1"
  --unprivileged 1
  --onboot 1
  --ostype debian
  --timezone host
  --description "rtmpix — départs RTM et LeVélo, dans Docker"
)
[[ -n "${PASSWORD:-}" ]] && CREATE_ARGS+=(--password "$PASSWORD")

pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" "${CREATE_ARGS[@]}" >/dev/null
ok "Conteneur créé (non privilégié)"

info "Démarrage…"
pct start "$CTID" >/dev/null

for _ in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  sleep 2
done
pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 || die "Le conteneur n'a pas obtenu de réseau."
ok "Réseau prêt"

# --------------------------------------------------------------------- docker

info "Installation de Docker (deux à trois minutes)…"
pct exec "$CTID" -- bash -c "
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends ca-certificates curl git gnupg >/dev/null
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian \$(. /etc/os-release && echo \$VERSION_CODENAME) stable\" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
" || die "Installation de Docker échouée."

# Un stockage en vfs signale que le noyau refuse overlay2 dans ce conteneur : Docker
# fonctionnera, mais en occupant plusieurs fois la place et en construisant lentement.
DRIVER="$(pct exec "$CTID" -- docker info --format '{{.Driver}}' 2>/dev/null || echo '?')"
if [[ "$DRIVER" == "vfs" ]]; then
  warn "Docker utilise le pilote vfs : lent et gourmand en disque."
  warn "Vérifie que le conteneur a bien les features nesting=1,keyctl=1."
else
  ok "Docker installé (stockage : $DRIVER)"
fi

# ---------------------------------------------------------------------- rtmpix

info "Récupération de rtmpix et construction de l'image…"
pct exec "$CTID" -- bash -c "
  set -e
  git clone --depth 1 --branch '$BRANCH' '$REPO' '$APP_DIR' >/dev/null 2>&1
  cd '$APP_DIR'
  [ -f config.yaml ] || cp config.example.yaml config.yaml
  docker compose build >/dev/null
" || die "Construction de l'image échouée."
ok "Image construite"

IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"

echo
echo "${GRN}┌────────────────────────────────────────────┐${RST}"
echo "${GRN}│${RST}  Installation terminée                     ${GRN}│${RST}"
echo "${GRN}└────────────────────────────────────────────┘${RST}"
echo
echo "  Conteneur ....... $CTID ($CT_HOSTNAME) sur ${IP:-?}"
echo "  Dashboard ....... ${BLU}http://${IP:-<ip>}:8723${RST} ${DIM}(une fois démarré)${RST}"
echo
echo "  ${YLW}Le service n'est pas encore lancé : deux valeurs sont à renseigner.${RST}"
echo "    ${DIM}pct exec $CTID -- nano $APP_DIR/config.yaml${RST}"
echo "      home.lat / home.lon  → les coordonnées de ton appart"
echo "      awtrix.host          → l'IP de l'Ulanzi TC001"
echo
echo "  Puis, depuis $APP_DIR :"
echo "    ${DIM}pct exec $CTID -- docker compose -f $APP_DIR/docker-compose.yml up -d${RST}"
echo "    ${DIM}pct exec $CTID -- docker compose -f $APP_DIR/docker-compose.yml logs -f${RST}"
echo
echo "  Le premier démarrage télécharge et compile le GTFS : compte deux minutes"
echo "  avant que le dashboard réponde."
echo
echo "  Mise à jour ultérieure :"
echo "    ${DIM}pct exec $CTID -- git -C $APP_DIR pull${RST}"
echo "    ${DIM}pct exec $CTID -- docker compose -f $APP_DIR/docker-compose.yml up -d --build${RST}"
echo
