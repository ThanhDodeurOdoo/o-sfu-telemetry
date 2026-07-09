# o-sfu telemetry deployment

this document is the operator contract for running the reference `o-sfu`
telemetry stack beside an `o-sfu` deployment that uses NGINX as the public edge

follow `o-sfu/DEPLOYMENT.md` for the SFU first

this stack is deployed as a separate Docker Compose project and joins the
existing `o-sfu_default` network

do not merge the telemetry services into the SFU runtime compose file

## traffic model

```text
operator HTTPS -> NGINX -> Grafana

private Prometheus -> o-sfu /metrics
private blackbox   -> o-sfu /v1/noop
private blackbox   -> o-sfu /internal/diagnostics/summary
private Grafana    -> o-sfu /internal/diagnostics/...

o-sfu Docker logs -> OpenTelemetry Collector -> Loki
o-sfu OTLP traces  -> OpenTelemetry Collector -> Tempo
```

public routes:

```text
/grafana/ -> allowed behind normal operator access control
/metrics -> blocked
/internal/diagnostics/... -> blocked
```

Prometheus, Loki, Tempo, Alertmanager, blackbox exporter and the collector stay
private

## required o-sfu environment

`o-sfu` must emit JSON logs, expose diagnostics privately and send traces to the
collector:

```env
TELEMETRY_LOG_FORMAT=json
TELEMETRY_DEPLOYMENT_ENVIRONMENT=production
TELEMETRY_OTLP_ENDPOINT=http://otel-collector:4318
DIAGNOSTICS_AUTH_TOKEN=<diagnostics-token>
```

`TELEMETRY_DEPLOYMENT_ENVIRONMENT=production` enables the production trace
sampling policy in `o-sfu`

root traces are sampled at 5 percent and child spans follow the parent decision

logs and metrics remain the primary alerting source because a sampled-out trace
will not be present in Tempo

the diagnostics token must be the same value used by Grafana and blackbox
exporter

the `deploy/sfu-vps` compose profile reads that token from its own
`deploy/sfu-vps/.env` file

do not mount `/etc/o-sfu/o-sfu.env` into Grafana or blackbox exporter because it
also contains `AUTH_KEY`

one safe way to merge the telemetry variables into the SFU env file:

```bash
read -rsp 'Diagnostics token: ' DIAG_TOKEN
printf '\n'

sudo sed -i \
  -e '/^TELEMETRY_LOG_FORMAT=/d' \
  -e '/^TELEMETRY_DEPLOYMENT_ENVIRONMENT=/d' \
  -e '/^TELEMETRY_OTLP_ENDPOINT=/d' \
  -e '/^DIAGNOSTICS_AUTH_TOKEN=/d' \
  /etc/o-sfu/o-sfu.env

sudo tee -a /etc/o-sfu/o-sfu.env >/dev/null <<EOF
TELEMETRY_LOG_FORMAT=json
TELEMETRY_DEPLOYMENT_ENVIRONMENT=production
TELEMETRY_OTLP_ENDPOINT=http://otel-collector:4318
DIAGNOSTICS_AUTH_TOKEN=${DIAG_TOKEN}
EOF
```

## shared network

the VPS profile expects the SFU compose project to create this Docker network:

```text
o-sfu_default
```

check it on the host:

```bash
sudo docker network inspect o-sfu_default >/dev/null
```

the telemetry dashboards and probes use `host.docker.internal:8070` as the
private SFU address

make the `o-sfu` service own that alias on the shared Docker network:

```yaml
services:
  o-sfu:
    networks:
      default:
        aliases:
          - host.docker.internal
```

if the SFU compose project does not use the default network name
`o-sfu_default`, either keep the `o-sfu` project name stable or update the
external network name in `deploy/sfu-vps/docker-compose.yml`

## o-sfu log source

`o-sfu` writes JSON logs to stdout/stderr

the VPS telemetry collector tails Docker `json-file` container logs directly
from `/var/lib/docker/containers`

the SFU compose service must use the `json-file` logging driver with bounded
rotation and the `com.odoo.sfu.component=server` label:

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

the Docker log option copies that label into each `json-file` record

the collector parses Docker's outer log envelope, drops entries without
`com.odoo.sfu.component=server`, then parses the inner `o-sfu` JSON log body

the collector persists file offsets in `data/otelcol`

do not wrap `o-sfu` in `tee`

## install

clone the telemetry repository on the SFU host:

