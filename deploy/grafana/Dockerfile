FROM grafana/grafana-oss:13.0.2@sha256:5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2

ARG GRAFANA_INFINITY_VERSION=3.10.1

USER root

ENV GF_PATHS_PLUGINS=/var/lib/grafana-plugins

RUN mkdir -p "$GF_PATHS_PLUGINS" \
    && chown -R 472:0 "$GF_PATHS_PLUGINS"

USER 472:0

RUN grafana cli --pluginsDir "$GF_PATHS_PLUGINS" plugins install yesoreyeram-infinity-datasource "$GRAFANA_INFINITY_VERSION"
