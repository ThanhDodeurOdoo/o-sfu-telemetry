# o-sfu telemetry defaults

> [!WARNING]
> AI DISCLAIMER
> I am not a "deployment"/"devops",
> This repository was written following the guidance and explanations of AI (mostly the Gemini deep research feature)
> README explanations have also been partially written (gemini) or formatted (Siri writing tools) by AI.
> This is NOT a production-grade product, it is only a personal tool to help me visualize and dev/debug o-sfu.

This repository carries the optional reference observability stack for
[`o-sfu`](https://github.com/ThanhDodeurOdoo/o-sfu). It mirrors the runtime
contract owned by the server:

- Prometheus scrapes `/metrics`
- blackbox probes `GET /v1/noop`
- Grafana ships the default dashboards
- the OpenTelemetry Collector accepts OTLP traces and tails JSON logs
- Loki stores structured logs
- Tempo stores traces

The stack is for local and staging validation. It is a reference baseline, not a
required production deployment model.

## Layout

- `docker-compose.yml`: local LGTM-style operator stack plus blackbox and Alertmanager
- `prometheus/`: scrape config, recording rules, alert rules, and the optional host-metrics example
- `grafana/`: provisioned datasources plus dashboards for control-plane, transport lifecycle, media path, recording, and staging canary checks
- `alertmanager/`: default grouping and routing stub for the reference alerts
- `blackbox/`: probe modules for `GET /v1/noop`
- `otel-collector/`: OTLP and filelog collector pipeline that forwards traces to Tempo and JSON logs to Loki
- `loki/`: local Loki config for structured OTLP log ingestion
- `tempo/`: local Tempo config for OTLP trace ingestion
- `data/`: bind-mounted local state for logs, Loki, and Tempo

## Running the stack

Start `o-sfu` on the host with JSON logs and OTLP traces enabled:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu

AUTH_KEY="$(openssl rand -base64 32)" \
PUBLIC_IP=192.0.2.10 \
TELEMETRY_LOG_FORMAT=json \
TELEMETRY_OTLP_ENDPOINT=http://host.docker.internal:4318 \
DIAGNOSTICS_AUTH_TOKEN=examplepassword \
cargo run --release -p o-sfu 2>&1 | tee ../o-sfu-telemetry/data/logs/o-sfu.jsonl
```
(the current urls are execting DIAGNOSTICS_AUTH_TOKEN=examplepassword)

Then bring up the reference stack:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu-telemetry
docker compose up
```

The compose stack uses `host.docker.internal` with a host-gateway mapping so the
containers can scrape and receive OTLP data from a host-run `o-sfu` process.

## Endpoints

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- Loki: `http://localhost:3100/metrics`
- Tempo: `http://localhost:3200/metrics`
- OTLP gRPC receiver: `localhost:4317`
- OTLP HTTP receiver: `localhost:4318`

Grafana provisions three datasources out of the box:

- `Prometheus`
- `Loki`
- `Tempo`

## Validation flow

1. Confirm `GET /v1/noop` succeeds on the host-run `o-sfu`.
2. Check Prometheus target health for the `o-sfu` scrape and `o-sfu-noop` probe.
3. Open the `o-sfu Staging Canary` dashboard and verify:
   - `Noop Probe` stays at `1`
   - `Join Success Ratio` stays healthy during staged joins
   - `Connected Transports` rises after the canary join
   - `Local Forwarding Efficiency` rises during live media
4. Open Grafana Explore with the `Loki` datasource and inspect the structured JSON log fields such as `event`, `room_id`, `user_id`, and `trace_id`.
5. Open Grafana Explore with the `Tempo` datasource and confirm the control-plane spans arrive for the same canary user.

## Alerts and recording rules

The reference Prometheus config now ships:

- recording rules for join success ratio, websocket startup failure rate, transport disconnect churn per active user, transport cleanup recovery, and local forwarding efficiency
- alerts for low join success ratio, websocket startup failures, normalized transport disconnect churn, unrecovered transport cleanup failures, routing pressure, relay overload, and low local forwarding efficiency

These derived rules are intended for operator dashboards and canary validation.
They should stay derived from runtime-owned metrics instead of introducing extra
application counters unless the runtime surface proves insufficient.

## Optional host and container metrics

`node_exporter` and `cAdvisor` stay explicitly outside the application runtime
scope.

On Linux hosts:

```bash
docker compose --profile linux-infra up
```

On Docker Desktop or macOS:

```bash
docker compose up
```

Do not enable the Linux host-metrics profile on Docker Desktop. Both
`node-exporter` and `cAdvisor` depend on Linux host mount-propagation behavior
and are aimed at real Linux hosts, not the Docker Desktop VM.

The default `prometheus/prometheus.yml` stays focused on the application, the
noop probe, and the reference operator signals. If you need host or container
panels, use `prometheus/prometheus.host-metrics.example.yml` as the starting
point for a local override.

## Dashboard inventory

- `control-plane.json`: HTTP, websocket admission, startup, and latency views
- `transport-lifecycle.json`: transport health, ICE, DTLS, cleanup recovery, and user lifetime views
- `media-path.json`: RTP ingress, forwarding, routing pressure, and route-control views
- `recording.json`: recording action outcomes, active captures, and recording fan-out
- `staging-canary.json`: join success, canary readiness, disconnect churn, and forwarding efficiency
