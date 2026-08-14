# rtmpix

Les départs RTM et les vélos LeVélo de Marseille sur une horloge pixel **Ulanzi TC001**
(firmware [AWTRIX 3](https://github.com/Blueforcer/awtrix3)).

L'écran ne dit pas « le métro passe dans 4 minutes » — inutile quand la station est à sept
minutes à pied et deux minutes de couloirs. Il dit **combien de temps il te reste avant de
devoir partir** :

```
┌──────────────────────────────┐
│  M2 7m   ▓▓▓▓▓▓▓░░░░░░░░░░░  │   pars dans 7 minutes, tranquille
│  M1 GO   ▓░░░░░░░░░░░░░░░░░  │   maintenant (clignote)
│  M2 ~4m  ▓▓▓▓░░░░░░░░░░░░░░  │   le ~ signale un horaire théorique
│  3v 14b                      │   3 vélos, 14 bornes libres
└──────────────────────────────┘
```

Le calcul complet :

```
temps restant = départ − maintenant − (marche + entrée→quai + préparation)
```

---

## Ce qui rend le chiffre juste

**Le temps de marche vient d'un vrai routage piéton**, pas d'un vol d'oiseau majoré. Sur un
trajet test à Marseille : 1 150 m à vol d'oiseau, **1 350 m par les rues**. Le moteur par
défaut est Valhalla, qui tient compte du **dénivelé** — à Marseille, ce n'est pas un détail.
Le trajet ne bouge pas, donc il est calculé une fois puis mis en cache.

**Le temps entrée→quai est réglable station par station.** Il est quasi nul à La Rose ou
Saint-Just, il approche les deux minutes à Estrangin ou Réformés. Aucune donnée ouverte ne
le décrit : il se chronomètre, depuis le dashboard. Concrètement, sur un test réel :

| Station | Marche | Quai | Total porte-à-quai |
|---|---:|---:|---:|
| Rome Dragon | 10′31 | 20 s | **12′21** |
| Estrangin | 10′00 | 150 s | **14′00** |

Estrangin est *plus proche* à pied, et pourtant plus loin en vrai. Sans ce réglage, le
classement des lignes est faux.

**Le temps réel est distingué du théorique.** Quand la mesure terrain décroche — ce qui
arrive — le chiffre s'affiche préfixé d'un `~` au lieu de faire semblant.

---

## Sources de données

| Donnée | Source | Statut |
|---|---|---|
| Prochains passages | [`api-mobilite.rbgl.fr`](https://api-mobilite.rbgl.fr/api-docs/) — fusionne le temps réel SPOTI et le théorique | ✅ sans clé |
| Repli passages | `api.rtm.fr/front/spoti/getStationDetails` — le système des écrans de quai | ✅ sans clé, non documenté |
| Repli hors ligne | GTFS RTM théorique, compilé en SQLite | ✅ officiel |
| Perturbations | `api-mobilite.rbgl.fr` `/RTM/getDisruptions` | ✅ sans clé |
| Vélos | GBFS 2.2 LeVélo, Métropole AMP | ✅ officiel, sans clé |
| Routage piéton | Valhalla / OSRM publics (OpenStreetMap) | ✅ sans clé |

Les trois sources de passages sont essayées **en cascade** : si la première ne répond pas,
la deuxième prend le relais, et le GTFS local assure le service même sans réseau.

### Pourquoi pas le SIRI officiel

La Métropole publie des points d'accès SIRI sur
[transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/reseaux-de-transports-en-commun-de-la-metropole-daix-marseille-provence-et-des-bouches-du-rhone/)
avec `RequestorRef=open-data`. Sur l'endpoint RTM, `CheckStatus` répond correctement mais
toute requête `GetStopMonitoring` renvoie :

> `Unable to find service contract for open-data`

La même requête passe le contrôle de contrat sur d'autres réseaux de la métropole
(Aix-en-Bus par exemple) : le contrat n'est simplement pas ouvert côté RTM. D'où le recours
aux sources ci-dessus. Si la Métropole l'ouvre un jour, un quatrième provider SIRI se
branchera au même endroit.

### Sur les API non officielles

`api.rtm.fr` n'est pas documentée publiquement et peut changer sans préavis.
`api-mobilite.rbgl.fr` est un service tiers bénévole. rtmpix les interroge modérément —
trois stations au plus, toutes les trente secondes, en identifiant son `User-Agent` — et
retombe sur le GTFS local en cas d'indisponibilité. Merci à
[@augustin64](https://github.com/augustin64/lepilote) d'avoir documenté les points d'accès
RTM, et à Baptiste RUELLO-BABALONI pour l'API mobilité.

---

## Installation

### Proxmox, en une commande

Depuis le shell de l'hôte Proxmox :

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/install.sh)"
```

Le script crée un LXC Debian non privilégié (1 vCPU, 512 Mo, 4 Go), installe rtmpix,
compile le GTFS et enregistre le service systemd. Réglable par variables d'environnement :

```bash
CTID=210 RAM=1024 STORAGE=local-lvm bash -c "$(curl -fsSL .../install.sh)"
```

Il reste deux valeurs à renseigner dans `/opt/rtmpix/config.yaml` : `home.lat` / `home.lon`
et `awtrix.host`. Puis `systemctl start rtmpix`.

Mise à jour, depuis l'intérieur du conteneur :

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/update.sh)"
```

### À la main

```bash
git clone https://github.com/GaspardMenou/rtmpix && cd rtmpix
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml   # renseigner home.lat/lon et awtrix.host
.venv/bin/python -m rtmpix build     # ~3 s, télécharge et compile le GTFS
.venv/bin/python -m rtmpix run
```

Python 3.11 ou plus récent.

---

## Dashboard

`http://<ip-du-lxc>:8723` — il sert à trois choses :

- **voir** ce que l'horloge affiche, en simulation 32×8 ;
- **chronométrer** les temps d'accès aux quais, station par station ;
- **régler** l'allure de marche par rapport à celle du routeur.

Les valeurs mesurées vont dans `data/calibration.json` et priment sur `config.yaml`, qui
n'est jamais réécrit. Le dashboard n'a **pas d'authentification** : à garder sur le réseau
local (`web.enabled: false` pour le couper).

---

## Commandes

```bash
rtmpix build [--force]   # télécharge et compile le GTFS (à faire une fois, puis auto)
rtmpix stops             # stations du rayon, distances, marche, quai, total
rtmpix once [--push]     # une passe affichée en console
rtmpix check             # teste l'horloge et chaque source
rtmpix run               # boucle de service + dashboard
```

`rtmpix stops` est le point de départ du réglage :

```
Station                      Mode         Vol oiseau   Par rue   Marche   Quai    Total
›Noailles                    métro/tram        179 m     201 m     2′22   90s     5′22
›Rome Davso                  tram              215 m     310 m     3′42   20s     5′32
 Estrangin                   métro             592 m     849 m    10′00  150s    14′00
```

---

## Configuration

Tout est dans `config.example.yaml`, commenté. Les réglages qui comptent :

| Clé | Rôle |
|---|---|
| `home.lat` / `home.lon` | d'où tu pars à pied — le réglage le plus important |
| `transit.max_stations` | stations réellement interrogées (3 par défaut) |
| `transit.lines` | filtrer : `["M1", "T2>Blancarde"]` pour une ligne, voire un seul sens |
| `transit.access_s` | temps entrée→quai par station |
| `transit.route_types` | `[0, 1]` tram et métro ; ajouter `3` pour les bus |
| `walk.engine` | `valhalla` (dénivelé), `osrm`, ou `haversine` (hors ligne) |
| `walk.door_delay_s` | le temps de sortir de chez soi |
| `sources.realtime` | source primaire : `rbgl`, `spoti` ou `gtfs` |

Les noms de stations sont ceux du GTFS, tels que `rtmpix stops` les affiche. Attention :
**« Préfecture » s'appelle `Estrangin`** dans les données.

---

## Comment c'est fait

```
gtfs.py        télécharge le GTFS RTM, le compile en SQLite (225 k horaires en ~2 s)
stations.py    regroupe les quais par station, calcule le budget porte-à-quai
routing.py     routage piéton Valhalla/OSRM, avec cache disque
realtime.py    trois sources de passages en cascade
departures.py  agrège en tableaux par ligne et sens, calcule le compte à rebours
render.py      compose les écrans 32×8
awtrix.py      pousse vers l'horloge
web.py         dashboard de réglage
```

Le GTFS RTM ne renseigne pas `parent_station` : « Castellane », c'est dix `stop_id`
distincts. rtmpix les regroupe par nom et retient le quai le plus proche. Le lien avec les
API temps réel se fait par `ext_netex_id` (`RTM:PNT:00002313`), dont les cinq derniers
chiffres forment le code SPOTI — vérifié sans collision sur les 2 756 arrêts du réseau.

---

## Licence

MIT.
