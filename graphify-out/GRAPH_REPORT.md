# Graph Report - rtm  (2026-10-15)

## Corpus Check
- 47 files · ~146,910 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 4)

## Summary
- 621 nodes · 1270 edges · 31 communities (24 shown, 7 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 77 edges (avg confidence: 0.89)
- Coût : aucun appel API externe. Tokens des agents non exposés par cet environnement ; compteurs internes à 0 par convention, pas une mesure de consommation.

## Community Hubs (Navigation)
- Planification des trajets
- Géographie et agendas
- Départs et temps réel
- Service et orchestration
- AWTRIX et calibration
- Configuration du projet
- GTFS et tests
- Rendu e-ink
- Rendu AWTRIX
- Surveillance des sources
- Dashboard et API
- Ponctualité et marges
- Docker et intégration continue
- Perturbations du réseau
- Choix et mécanismes documentés
- Routage piéton
- Fonctions visibles du dashboard
- Présentation du produit
- Déploiement Home Assistant
- Serveur web Flask
- Installation LXC native
- Installation LXC Docker
- Sources et replis RTM
- Mise à jour Proxmox
- Illustration des transports
- Démarrage Home Assistant
- Architecture LXC documentée
- Paquet Python
- Identité visuelle couleur
- Identité visuelle monochrome

## God Nodes (most connected - your core abstractions)
1. `Service` - 41 edges
2. `load_config()` - 23 edges
3. `Dashboard de trajets et de calibration` - 19 edges
4. `Departure` - 18 edges
5. `create_app()` - 18 edges
6. `rtmpix` - 18 edges
7. `Pattern` - 17 edges
8. `discover()` - 17 edges
9. `render()` - 16 edges
10. `latest_departure()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Geocoder` --implements--> `Recherche explicite Nominatim avec cache`  [INFERRED]
  rtmpix/geocode.py → README.md
- `Calibration` --implements--> `Priorité de data/calibration.json sur config.yaml`  [INFERRED]
  rtmpix/calibration.py → README.md
- `render()` --implements--> `Écran e-ink 800×480 à heures absolues`  [INFERRED]
  rtmpix/eink.py → README.md
- `RealtimeService` --implements--> `Cascade rbgl → SPOTI → GTFS local`  [INFERRED]
  rtmpix/realtime.py → README.md
- `ScheduleClient` --implements--> `Rafraîchissement et cache iCal par destination`  [INFERRED]
  rtmpix/schedule.py → README.md

## Import Cycles
- None detected.

## Communities (31 total, 7 thin omitted)

### Community 0 - "Planification des trajets"
Cohesion: 0.05
Nodes (35): Agendas iCal des destinations, Reliability, date_to_int(), _dedupe(), discover(), score(), earliest_arrival(), _expected_wait_s() (+27 more)

### Community 1 - "Géographie et agendas"
Cohesion: 0.05
Nodes (17): load(), save(), haversine_m(), walk_seconds(), Geocoder, Place, walk_from(), walk_to() (+9 more)

### Community 2 - "Départs et temps réel"
Cohesion: 0.05
Nodes (24): Board, build_boards(), sort_key(), _fold(), _margin(), _matches_filter(), Departure, _gather() (+16 more)

### Community 3 - "Service et orchestration"
Cohesion: 0.07
Nodes (6): cmd_once(), cmd_run(), RealtimeService, JourneyState, Service, test_priorite_des_deux_agendas()

### Community 4 - "AWTRIX et calibration"
Cohesion: 0.07
Nodes (12): Awtrix, Calibration, cmd_check(), cmd_journey(), cmd_stops(), main(), _print_plans(), setup_logging() (+4 more)

### Community 5 - "Configuration du projet"
Cohesion: 0.08
Nodes (22): Awtrix, Config, Destination, Disruptions, Eink, Gtfs, Home, Journeys (+14 more)

### Community 6 - "GTFS et tests"
Cohesion: 0.08
Nodes (14): build_db(), connect(), Database, db_meta(), download(), ensure_db(), parse_gtfs_time(), _reader() (+6 more)

### Community 7 - "Rendu e-ink"
Cohesion: 0.10
Nodes (12): Canvas, _font(), _french_date(), _next_catchable(), render(), to_bmp_1bit(), to_packed_1bpp(), to_png() (+4 more)

### Community 8 - "Rendu AWTRIX"
Cohesion: 0.11
Nodes (17): board_app(), board_screen(), deadline_app(), deadline_screen(), disruption_app(), format_hour(), format_lead(), line_color() (+9 more)

### Community 9 - "Surveillance des sources"
Cohesion: 0.23
Nodes (12): Surveillance hebdomadaire des sources externes, check_gbfs(), check_gtfs(), check_osrm(), check_rbgl_departures(), check_rbgl_disruptions(), check_spoti(), check_valhalla() (+4 more)

### Community 10 - "Dashboard et API"
Cohesion: 0.15
Nodes (15): Dashboard de trajets et de calibration, Sélection des arrêts et sens avec brouillon local, create_app(), add_destination(), calibration(), eink_bmp(), eink_png(), eink_raw() (+7 more)

### Community 11 - "Ponctualité et marges"
Cohesion: 0.15
Nodes (3): LineStats, _percentile(), Punctuality

### Community 12 - "Docker et intégration continue"
Cohesion: 0.24
Nodes (3): CI Python, shell et Docker, Service Docker Compose rtmpix, Dépendances Python déclarées

### Community 13 - "Perturbations du réseau"
Cohesion: 0.24
Nodes (4): _clean(), Disruption, DisruptionClient, relevant()

### Community 14 - "Choix et mécanismes documentés"
Cohesion: 0.18
Nodes (6): Configuration d’exemple rtmpix, Limites de découverte et d’affichage des trajets, Percentile et seuil des marges de fiabilité, OSRM, Protocole TRMNL BYOS, Valhalla

### Community 15 - "Routage piéton"
Cohesion: 0.29
Nodes (3): _key(), Leg, WalkRouter

### Community 16 - "Fonctions visibles du dashboard"
Cohesion: 0.33
Nodes (10): Levélo station bicycle and free-dock availability, rtmpix dashboard, Leave-at time and remaining-time countdown, Destination itineraries, Transit disruption status, Door-to-platform walking and platform-time calibration, E-ink clock preview and delivery, Optional iCal destination agenda (+2 more)

### Community 17 - "Présentation du produit"
Cohesion: 0.20
Nodes (3): LeVélo GBFS 2.2 Métropole AMP, Perturbations RTM par API mobilité, rtmpix

### Community 18 - "Déploiement Home Assistant"
Cohesion: 0.29
Nodes (3): Manifest de l’application Home Assistant rtmpix, Sauvegarde HA cold du dossier addon_config, Application locale Home Assistant OS

### Community 20 - "Installation LXC native"
Cohesion: 0.52
Nodes (6): die(), info(), ok(), pick_storage(), install.sh script, warn()

### Community 21 - "Installation LXC Docker"
Cohesion: 0.52
Nodes (6): die(), info(), ok(), pick_storage(), install-docker.sh script, warn()

### Community 22 - "Sources et replis RTM"
Cohesion: 0.33
Nodes (3): GTFS RTM compilé en SQLite, API mobilité rbgl, API RTM SPOTI non documentée

### Community 23 - "Mise à jour Proxmox"
Cohesion: 0.70
Nodes (4): die(), info(), ok(), update.sh script

### Community 24 - "Illustration des transports"
Cohesion: 0.83
Nodes (4): Commute banner, Stop departure display, Marseille public transport commute, Tram

## Knowledge Gaps
- **16 isolated node(s):** `rtmpix`, `Valhalla`, `OSRM`, `Agendas iCal des destinations`, `Protocole TRMNL BYOS` (+11 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 208 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Service` connect `Service et orchestration` to `Planification des trajets`, `Géographie et agendas`, `AWTRIX et calibration`, `Configuration du projet`, `Ponctualité et marges`, `Perturbations du réseau`, `Routage piéton`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `Service` (e.g. with `Awtrix` and `Calibration`) actually correct?**
  _`Service` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `rtmpix`, `Valhalla`, `OSRM` to the rest of the system?**
  _16 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Planification des trajets` be split into smaller, more focused modules?**
  _Cohesion score 0.0539906103286385 - nodes in this community are weakly interconnected._
- **Why does `rtmpix` connect `Présentation du produit` to `Géographie et agendas`, `Départs et temps réel`, `AWTRIX et calibration`, `GTFS et tests`, `Rendu AWTRIX`, `Surveillance des sources`, `Docker et intégration continue`, `Choix et mécanismes documentés`, `Serveur web Flask`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `Dashboard de trajets et de calibration` (e.g. with `add_destination()` and `calibration()`) actually correct?**
  _`Dashboard de trajets et de calibration` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `Géographie et agendas` be split into smaller, more focused modules?**
  _Cohesion score 0.0525879917184265 - nodes in this community are weakly interconnected._
## Périmètre et limites de la cartographie

- Corpus : code, tests, scripts, documentation, visuels et deux Dockerfiles de ce dépôt.
- Configuration privée `config.yaml`, données, environnement virtuel, `dist/` et réglages locaux des outils exclus. Le firmware ESP préparé dans `dist/` est donc hors de cette carte.
- Analyse statique et documentaire : aucune exécution des tests applicatifs, aucun contrôle du serveur Home Assistant ni de la dalle pendant cette cartographie.
- Diagnostic Graphify de l’extraction : 135 liens avec extrémité absente dans les nœuds bruts (notamment imports de bibliothèques externes), 82 relations de mêmes extrémités regroupées dans la vue non orientée. Voir `GRAPH_HEALTH.txt`. Le JSON brut `extraction.json` conserve les relations avant construction de la vue.
- Le graphe final a été contrôlé : chaque relation référence des nœuds présents. Les relations documentaires inférées gardent leur niveau de confiance.
- Les deux Dockerfiles ont été inclus explicitement comme documents ; une extraction automatique ultérieure doit conserver ce périmètre.
