# o-sfu telemetry defaults

> [!WARNING]
> This repository was written with AI assistance:
> - Research and documentation parsing has been done with "Gemini Deep research"
> - Text formatting has been done with Siri writing tools
> - Grafana graphs have been written with the assitance of google gemini

This repository carries the optional reference observability stack for
[`o-sfu`](https://github.com/ThanhDodeurOdoo/o-sfu). It mirrors the runtime
contract owned by the server:

- Prometheus scrapes `/metrics`
- blackbox probes `GET /v1/noop`
- blackbox probes `GET /internal/diagnostics/summary` with the example diagnostics token
- Grafana ships the default dashboards
- the OpenTelemetry Collector accepts OTLP traces and tails JSON logs
- Loki stores structured logs
- Tempo stores traces

The stack is for local and staging validation, but its defaults now follow the
same shape expected from production logging: the application writes structured
logs to its normal runtime sink, the collector tails a bounded log source, and
file copies are exported on demand for incidents instead of being kept as an
ever-growing debug file.

## Layout

- `docker-compose.yml`: local LGTM-style operator stack plus blackbox and Alertmanager
- `prometheus/`: scrape config, recording rules, alert rules, and the optional host-metrics example
- `grafana/`: provisioned datasources plus dashboards for control-plane, transport lifecycle, media path, sampled media quality, receiver budget adaptation, recording and staging canary checks
- `alertmanager/`: default grouping and routing stub for the reference alerts
- `blackbox/`: probe modules for `GET /v1/noop`
- `otel-collector/`: OTLP and filelog collector pipeline that forwards traces to Tempo and JSON logs to Loki
- `deploy/grafana/`: CI-built Grafana image with the Infinity datasource plugin baked in
- `loki/`: local Loki config for structured OTLP log ingestion
- `tempo/`: local Tempo config for OTLP trace ingestion
- `data/`: bind-mounted local state for logs, collector offsets, Prometheus, Loki, Grafana, and Tempo

## Running the stack

Create a local environment file before starting the stack:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu-telemetry
cp .env.example .env
```

Set `GRAFANA_ADMIN_PASSWORD` to a non-default value. The default
`O_SFU_LOG_DIR=./data/logs` is a local fallback for manual JSONL replay files.
The VPS deployment reads Docker `json-file` logs directly.

Start `o-sfu` on the host with JSON logs and OTLP traces enabled. Do not pipe it
through `tee` as the primary retention mechanism:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu

AUTH_KEY="$(openssl rand -base64 32)" \
PUBLIC_IP=192.0.2.10 \
TELEMETRY_LOG_FORMAT=json \
TELEMETRY_OTLP_ENDPOINT=http://host.docker.internal:4318 \
DIAGNOSTICS_AUTH_TOKEN=examplepassword \
cargo run --release -p o-sfu
```

Then bring up the reference stack:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu-telemetry
docker compose up --build
```

The compose stack uses `host.docker.internal` with a host-gateway mapping so the
containers can scrape and receive OTLP data from a host-run `o-sfu` process.
Service ports are bound to `127.0.0.1` by default; put Grafana or the telemetry
endpoints behind your deployment's normal access-control layer if they must be
reachable remotely.

## Running on the SFU VPS

Use [DEPLOYMENT.md](./DEPLOYMENT.md) for the VPS operator runbook.

That guide is the canonical deployment path for running this stack beside an
NGINX-fronted `o-sfu` deployment. It keeps Prometheus, Loki, Tempo,
Alertmanager, blackbox exporter and the collector private. It exposes Grafana
only through the operator access path under `/grafana/` and keeps the SFU
`AUTH_KEY` out of telemetry containers.

## Log ingestion model

`o-sfu` should emit structured JSON logs to stdout/stderr. The runtime owns log
rotation and retention at the source:

- `o-sfu`: set `TELEMETRY_LOG_FORMAT=json` so stdout/stderr contains one JSON
  object per line
- Docker VPS: use the `json-file` logging driver with `max-size`, `max-file`
  and `labels: "com.odoo.sfu.component"`
- telemetry VPS: mount `/var/lib/docker/containers` read-only into the
  collector
- systemd/journald: keep logs in the journal and export slices with `journalctl`
- Kubernetes: let the node/container runtime rotate container logs and ship them
  from the node log path
- local replay: write a bounded `*.jsonl` file under `data/logs`

the VPS Docker setup labels the `o-sfu` container and lets Docker own the log
files:

```yaml
x-logging: &bounded-logs
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
    labels: "com.odoo.sfu.component"

services:
  o-sfu:
    labels:
      com.odoo.sfu.component: server
    logging: *bounded-logs
```

The OpenTelemetry Collector parses Docker's outer log envelope, keeps only log
records with `com.odoo.sfu.component=server`, then parses the inner `o-sfu`
JSON log body. It stores file offsets in `data/otelcol` so collector restarts do not
replay the same logs.

The local `data/logs` directory remains available for manual replay, but it is
not the production retention mechanism.

Alertmanager routes alerts to the webhook URL stored in
`ALERTMANAGER_WEBHOOK_URL_FILE`. The committed example URL is only for local
configuration validation. Production deployments must provide a real operator
notification endpoint.

For a local replay file:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu

AUTH_KEY="$(openssl rand -base64 32)" \
PUBLIC_IP=192.0.2.10 \
TELEMETRY_LOG_FORMAT=json \
TELEMETRY_OTLP_ENDPOINT=http://host.docker.internal:4318 \
DIAGNOSTICS_AUTH_TOKEN=examplepassword \
cargo run --release -p o-sfu > ../o-sfu-telemetry/data/logs/o-sfu.jsonl 2>&1
```

Start the telemetry stack before writing this file, or truncate the file before
rerunning `o-sfu`, because the production-shaped collector starts at the end of
new files. This is useful for local reproduction only. Delete or rotate the file
yourself after the replay is no longer needed.

## Exporting a debug log copy

Use bounded exports when you need a file for debugging.

From Loki:

```bash
curl -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={service_name="o-sfu"}' \
  --data-urlencode 'start=2026-04-30T10:00:00Z' \
  --data-urlencode 'end=2026-04-30T10:30:00Z' \
  --data-urlencode 'limit=5000' \
  > o-sfu-incident-2026-04-30.json
```

From journald:

```bash
journalctl -u o-sfu \
  --since '2026-04-30 10:00:00 UTC' \
  --until '2026-04-30 10:30:00 UTC' \
  -o json > o-sfu-incident-2026-04-30.jsonl
```

From Docker:

```bash
docker logs \
  --since '2026-04-30T10:00:00Z' \
  --until '2026-04-30T10:30:00Z' \
  o-sfu > o-sfu-incident-2026-04-30.jsonl
```

The exported file is an incident artifact, not the telemetry stack's source of
truth.

## Retention

The reference stack applies bounded local retention:

- Prometheus uses `PROMETHEUS_RETENTION_TIME` and
  `PROMETHEUS_RETENTION_SIZE`.
- Loki keeps logs for `14d` through its compactor.
- Tempo keeps traces for `48h`.

These defaults are intentionally small for a local/staging stack. A real
deployment should move long-lived Loki and Tempo storage to the deployment's
object store and set retention from incident-response requirements.

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
2. Confirm `GET /internal/diagnostics/summary` succeeds with `Authorization: Bearer examplepassword`.
3. Check Prometheus target health for the `o-sfu` scrape, `o-sfu-noop`, and `o-sfu-diagnostics` probes.
4. Open the `o-sfu Staging Canary` dashboard and verify:
   - `Noop Probe` stays at `1`
   - `Join Success Ratio` stays healthy during staged joins
   - `Connected Transports` rises after the canary join
   - `Local Forwarding Efficiency` rises during live media
   - sampled peer RTT and sampled loss stay close to the staged network baseline once media flows
   - receiver budget cards show whether adaptation is degrading, pausing, resuming, or intentionally staying over budget for protected media
5. Open the `o-sfu Media Path` dashboard during simulcast validation. The sampled quality section should show peer RTT, media RTT, ingress or egress loss, peer BWE and egress jitter beside the existing packet-path, decoder-refresh and receiver-budget signals.
6. Open the `o-sfu Room Graph` dashboard, select a room from the active-room table, then select a user from the room-user table. The room graph shows the whole room topology, while the user graph shows that user's inbound and outbound media paths through media-worker nodes, source nodes, and peer users. Use it to inspect the exact receiver BWE estimate, selected receiver budget, active route count, selected bitrate, pause reason, and over-budget exception reason behind the low-cardinality Prometheus signals.
7. Open Grafana Explore with the `Loki` datasource and inspect the structured JSON log fields such as `event`, `room_id`, `user_id`, and `trace_id`.
8. Open Grafana Explore with the `Tempo` datasource and confirm the control-plane spans arrive for the same canary user.

## Sampled media-quality signals

Sampled media quality is server-side transport telemetry emitted by `o-sfu`
through str0m stats events. It is controlled by
`TELEMETRY_MEDIA_QUALITY_INTERVAL_MS`, defaults to one sample window every 5
seconds and can be disabled with `0`. It is not browser `getStats` data. It
does not include browser render quality, device capture quality, decoder
behavior or end-user perception.

Prometheus receives only aggregate labels:

- `sample`: `peer`, `media_ingress` or `media_egress`
- `direction`: `ingress` or `egress` for loss only

There are no room, user, session, source or RID labels. This keeps the metrics
safe for long retention and dashboard-wide alerting. Per-user context stays in
the diagnostics endpoint and appears in the `o-sfu User Diagnostics` dashboard
under `qualitySummary`.

The sampled quality rules expose these operator signals:

- `osfu:media_quality_samples_rate_5m` shows whether sampled stats are arriving.
  A zero value usually means sampling is disabled, no transport is active or no
  media flow has produced a stats event yet.
- `osfu:media_quality_peer_rtt_p95_5m` is the p95 peer transport RTT over the
  recent sample window. Use it as the broadest server-visible latency signal.
- `osfu:media_quality_media_rtt_p95_5m` is the p95 RTT from media ingress and
  egress stats. Use it beside peer RTT to see whether RTT pressure is also
  visible in media feedback.
- `osfu:media_quality_ingress_loss_ppm_average_5m` is average packet loss for
  media entering `o-sfu`. It points first at publisher upload paths, publisher
  network conditions or the server ingress edge.
- `osfu:media_quality_egress_loss_ppm_average_5m` is average packet loss for
  media leaving `o-sfu` toward receivers as exposed by sampled transport stats.
  It points first at receiver downlink paths, server egress pressure or relay
  fan-out pressure.
- `osfu:media_quality_bwe_bps_average_5m` is the average peer bandwidth estimate
  exposed by str0m. Treat it as a capacity trend, not as the exact application
  send bitrate.
- `osfu:media_quality_egress_jitter_average_5m` is remote egress jitter in RTP
  timestamp units. It is intentionally not converted to milliseconds because
  the server-side sample does not infer codec clock rates.

Loss values use parts per million. `10000` means 1 percent loss and `50000`
means 5 percent loss. Dashboard panels divide those values by `1000000` when
they display loss as a fraction.

Read the dashboard panels as rollout and regression indicators rather than as a
complete user-experience diagnosis:

- high peer RTT with low loss usually means latency pressure on the transport
  path.
- high ingress loss usually means publisher-side upload trouble or ingress edge
  pressure.
- high egress loss usually means receiver-side downlink trouble, egress pressure
  or relay fan-out pressure.
- falling BWE together with rising RTT or loss usually means congestion.
- rising jitter with stable loss usually means packet timing variability. Keep
  it in RTP timestamp units and compare trends inside the same codec context.

The warning alerts are conservative canary signals. `OSFUMediaQualityRttHigh`
fires when sampled peer RTT p95 stays above 750 ms while sampled traffic is
present. `OSFUMediaQualityLossHigh` fires when average ingress or egress loss
stays above 5 percent while sampled media traffic is present. Use those alerts
to decide where to inspect next, then combine them with transport lifecycle,
media-path, room graph, user diagnostics and logs.

## Decoder-refresh and keyframe request signals

Decoder refreshes are packet-path observations emitted when `o-sfu` sees a
frame that can make a decoder recover. The `scope` label is bounded:

- `rid`: the packet carried a RID and can refresh a selected simulcast layer.
- `source`: the packet did not carry a RID and is only source-wide.

The media-path dashboard shows `osfu:rtp_decoder_refresh_rate_5m` beside
`osfu:rtc_keyframe_requests_forwarded_rate_5m` and
`osfu:rtc_keyframe_requests_absorbed_rate_5m`. Those request counters come from
route-control decisions, so they include consumer RTCP feedback and internal
selected-RID refresh requests. During a viewer freeze with RTP still flowing, a
rising request rate without RID decoder refreshes points at producer recovery
or packet loss around the selected simulcast layer. A low request rate points
first at missing downstream feedback, stale routes or a browser-side recovery
gap.

Per-source and per-RID ages stay out of Prometheus because those identifiers
are high cardinality. They are exposed by the `o-sfu` diagnostics endpoint on
source encodings as `lastPacketAgeMs` and `lastKeyframeAgeMs`.

## Alerts and recording rules

The reference Prometheus config now ships:

- recording rules for join success ratio, websocket startup failure rate, websocket outbound queue pressure, transport disconnect churn per active user, transport cleanup recovery, local forwarding efficiency, decoder refreshes, keyframe requests, sampled media quality and receiver budget solver outcome rates
- alerts for low join success ratio, websocket startup failures, websocket outbound queue overflow, diagnostics probe failures, normalized transport disconnect churn, unrecovered transport cleanup failures, routing pressure, relay overload, low local forwarding efficiency and sampled media-quality degradation

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

## Production gaps

This repository is still a reference stack, not a complete production platform.
Before using it outside a controlled environment:

- replace the example diagnostics token in `blackbox/blackbox.yml` and
  `grafana/provisioning/datasources/infinity.yaml`
- put Grafana and backend APIs behind your normal authentication and TLS layer
- move durable Loki and Tempo storage to object storage
- decide retention periods from operational requirements
- provision secrets through your deployment system instead of committed files

## Dashboard inventory

- `control-plane.json`: HTTP, websocket admission, diagnostics probe, startup, outbound queue pressure and latency views
- `transport-lifecycle.json`: transport health, ICE, DTLS, cleanup recovery, and user lifetime views
- `media-path.json`: RTP ingress, forwarding, routing pressure, route-control and sampled media-quality views
- `recording.json`: recording action outcomes, active captures, and recording fan-out
- `staging-canary.json`: join success, canary readiness, sampled media quality, disconnect churn and forwarding efficiency
- `room-graph.json`: diagnostics-backed active-room selection, room topology, room-user selection, per-user media-path topology, and source-selection views
- `user-diagnostics.json`: user-id drill-down for retained Loki logs plus live transport-quality diagnostics tables and optional room-scoped media graph
