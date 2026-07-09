FROM grafana/grafana-oss:11.4.0@sha256:d8ea37798ccc41061a62ab080f2676dda6bf7815558499f901bdb0f533a456fb

ARG GRAFANA_INFINITY_VERSION=3.8.0

USER root

ENV GF_PATHS_PLUGINS=/var/lib/grafana-plugins

RUN mkdir -p "$GF_PATHS_PLUGINS" \
    && chown -R grafana:grafana "$GF_PATHS_PLUGINS"

USER grafana

RUN grafana-cli --pluginsDir "$GF_PATHS_PLUGINS" plugins install yesoreyeram-infinity-datasource "$GRAFANA_INFINITY_VERSION"
