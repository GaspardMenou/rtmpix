#!/bin/sh
set -eu

if [ ! -f /config/config.yaml ]; then
    echo "Configuration absente : copier le config.yaml du Mac dans /addon_configs/local_rtmpix/config.yaml" >&2
    exit 1
fi

exec python -m rtmpix --config /config/config.yaml run
