FROM python:3.13-slim

# Deux paquets qui ne sont pas du confort mais des conditions de fonctionnement :
#
#   tzdata            tout le calcul horaire repose sur ZoneInfo("Europe/Paris"). Les images
#                     slim n'embarquent aucune base de fuseaux : sans lui, le service lève
#                     ZoneInfoNotFoundError au démarrage. Et une heure d'écart en été
#                     donnerait des comptes à rebours faux sans jamais lever d'erreur.
#   fonts-dejavu-core le rendu e-ink cherche une police TrueType ; sans elle il retombe sur
#                     la police bitmap par défaut, minuscule et illisible sur 800×480.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Paris \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Les dépendances d'abord : elles changent bien moins souvent que le code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY rtmpix ./rtmpix
COPY config.example.yaml ./

# Le service n'a aucune raison de tourner en root.
RUN useradd --system --uid 10001 --home /app rtmpix \
    && mkdir -p /app/data \
    && chown -R rtmpix:rtmpix /app/data
USER rtmpix

EXPOSE 8723

# Le dashboard fait office de sonde. Le délai de démarrage laisse le temps de télécharger
# et compiler le GTFS au tout premier lancement.
HEALTHCHECK --interval=60s --timeout=6s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request as u, sys; \
sys.exit(0 if u.urlopen('http://127.0.0.1:8723/api/state', timeout=5).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "rtmpix", "--config", "/app/config.yaml"]
CMD ["run"]
