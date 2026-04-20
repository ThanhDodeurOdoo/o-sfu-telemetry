# o-sfu telemetry defaults

examples of tooling for https://github.com/ThanhDodeurOdoo/o-sfu

see the repository for more info of what can be observed.

## What is here

- `docker-compose.yml`: local Prometheus, Grafana, Alertmanager, blackbox probe, and collector stack
- `prometheus/`: scrape config, alert rules, and host-metrics example
- `grafana/`: provisioned Prometheus datasource plus dashboards for control-plane, transport lifecycle, media path, and recording
- `alertmanager/`: default grouping and routing stub for the reference alerts
- `blackbox/`: probe modules used to check `GET /v1/noop`
- `otel-collector/`: placeholder OTLP receiver for the later trace feature

## Local prototype

1. Start `o-sfu` on the host with the normal HTTP listener on `:8070`.
2. From this repository root, run `docker compose up`.
3. Open Grafana on `http://localhost:3000`, Prometheus on `http://localhost:9090`, and Alertmanager on `http://localhost:9093`.
4. Confirm the `o-sfu` target is up, the `o-sfu-noop` probe succeeds, and Grafana auto-loads the default vuews

The compose stack uses `host.docker.internal` with a host-gateway mapping so the
containers can scrape a host-run `o-sfu` process.

## Optional host and container metrics

`node_exporter` and `cAdvisor` stay explicitly outside the application runtime
scope. they are optional services behind  `infra` profile:

```bash
docker compose --profile infra up
```

The default `prometheus/prometheus.yml` stays focused on the application and the
noop probe. If you want the reference host or container panels, use
`prometheus/prometheus.host-metrics.example.yml` as the starting point for a local
override.

## Dashboard layout

- `control-plane.json`: HTTP, websocket admission, session startup, and latency views
- `transport-lifecycle.json`: transport health, ICE, DTLS, and lifetime views
- `media-path.json`: RTP ingress, forwarding, routing pressure, and route-control views
- `recording.json`: recording action outcomes, active captures, and recording fan-out
