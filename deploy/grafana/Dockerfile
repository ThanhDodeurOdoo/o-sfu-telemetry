FROM grafana/grafana:13.1.0@sha256:121a7a9ece6dc10b969f1f96eed64b4f07dfac0d0b8abc070f7cb83bbde86f63

ARG GRAFANA_INFINITY_VERSION=3.10.1

USER root

ENV GF_PATHS_PLUGINS=/var/lib/grafana-plugins

RUN mkdir -p "$GF_PATHS_PLUGINS" \
    && chown -R 472:0 "$GF_PATHS_PLUGINS"

USER 472:0

RUN grafana cli --pluginsDir "$GF_PATHS_PLUGINS" plugins install yesoreyeram-infinity-datasource "$GRAFANA_INFINITY_VERSION"