```bash
sudo mkdir -p /opt/o-sfu-telemetry
sudo chown -R "$USER:$USER" /opt/o-sfu-telemetry

git clone https://github.com/<owner>/o-sfu-telemetry.git /opt/o-sfu-telemetry
cd /opt/o-sfu-telemetry
```

create the local environment file:

```bash
: "${DIAG_TOKEN:?set DIAG_TOKEN to the same diagnostics token used in /etc/o-sfu/o-sfu.env}"
SFU_DOMAIN=<sfu-domain>
GRAFANA_PASSWORD="$(openssl rand -base64 32)"
ALERTMANAGER_WEBHOOK_URL_FILE=/etc/o-sfu-telemetry/alertmanager-webhook-url

read -rsp 'Alertmanager webhook URL: ' ALERTMANAGER_WEBHOOK_URL
printf '\n'
sudo install -d -m 700 -o root -g root /etc/o-sfu-telemetry
sudo install -m 600 -o root -g root /dev/null "${ALERTMANAGER_WEBHOOK_URL_FILE}"
printf '%s\n' "${ALERTMANAGER_WEBHOOK_URL}" | sudo tee "${ALERTMANAGER_WEBHOOK_URL_FILE}" >/dev/null
unset ALERTMANAGER_WEBHOOK_URL

umask 077
cat > deploy/sfu-vps/.env <<EOF
GRAFANA_IMAGE=ghcr.io/<owner>/o-sfu-telemetry-grafana:<tag>
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
GRAFANA_ROOT_URL=https://${SFU_DOMAIN}/grafana/
DIAGNOSTICS_AUTH_TOKEN=${DIAG_TOKEN}
ALERTMANAGER_WEBHOOK_URL_FILE=${ALERTMANAGER_WEBHOOK_URL_FILE}
PROMETHEUS_RETENTION_TIME=15d
PROMETHEUS_RETENTION_SIZE=2GB
EOF
chmod 600 deploy/sfu-vps/.env
```

store the generated Grafana password in the deployment secret store

the reference VPS profile still passes the Grafana password and diagnostics
token as container environment variables for simple bootstrap

production operators should replace that path with file backed secrets or their
deployment secret manager

do not commit `deploy/sfu-vps/.env`

prepare writable bind mounts before the first `up`:

```bash
cd /opt/o-sfu-telemetry

sudo mkdir -p data/grafana data/prometheus data/loki data/tempo data/otelcol
sudo chown -R 472:472 data/grafana
sudo chown -R 65534:65534 data/prometheus
sudo chown -R 10001:10001 data/loki data/tempo data/otelcol
```

the collector reads Docker container logs through a read-only host mount

```bash
sudo test -r /var/lib/docker/containers
```

the VPS compose profile runs the collector as root because Docker log files are
usually owned by the host root account

## host NGINX exposure

when NGINX runs on the host, the SFU compose stack must publish the HTTP
listener on loopback as described in `o-sfu/DEPLOYMENT.md`:

```yaml
services:
  o-sfu:
    ports:
      - "127.0.0.1:8070:8070/tcp"
```

when NGINX runs on the host, expose only Grafana on loopback with a local
compose overlay:

```bash
cd /opt/o-sfu-telemetry

cat > deploy/sfu-vps/docker-compose.host-nginx.yml <<'YAML'
services:
  grafana:
    ports:
      - "127.0.0.1:3000:3000"
YAML
```

add the Grafana subpath to the same NGINX server that serves `o-sfu`:

```nginx
location = /grafana {
    return 301 /grafana/;
}

location ^~ /grafana/ {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_read_timeout 75s;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
}
```

the Grafana `proxy_pass` target intentionally has no URI suffix so NGINX keeps
the `/grafana/...` path expected by Grafana subpath mode

keep the public SFU protections in the same NGINX server:

```nginx
location = /metrics {
    return 404;
}

location ^~ /internal/diagnostics/ {
    return 404;
}
```

if NGINX itself runs as a container on `o-sfu_default`, do not publish the
loopback Grafana port

proxy to `http://grafana:3000` from the NGINX container instead

## start

start the telemetry stack:

```bash
cd /opt/o-sfu-telemetry

sudo docker compose \
  --env-file deploy/sfu-vps/.env \
  --file deploy/sfu-vps/docker-compose.yml \
  --file deploy/sfu-vps/docker-compose.host-nginx.yml \
  pull

sudo docker compose \
  --env-file deploy/sfu-vps/.env \
  --file deploy/sfu-vps/docker-compose.yml \
  --file deploy/sfu-vps/docker-compose.host-nginx.yml \
  up -d
```

