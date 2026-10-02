FROM python:3.13-slim

ARG BUILD_VERSION=0.2.0
ARG BUILD_ARCH=aarch64
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Paris PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY rtmpix ./rtmpix
COPY run.sh /run.sh
EXPOSE 8723
CMD ["/bin/sh", "/run.sh"]
