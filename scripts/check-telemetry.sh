#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
telemetry_scratch="$(mktemp -d)"
trap 'rm -rf "$telemetry_scratch"' EXIT
printf '%s' 'telemetry-validation-token' > "$telemetry_scratch/token"

docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example --profile linux-infra config --quiet
docker compose --env-file deploy/sfu-vps/.env.example --file deploy/sfu-vps/docker-compose.yml config --quiet
telemetry_image="$(docker compose --env-file .env.example config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["prometheus"]["image"])')"
collector_image="$(docker compose --env-file .env.example config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["otel-collector"]["image"])')"
python3 scripts/check_dashboard_queries.py "$telemetry_scratch/dashboard-queries.json"
python3 scripts/check_graph_queries.py --check
python3 scripts/check_collector_logs.py "$collector_image"

for telemetry_config in prometheus/prometheus.yml deploy/sfu-vps/prometheus.yml prometheus/prometheus.host-metrics.example.yml
do
  docker run --rm --network none --read-only \
    -v "$PWD:/workspace:ro" \
    -v "$PWD/prometheus:/etc/prometheus:ro" \
    -v "$telemetry_scratch/token:/run/secrets/o_sfu_diagnostics_token:ro" \
    --entrypoint /bin/promtool "$telemetry_image" \
    check config "/workspace/$telemetry_config"
done

docker run --rm --network none --read-only \
  -v "$telemetry_scratch:/validation:ro" \
  --entrypoint /bin/promtool "$telemetry_image" \
  check rules /validation/dashboard-queries.json
docker run --rm --network none --read-only --tmpfs /tmp \
  -v "$PWD:/workspace:ro" -w /workspace \
  --entrypoint /bin/promtool "$telemetry_image" \
  test rules tests/prometheus-rules.test.yml
