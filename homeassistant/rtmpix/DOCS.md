# rtmpix sur Home Assistant OS

Avant de démarrer l'application, place la configuration du Mac à
`/addon_configs/local_rtmpix/config.yaml` et les anciens fichiers `data/` à
`/addon_configs/local_rtmpix/data/`. Le partage Samba `addon_configs` donne accès à ce dossier.

Dans `config.yaml`, conserve `gtfs.data_dir: ./data`, `web.host: 0.0.0.0` et
`web.port: 8723`. Arrête le service Mac avant de copier la base SQLite.

Ouvre le tableau de bord à `http://IP_DU_PI:8723/` et donne à ton écran l'URL
`http://IP_DU_PI:8723/eink.png`. Les journaux de l'application indiquent les erreurs de
configuration ou de téléchargement du GTFS.

Le port 8723 n'a pas d'authentification : ne l'expose pas sur Internet.
