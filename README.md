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

## Trajets avec correspondance et heure limite

Le vrai besoin n'est pas « quand passe le prochain métro » mais **« j'ai jusqu'à quelle
heure avant d'être en retard en cours »**. rtmpix lit l'emploi du temps iCal de l'école,
prend le prochain cours, et calcule **à rebours** :

```
cours à 8h00  →  être là 7h55  →  dernier bus qui arrive à temps
              →  dernier métro pour l'attraper  →  PARS À 07:21
```

Les itinéraires ne se configurent pas : ils se découvrent. À partir du domicile et des
coordonnées de la destination, rtmpix énumère les enchaînements de lignes possibles (une
correspondance au plus) et garde les meilleurs :

```
$ rtmpix journey

  Itinéraires possibles (3) :
    M1 › B3      ~23′  8′ à pied · M1 Cinq Avenues → La Rose · corresp. 2′ · B3 Métro La Rose → Technopôle Centrale Med · 2′ à pied
    M1 › 142     ~25′  …
    M1 › 1       ~25′  …

  Prochain cours : Mécanique des fluides - CM
    lundi 17/08 à 08:00 · Centrale Méditerranée - Amphi 1

  → M1 › B3    PARS À 07:21 (dans 42′)   arrivée 07:52
       07:31 M1   Cinq Avenues Longchamp → 07:39 La Rose
       07:48 B3   Métro La Rose          → 07:50 Technopôle Centrale Med
```

Les itinéraires suivants ne sont pas du décor : ce sont les plans B quand une ligne saute.

**Une correspondance ne se détecte pas par le nom.** À La Rose, le quai du métro s'appelle
`La Rose` et l'arrêt de bus `Métro La Rose`, et selon le quai ils sont distants de 3 à
500 m. rtmpix apparie donc les arrêts géométriquement, et le temps de correspondance se
règle au chronomètre depuis le dashboard — c'est souvent lui qui décide. Exemple mesuré :
en passant la correspondance de 120 s à 240 s, le B3 tient toujours 07:21 (il passe toutes
les 2 min), mais les lignes 1 et 142 reculent à 07:14.

## Plusieurs itinéraires, et la fiabilité de chacun

Une destination est rarement desservie par un seul arrêt. Centrale Méditerranée a
*Technopôle Centrale Med* à 150 m (B3 seul) et *Einstein Monnet* à 270 m (lignes 1, 62,
142) — sans compter les variantes au départ. rtmpix énumère tout, garde huit itinéraires
candidats et répond à **deux questions différentes** :

| Question | Réponse |
|---|---|
| Le plus rapide en partant maintenant | `M1 › B3`, arrivée 19:56, 35′ porte à porte |
| Le plus tard sans être en retard | `42 › B3`, pars à 07:23 |

Ce ne sont pas les mêmes itinéraires, et c'est normal : partir au plus tard et arriver au
plus vite sont deux optimisations distinctes.

**Un bus n'est pas un métro.** Plutôt qu'une constante au jugé, rtmpix mesure : l'API
fournit pour chaque passage l'horaire annoncé *et* l'horaire réel, et leur écart est la
ponctualité du moment. Relevés à Marseille :

| Ligne | Mode | Écart médian |
|---|---|---:|
| T2 | tram | **+15 s** |
| 7B | bus | **+146 s** |
| 7 | bus | **+182 s** |

Ces écarts alimentent deux marges par ligne, qui ne jouent pas au même endroit : le
**retard** fait viser une course plus tôt, l'**avance** fait arriver au quai plus tôt —
c'est elle qui fait rater un bus depuis le trottoir. Une course n'est comptée qu'une fois
même si elle est vue à chaque rafraîchissement, et sous 20 relevés la marge du mode
s'applique. Le tout est visible et réglable dans le dashboard.

## Écran e-ink

Le service produit aussi une image 800×480 pour un panneau e-ink 7,5″ (TRMNL, XIAO ePaper
Panel, ou tout ce qui sait afficher un BMP) :

| Endpoint | Usage |
|---|---|
| `/eink.png` | aperçu dans un navigateur |
| `/eink.bmp` | BMP 1 bit, ce qu'attendent les panneaux |
| `/eink.raw` | buffer 1 bpp brut (48 000 octets), pour un firmware ESP32 minimal |
| `/api/display` | protocole TRMNL « BYOS » (écrit d'après la doc, **non vérifié sur matériel**) |

Un e-ink se rafraîchit toutes les cinq à quinze minutes : **on n'y met jamais de compte à
rebours**, qui serait faux avant même d'être lu. Il affiche des heures absolues (« PARS À
07:21 »), le détail du trajet, les prochains passages et les perturbations. L'horloge dit
l'urgence, l'e-ink dit le plan.

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

Depuis le shell de l'hôte Proxmox, au choix :

```bash
# LXC + service systemd — le plus léger
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/install.sh)"

# LXC + Docker — si tu gères déjà tes services en conteneurs
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/install-docker.sh)"
```

