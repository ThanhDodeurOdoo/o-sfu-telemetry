#!/usr/bin/env python3
"""Run both production log receivers against normalization fixtures.

The image argument must be the Collector image from Docker Compose. Receiver
operators and processors come from the production config. Only file offsets,
storage and the log exporter change for this isolated container. The original
log body must remain exact while structured metadata resolves span context.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = pathlib.Path(__file__).resolve().parent.parent


def docker(*arguments):
    """Run Docker and raise subprocess.CalledProcessError on a failed command."""
    result = subprocess.run(
        ["docker", *arguments], check=True, text=True, capture_output=True
    )
    return result.stdout + result.stderr


def records(path):
    """Read complete OTLP JSON export lines while the exporter may append."""
    result = []
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for resource in payload.get("resourceLogs", []):
            for scope in resource.get("scopeLogs", []):
                result.extend(scope.get("logRecords", []))
    return result


def attribute(value):
    """Decode an OTLP JSON AnyValue without converting integers to floats."""
    if "intValue" in value:
        return int(value["intValue"])
    if "arrayValue" in value:
        return [attribute(item) for item in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return {item["key"]: attribute(item["value"]) for item in value["kvlistValue"].get("values", [])}
    return next(iter(value.values()), None)


def check(image):
    """Assert exact bodies from JSONL and labelled Docker logs.

    Raises AssertionError for changed values, types, missing logs or leaked
    records from Docker containers without the SFU server label.
    """
    fixtures = json.loads((ROOT / "tests/collector-logs.json").read_text())
    with tempfile.TemporaryDirectory(prefix="o-sfu-collector-") as directory:
        scratch = pathlib.Path(directory)
        scratch.chmod(0o755)
        jsonl = scratch / "jsonl"
        docker_logs = scratch / "docker" / ("a" * 64)
        output = scratch / "output"
        for path in (jsonl, docker_logs, output):
            path.mkdir(parents=True)
        output.chmod(0o777)
        lines = [
            item["input"] if isinstance(item["input"], str) else json.dumps(item["input"])
            for item in fixtures
        ]
        (jsonl / "runtime.jsonl").write_text("\n".join(lines) + "\n")
        wrapped = [
            json.dumps({"log": line + "\n", "stream": "stdout", "time": "2026-09-17T08:09:10Z", "attrs": {"com.odoo.sfu.component": "server"}})
            for line in lines
        ]
        wrapped.append(json.dumps({"log": "unlabelled container\n", "stream": "stdout", "time": "2026-09-17T08:09:10Z"}))
        (docker_logs / (("a" * 64) + "-json.log")).write_text("\n".join(wrapped) + "\n")
        override = {
            "receivers": {name: {"start_at": "beginning"} for name in ("filelog/docker", "filelog/jsonl")},
            "exporters": {"file/fixture": {"path": "/output/logs.json", "flush_interval": "100ms"}},
            "service": {"pipelines": {"logs": {"exporters": ["file/fixture"]}}},
        }
        (scratch / "override.json").write_text(json.dumps(override))
        name = "o-sfu-collector-" + uuid.uuid4().hex[:12]
        started = False
        try:
            docker("run", "--detach", "--name", name, "--network", "none", "--read-only",
                   "--tmpfs", "/var/lib/otelcol:uid=10001,gid=10001",
                   "--volume", str(ROOT / "otel-collector/config.yaml") + ":/config.yaml:ro",
                   "--volume", str(scratch / "override.json") + ":/override.json:ro",
                   "--volume", str(jsonl) + ":/var/log/o-sfu:ro",
                   "--volume", str(scratch / "docker") + ":/var/lib/docker/containers:ro",
                   "--volume", str(output) + ":/output", image, "--config=/config.yaml", "--config=/override.json")
            started = True
            deadline = time.monotonic() + 20
            exported = []
            while time.monotonic() < deadline:
                exported = records(output / "logs.json")
                if len(exported) >= 2 * len(fixtures):
                    break
                time.sleep(0.1)
            assert len(exported) == 2 * len(fixtures), (len(exported), docker("logs", name))
            expected = {line: item["expected"] for line, item in zip(lines, fixtures)}
            seen = {receiver: set() for receiver in ("docker", "jsonl")}
            for record in exported:
                body = record["body"]["stringValue"]
                attributes = {item["key"]: attribute(item["value"]) for item in record.get("attributes", [])}
                receiver = "docker" if attributes["log.file.path"].startswith("/var/lib/docker/") else "jsonl"
                if receiver == "docker":
                    assert body.endswith("\n"), f"Changed Docker log terminator: {body!r}"
                    body = body[:-1]
                assert body in expected, f"Changed original log body: {body!r}"
                assert body not in seen[receiver], f"Duplicate {receiver} log: {body!r}"
                seen[receiver].add(body)
                actual = {key: value for key, value in attributes.items() if not key.startswith("log.")}
                assert json.dumps(actual, sort_keys=True) == json.dumps(expected[body], sort_keys=True), f"Unexpected {receiver} metadata: {actual!r}"
            assert all(len(values) == len(fixtures) for values in seen.values()), seen
            print(f"Collector log fixtures passed for JSONL and Docker ({len(exported)} records)")
        except Exception:
            if started:
                print(docker("logs", name), file=sys.stderr)
            raise
        finally:
            if started:
                docker("rm", "--force", name)


if __name__ == "__main__":
    check(sys.argv[1])
