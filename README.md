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
- blackbox probes `GET /internal/diagnostics/summary` with the configured diagnostics token
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
- `prometheus/`: shared target inventory, scrape configs, recording rules, alert rules and the optional host-metrics example
- `grafana/`: provisioned datasources plus dashboards for control-plane, transport lifecycle, media path, sampled media quality, receiver budget adaptation, recording and staging canary checks
- `alertmanager/`: default grouping and routing stub for the reference alerts
- `blackbox/`: shared probe modules for `GET /v1/noop` and protected diagnostics
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
The VPS deployment reads Docker `json-file` logs directly. Keep
`DIAGNOSTICS_AUTH_TOKEN` equal to the token passed to the local server. The
committed `examplepassword` value is only for this host-local example.

Start `o-sfu` on the host with JSON logs and OTLP traces enabled. Do not pipe it
through `tee` as the primary retention mechanism:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu

AUTH_KEY="$(openssl rand -base64 32)" \
PUBLIC_IP=192.0.2.10 \
TELEMETRY_LOG_FORMAT=json \
TELEMETRY_OTLP_ENDPOINT=http://127.0.0.1:4318 \
DIAGNOSTICS_AUTH_TOKEN=examplepassword \
cargo run --release -p o-sfu
```

Then bring up the reference stack:

```bash
cd /Volumes/X9-Pro/odoo-dev/o-sfu-telemetry
docker compose up --build
```

The compose stack uses `host.docker.internal` with a host-gateway mapping so
containers can scrape the host-run `o-sfu` process. The host sends OTLP traces
to the collector's published `127.0.0.1:4318` port.
Prometheus and blackbox read the diagnostics token from a service-scoped
Compose secret. Grafana receives the same token through its environment.
Set `DIAGNOSTICS_AUTH_TOKEN` in `.env` and on the server to the same value.
Recreate these services after changing it so their credentials stay aligned.
Service ports are bound to `127.0.0.1` by default; put Grafana or the telemetry
endpoints behind your deployment's normal access-control layer if they must be
reachable remotely.

The reference targets assume the stack and `o-sfu` share one trusted host. Do
not attach untrusted workloads to their container network or send the bearer
token to a remote plaintext target. Use a private TLS endpoint or an
authenticated encrypted overlay when the scraper is on another host.

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

The original JSON line remains intact in Loki. The Collector resolves parent
span fields from root to leaf, applies event fields and preserves authoritative
envelope metadata. Dashboards filter the resulting structured metadata directly.
Trace links use the resolved `trace_id` metadata.

Numeric metadata outside signed 64-bit range is omitted because the Collector's
JSON parser cannot preserve it exactly. The original body retains those digits.

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
TELEMETRY_OTLP_ENDPOINT=http://127.0.0.1:4318 \
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

Grafana provisions four datasources out of the box:

- `Prometheus`
- `Loki`
- `Tempo`
- `Infinity` for the configured SFU diagnostics endpoints

Graph panels fetch `/internal/diagnostics/rooms/{uuid}` and build nodes and edges
with Infinity's JQ backend. Their shared expressions live in `grafana/graphs/`.
Run `python3 scripts/check_graph_queries.py --write` after editing an expression
to refresh its dashboard targets. Infinity decodes numbers as floating point,
so graph queries reject numeric identities outside the exact integer range
`-(2^53-1)` through `2^53-1`. String identities retain their exact representation.

## Validation flow

1. Confirm `GET /v1/noop` succeeds on the host-run `o-sfu`.
2. Confirm `GET /v1/stats`, `GET /metrics` and `GET /internal/diagnostics/summary` succeed with `Authorization: Bearer <DIAGNOSTICS_AUTH_TOKEN>`.
3. Check Prometheus target health for the `o-sfu` scrape, `o-sfu-noop`, and `o-sfu-diagnostics` probes.
4. Open `o-sfu Operations`. Confirm current metrics and both probes are available, then inspect each degraded boundary. Idle activity and missing evidence have separate states.
5. Open `o-sfu Canary Comparison`. Select distinct baseline and candidate instances with comparable workloads. Compare event rates, quality observation counts, short closed-session shares and protection events. Add deployment or rollback markers with Grafana annotations.
6. Open `o-sfu Media Path`. Quality observations and repair activity precede throughput. A missing quality value means no usable observations. Local forwards per ingress packet measure fanout and can exceed one.
7. Open `o-sfu Room Graph`, select a room and then a user. Current diagnostics show source and encoding identity, delivery policy, packet age and keyframe age where available. These snapshots do not follow the historical time picker.
8. Open `o-sfu User Diagnostics` for historical room/user failures and current transport state. INFO lifecycle records discover rooms independently of the selected warning filter. Roomless warnings remain separate from room-attributed evidence.
9. Open `o-sfu Telemetry and Log Health`. Confirm collector intake and export, queue occupancy, service readiness and retained log activity. Zero application logs alone do not establish pipeline health.
10. Follow a log's trace ID to Tempo when that trace was sampled and retained. Trace details link back to the matching structured logs.

## Baseline and canary targets

All three SFU scrape jobs read `prometheus/targets/*.json`. The default inventory
contains `host.docker.internal:8070`. Both Compose profiles mount this directory.
Prometheus discovers inventory edits without a restart.

For a two-instance comparison, replace `prometheus/targets/local.json` with an
edited copy of `prometheus/targets.canary.example.json`. Set the two addresses to
reachable SFU HTTP listeners. Do not keep duplicate targets in another inventory
file. The example remains outside the discovery directory until copied.

Metrics and both probes use the same `instance="host:port"` label. Probes retain
their full endpoint URL in `probe_target`. Recording rules preserve `instance`,
so one healthy SFU cannot mask a failed candidate. The baseline and candidate
selectors must identify different targets for a useful comparison. Optional
`deployment_role` labels describe the inventory but do not select a target.

This reference profile shares one `DIAGNOSTICS_AUTH_TOKEN` across its targets.
Use separate authenticated scrape jobs and token files when targets require
different credentials. The example uses HTTP inside the existing private
observation network. Remote targets still need the protected transport described
in [DEPLOYMENT.md](DEPLOYMENT.md).

Room, user and worker HTTP diagnostics continue to query the configured Infinity
server. The Prometheus instance picker does not redirect that datasource. Their
panels state that scope. Configure an additional authenticated Infinity datasource
and matching diagnostic URLs before inspecting another SFU through those views.

## Evidence and unavailable states

- Current health requires recent successful scrapes and probes. Missing scrapes do not become an OK state.
- Connection-stage ratios compare aggregate events in the same window. They can exceed one near window boundaries and do not identify affected users.
- The join/DTLS event gap is an aggregate difference. Confirm individual failures through room/user logs.
- A low forwarding fanout can reflect subscription layout or delivery policy. It is not a packet-loss fraction.
- Short-session shares count closed transport sessions. A short normal call contributes to the same histogram as a failed attempt.
- Each quality field has its own observation count. Zero observations suppress its average or percentile.
- A missing worker heartbeat is distinct from a reported zero delay. Worker pressure measures bounded mailbox utilization, not CPU usage.
- Persistent recording is unsupported at the checked `o-sfu` revision `b60da1d5`. The recording board shows handled and rejected controls without implying capture or upload.

Exact failed-user cohorts, browser freeze duration, quality sample age, historical
worker pressure and recorder completion require additional server or browser
instrumentation. These dashboards do not synthesize those measurements from
unrelated counters.

## Telemetry pipeline monitoring

Prometheus scrapes itself, the collector, Loki and Tempo. Blackbox probes their
readiness endpoints. Collector internal metrics listen on port `8888` only inside
the Compose network. No additional host port is published.

The pipeline board shows accepted and exported logs/spans, receiver refusals,
failed sends and enqueues, queue occupancy, process memory and scrape age. Sending
failures can retry. Enqueue failures can discard telemetry. Missing lazy counters
remain unavailable until the collector observes the corresponding signal.

Host filesystem capacity appears only when the optional Linux node-exporter
profile and scrape are enabled. Match its mountpoint to the filesystem backing
`data/`. Process memory and exporter queues do not measure available disk space.

`prometheus/pipeline-alerts.yml` covers failed scrapes/readiness, recurring export
failures, receiver refusals and queues above 80 percent capacity for five minutes.

## Repository checks

Run `scripts/check-telemetry.sh` with Docker, Python 3 and jq. It validates all
Compose profiles, dashboard layouts, PromQL expressions, graph relationships,
Collector log normalization and the three Prometheus configurations. Collector
fixtures run against the pinned image through both JSONL and Docker receivers.
Prometheus rule fixtures use the pinned Prometheus image. The same command runs
in the Compose CI workflow.

The rule fixtures cover independent SFU instances, stale or failed scrapes,
missing probes, idle traffic, fanout above one, zero observations, simultaneous
degraded boundaries, short-session shares and collector export failures.

Dashboard organization follows [Grafana's dashboard guidance](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/).
Collector metrics use the documented [internal telemetry reader](https://opentelemetry.io/docs/collector/internal-telemetry/).
Rule behavior uses [Prometheus rule tests](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/).

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
the room-scoped diagnostics endpoint and appears in the `o-sfu User Diagnostics`
dashboard under `qualitySummary`.

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

## Performance signals

`o-sfu Performance Signals` (`osfu-performance-signals`) follows one selected
SFU instance with rolling five-minute measurements. It places peer RTT
p50/p95/p99, separate media-ingress/media-egress RTT p95 and directional loss
observations beside workload, repair activity and saturation events. Websocket
setup duration measures connection setup rather than media delivery latency.

When updating a running stack, reload or restart Prometheus to load the four
new RTT recording rules. Grafana discovers the board through its existing
dashboard file provisioning.

Published tracks, subscribers, packet rate, throughput and CPU are common SFU
benchmark dimensions. Participant count alone does not describe forwarding
work. The board therefore pairs rooms and users with ingress/egress packet
rates, RTP payload throughput and local forwarding fanout. These counters do
not prove receipt at subscribers. See [LiveKit's benchmarking guide](https://docs.livekit.io/transport/self-hosting/benchmark).

RTT percentiles estimate the distribution of sampled transport observations,
not users or individual packets. The current histogram has finite bounds at
50, 100, 250 and 500 ms followed by 1, 2 and 5 seconds. It cannot resolve tails
inside the first 50 ms bucket. Cumulative bucket shares and observation counts
provide the measured distribution, including observations above 5 seconds
that cannot yield an exact tail value. Quantiles depend on histogram bucket
resolution and must be calculated after aggregating buckets, rather than by
averaging percentiles. See [Prometheus histogram guidance](https://prometheus.io/docs/practices/histograms/).

Ingress and egress loss are observation means, not packet-weighted loss
fractions. Each direction combines the available peer and media stats reports,
which can describe overlapping traffic. Read each mean with its own observation
count. Missing observations remain unavailable instead of becoming zero. The
board applies no generic good/bad thresholds to these performance values.

At the checked server revision `b60da1d5`, jitter exports contain only a sum and
count in raw RTP timestamp units across potentially different codec clocks.
They cannot produce jitter p95 or a defensible aggregate in milliseconds.
RTP interarrival jitter measures packet-spacing variation and is distinct from
receiver jitter-buffer residence time. See [RFC 3550 section 6.4.1](https://www.rfc-editor.org/rfc/rfc3550.html#section-6.4.1)
and the [WebRTC statistics definitions](https://www.w3.org/TR/webrtc-stats/).
Per-packet SFU forwarding delay, browser playout quality and historical worker
pressure also lack the required metrics. RTT does not substitute for these
measurements. The optional current worker diagnostics use the configured
Infinity server, independently of the Prometheus instance and historical time
selectors. Worker heartbeat delay measures worker service delay.

For revision comparisons, match codec, bitrate, topology, subscription fanout
and offered packet rate. Ensure the load generator has spare capacity. Mark
load-step boundaries and deployments with Grafana annotations, then compare
steady portions after the five-minute window contains the new load. This
stack does not map CPU or RSS measurements to the selected SFU process. Use
the [o-sfu-load-testing reports](https://github.com/ThanhDodeurOdoo/o-sfu-load-testing#interactive-reports)
for separate SFU/generator resources, worker history and receiver delivery
results when evaluating capacity or a performance regression.

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

- recording rules for join success ratio, websocket startup failure rate, websocket outbound queue pressure, transport disconnect churn per active user, terminal transport cleanup failures, local forwarding fanout, decoder refreshes, keyframe requests, sampled media quality and committed receiver video route transition rates
- alerts for low join success ratio, websocket startup failures, websocket outbound queue overflow, diagnostics probe failures, normalized transport disconnect churn, recurring terminal transport cleanup failures, routing pressure, relay overload, protective output-budget closures and sampled media-quality degradation

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

- set the same non-example `DIAGNOSTICS_AUTH_TOKEN` in `.env` and on `o-sfu`
- put Grafana and backend APIs behind your normal authentication and TLS layer
- move durable Loki and Tempo storage to object storage
- decide retention periods from operational requirements
- provision secrets through your deployment system instead of committed files

## Dashboard inventory

- `operations.json`: current availability, concurrent failure boundaries and the investigation path
- `control-plane.json`: HTTP, websocket admission, startup failures and outbound queue pressure
- `transport-lifecycle.json`: transport health, ICE/DTLS events, short sessions and cleanup failures
- `media-path.json`: sampled quality, repair, protection events, receiver adaptation and media throughput
- `performance-signals.json`: RTT distributions, loss observations, workload, recovery and saturation with measurement limits
- `recording.json`: checked backend capability and handled/rejected recording controls
- `staging-canary.json`: independent baseline/candidate measurements, workload and observation counts
- `room-graph.json`: current room selection, room topology and user media paths
- `user-diagnostics.json`: historical room/user failures and current transport/source/encoding details
- `worker-load.json`: current missing heartbeats and queue pressure plus instance-scoped workload history
- `log-health.json`: telemetry readiness, intake/export failures, queues and warning/error activity
- `logs.json`: structured log search with room, user and trace context