**Une précision à contre-courant de l'intuition sur la seconde variante** : faire tourner
Docker dans un LXC impose `nesting=1`, qui *assouplit* le profil AppArmor du conteneur. On
ajoute une couche d'isolation tout en desserrant celle du dessous — le résultat net vaut à
peu près un LXC non privilégié sans nesting. Le gain réel de Docker ici est la
reproductibilité et la simplicité de mise à jour, ce qui reste une bonne raison ; ce n'est
simplement pas un gain de cloisonnement.

Le script garde le conteneur **non privilégié** et ne touche pas à AppArmor : `keyctl=1`
suffit à faire tourner Docker sans cela. Beaucoup de tutoriels recommandent
`lxc.apparmor.profile: unconfined` — c'est inutile ici et cela supprimerait pour de bon
l'isolation recherchée. Le script vérifie aussi le pilote de stockage retenu : un `vfs`
signalerait qu'`overlay2` est refusé, et donc un Docker lent et gourmand en disque.

Le premier script crée un LXC Debian non privilégié (1 vCPU, 512 Mo, 4 Go), installe
rtmpix, compile le GTFS et enregistre le service systemd. Réglable par variables
d'environnement :

```bash
CTID=210 RAM=1024 STORAGE=local-lvm bash -c "$(curl -fsSL .../install.sh)"
```

Il reste deux valeurs à renseigner dans `/opt/rtmpix/config.yaml` : `home.lat` / `home.lon`
et `awtrix.host`. Puis `systemctl start rtmpix`.

Mise à jour, depuis l'intérieur du conteneur :

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/GaspardMenou/rtmpix/main/proxmox/update.sh)"
```

### Docker

```bash
cp config.example.yaml config.yaml   # renseigner home.lat/lon et awtrix.host
docker compose up -d
```

**Le réseau ne demande rien de particulier.** rtmpix n'émet que des requêtes HTTP
sortantes, y compris vers l'horloge : joindre `192.168.x.x` depuis un conteneur en bridge
passe par la passerelle et fonctionne tel quel. `network_mode: host` ne servirait qu'à de
la découverte mDNS, dont ce service n'a pas besoin — et il est de toute façon inopérant sur
Docker Desktop.

Deux points le concernent en revanche directement, et tous deux cassent en silence :

- **`tzdata`** — tout le calcul repose sur `ZoneInfo("Europe/Paris")`, absente des images
  slim. L'image l'installe et fixe `TZ` ; sans cela, une heure d'écart en été donnerait des
  comptes à rebours faux sans jamais lever d'erreur.
- **le volume `/app/data`** — il contient la base GTFS compilée, le cache de routage, tes
  calibrations chronométrées et surtout **l'historique de ponctualité**. Le perdre revient à
  repartir de zéro sur les marges mesurées, qui demandent plusieurs jours à se constituer.

Vérifié : image de 198 Mo, `healthy` au bout d'une minute, et au redémarrage la base de
194 Mo est réutilisée sans être recompilée.

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

## Intégration continue

Deux workflows, avec des rôles très différents :

**`ci.yml`** — à chaque push : `ruff`, les tests sur Python 3.11 et 3.13 (les versions de
Debian 12 et 13, les deux cibles possibles du LXC), `shellcheck` sur les scripts Proxmox, et
une vérification que `config.example.yaml` reste chargeable.

**`sources.yml`** — tous les lundis matin, et c'est le plus utile des deux. Le code de ce
dépôt bouge peu ; ses dépendances ne sont pas sous notre contrôle. Ce workflow interroge
réellement le GTFS, l'API rbgl, le SPOTI, le GBFS et les deux routeurs, et vérifie que les
champs attendus sont toujours là — pas seulement que le serveur répond. En cas de casse il
ouvre une issue (et commente l'existante au lieu d'en créer une par semaine), puis la
referme automatiquement quand tout revient.

```bash
python scripts/check_sources.py     # exécutable à la main, sans rien installer d'autre que requests
```

Quatre états, parce que « ne répond pas » recouvre des situations très différentes :
**panne** (GTFS, rbgl, GBFS : l'affichage s'arrête, il faut agir), **dégradé** (SPOTI,
routeurs : un repli disparaît, le service tient), **accès refusé**, et ok.

Ce dernier état vient d'un cas rencontré dès le premier passage : rbgl renvoie `403` aux
runners GitHub alors qu'il répond parfaitement depuis une connexion domestique — vérifié,
le User-Agent n'y est pour rien, c'est un filtrage réseau. Le traiter comme une panne
aurait ouvert une issue chaque lundi pour un service en parfait état, et l'alerte aurait
vite été ignorée. Une alerte qui crie au loup ne sert plus à rien.

## Tests

```bash
pytest -q
```

Vingt tests sur ce qui casse en silence : le calcul à rebours avec correspondance, le
passage de minuit (une course à 25:10 circule bien à 1h10), les exceptions de calendrier,
les comparaisons insensibles aux accents, et la taille du buffer e-ink. Le réseau n'y est
jamais sollicité — c'est le rôle de `check_sources.py`.

## Licence

MIT.