omit the `docker-compose.host-nginx.yml` file when NGINX runs inside the Docker
network and proxies to `grafana:3000`

restart the SFU after the telemetry collector is up:

```bash
cd /opt/o-sfu
sudo docker compose up -d o-sfu
```

reload NGINX:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Grafana is available at:

```text
https://<sfu-domain>/grafana/
```

## image policy

the telemetry repository builds one custom image for this deployment:

- `ghcr.io/<owner>/o-sfu-telemetry-grafana:<tag>`

that image is based on the pinned upstream Grafana image and bakes in the
version-pinned Infinity datasource plugin

the remaining compose services run digest-pinned upstream images:

- Prometheus
- Loki
- Tempo
- OpenTelemetry Collector
- blackbox exporter
- Alertmanager

the container image workflow builds and scans the custom Grafana image, then
extracts the remaining compose image references, requires digest pins and scans
those upstream images

promote telemetry updates by changing the compose image references in git,
letting CI pass, then pulling the updated compose stack on the SFU host

## update

for a host NGINX deployment:

```bash
cd /opt/o-sfu-telemetry
git pull --ff-only

sudo docker compose \
  --env-file deploy/sfu-vps/.env \
  --file deploy/sfu-vps/docker-compose.yml \
  --file deploy/sfu-vps/docker-compose.host-nginx.yml \
  pull

sudo docker compose \
  --env-file deploy/sfu-vps/.env \
  --file deploy/sfu-vps/docker-compose.yml \
  --file deploy/sfu-vps/docker-compose.host-nginx.yml \
  up -d --remove-orphans
```

for an in-network NGINX container, omit the local host-NGINX overlay file

after confirming the updated stack is healthy, prune old unused images on a
maintenance window:

```bash
sudo docker image prune --filter "until=168h"
```

update `o-sfu` separately with the `o-sfu` deployment procedure

## retention

container stdout/stderr logs are bounded by the compose logging block:

```text
max-size=20m
max-file=5
```

Prometheus retention is controlled by:

```env
PROMETHEUS_RETENTION_TIME=15d
PROMETHEUS_RETENTION_SIZE=2GB
```

the Prometheus size value applies to persistent TSDB blocks; reserve disk
headroom for WAL and head chunks

Loki keeps ingested SFU logs for `14d`

Loki also has ingestion and per-stream rate limits in `loki/config.yaml`

Tempo keeps traces for `48h`

the source Docker `json-file` logs are bounded by the SFU compose logging block

## validation

check the compose state:

```bash
cd /opt/o-sfu-telemetry

sudo docker compose \
  --env-file deploy/sfu-vps/.env \
  --file deploy/sfu-vps/docker-compose.yml \
  --file deploy/sfu-vps/docker-compose.host-nginx.yml \
  ps
```

validate private SFU access from the shared Docker network:

```bash
DIAG_TOKEN="$(sudo sed -n 's/^DIAGNOSTICS_AUTH_TOKEN=//p' /etc/o-sfu/o-sfu.env | tail -n1)"

sudo docker run --rm --network o-sfu_default curlimages/curl:8.10.1 \
  -i http://host.docker.internal:8070/metrics

sudo docker run --rm --network o-sfu_default curlimages/curl:8.10.1 \
  -i http://host.docker.internal:8070/v1/noop

printf 'header = "Authorization: Bearer %s"\n' "${DIAG_TOKEN}" | \
  sudo docker run --rm -i --network o-sfu_default curlimages/curl:8.10.1 \
    -i -K - http://host.docker.internal:8070/internal/diagnostics/summary
```

expected:

```text
private /metrics -> 200
private /v1/noop -> 200
private diagnostics -> 200
```

validate the public edge:

```bash
curl -i https://<sfu-domain>/grafana/
curl -i https://<sfu-domain>/v1/noop
curl -i https://<sfu-domain>/metrics
curl -i https://<sfu-domain>/internal/diagnostics/summary
```

expected:

```text
public /grafana/ -> configured operator-auth challenge, Grafana login or redirect
public /v1/noop -> 200 with {"result":"ok"}
public /metrics -> 404
public diagnostics -> 404
```

validate log ingestion after `o-sfu` emits at least one fresh log:

```bash
sudo docker run --rm --network o-sfu_default curlimages/curl:8.10.1 \
  -G http://loki:3100/loki/api/v1/query \
  --data-urlencode 'query={service_name="o-sfu"}'
```

validate the dashboards in Grafana:

- Prometheus target for `o-sfu` is up
- noop blackbox probe is up
- diagnostics blackbox probe is up
- Alertmanager sends a test alert to the configured operator webhook
- dashboards load without datasource errors
- Loki Explore returns logs for `{service_name="o-sfu"}`
- Tempo Explore receives traces after live traffic

## deployment checklist

network:

- `o-sfu/DEPLOYMENT.md` network checklist is complete
- `o-sfu_default` exists
- telemetry compose joins `o-sfu_default`
- `o-sfu` has the `host.docker.internal` network alias
- host NGINX deployments publish `o-sfu` HTTP only on `127.0.0.1:8070`
- `o-sfu` can resolve `otel-collector`
- Prometheus can scrape private `/metrics`
- blackbox exporter can probe private `/v1/noop`
- blackbox exporter can probe private diagnostics with bearer auth
- public NGINX still blocks `/metrics`
- public NGINX still blocks `/internal/diagnostics/...`

grafana:

- `GRAFANA_ROOT_URL` is `https://<sfu-domain>/grafana/`
- `GF_SERVER_SERVE_FROM_SUB_PATH=true` is active through compose
- anonymous auth is disabled
- admin password is provisioned outside the repository
- operator access control is enforced before or at Grafana
- unauthenticated `/grafana/` requests receive the configured operator-auth challenge or Grafana login flow
- host NGINX exposes Grafana only on `127.0.0.1:3000`, or container NGINX proxies privately to `grafana:3000`
- NGINX forwards `X-Forwarded-Host` from `$host`

collector:

- `TELEMETRY_LOG_FORMAT=json` is set on `o-sfu`
- `TELEMETRY_DEPLOYMENT_ENVIRONMENT=production` is set on `o-sfu`
- `TELEMETRY_OTLP_ENDPOINT=http://otel-collector:4318` is set on `o-sfu`
- `DIAGNOSTICS_AUTH_TOKEN` is set on `o-sfu`
- `o-sfu` uses Docker `json-file` logging
- `o-sfu` has the `com.odoo.sfu.component=server` Docker label
- the `json-file` logging options include `labels: "com.odoo.sfu.component"`
- telemetry containers receive only `DIAGNOSTICS_AUTH_TOKEN`, not the full SFU env file
- collector can export traces to Tempo
- collector can export logs to Loki
- filelog offsets persist under `data/otelcol`
- the collector can read `/var/lib/docker/containers`

storage:

- Docker or runtime logs are bounded
- Prometheus has retention time and size caps
- Loki retention matches the incident-response policy
- Tempo retention matches the incident-response policy
- bind-mounted data directories have the correct container ownership
- disk usage is monitored

validation:

- `o-sfu` boot logs show `deployment_environment=production`
- `o-sfu` boot logs show `trace_export_otlp_endpoint=http://otel-collector:4318`
- Grafana login works
- dashboards load without datasource errors
- Prometheus, blackbox, Loki and Tempo datasources are healthy
- public metrics and diagnostics remain blocked

## environment variables

telemetry compose:

| variable | default | description |
| --- | --- | --- |
| `GRAFANA_IMAGE` | required | CI-built Grafana image with the Infinity datasource plugin baked in |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana administrator login |
| `GRAFANA_ADMIN_PASSWORD` | required | Grafana administrator password |
| `GRAFANA_ROOT_URL` | required | public Grafana URL, including `/grafana/` |
| `DIAGNOSTICS_AUTH_TOKEN` | required | diagnostics bearer token passed only to Grafana and blackbox exporter |
| `ALERTMANAGER_WEBHOOK_URL_FILE` | required | host file containing the operator notification webhook URL |
| `PROMETHEUS_RETENTION_TIME` | `15d` | Prometheus time retention |
| `PROMETHEUS_RETENTION_SIZE` | `2GB` | Prometheus TSDB block retention target, not a full disk cap |

required `o-sfu` variables for telemetry:

| variable | value | description |
| --- | --- | --- |
| `TELEMETRY_LOG_FORMAT` | `json` | emits one JSON object per log line |
| `TELEMETRY_DEPLOYMENT_ENVIRONMENT` | `production` | enables production trace sampling |
| `TELEMETRY_OTLP_ENDPOINT` | `http://otel-collector:4318` | collector OTLP HTTP receiver |
| `DIAGNOSTICS_AUTH_TOKEN` | secret | bearer token for private diagnostics dashboards and probes |
