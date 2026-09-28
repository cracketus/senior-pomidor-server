"""Bounded local Docker harness for actual Edge/Core applications."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEVICE = "edge-staging-cross-repo"
SCENARIOS = (
    "normal-delivery",
    "duplicate-http-mqtt",
    "core-outage-spool-growth",
    "edge-restart-pending",
    "fresh-during-backlog-replay",
    "core-recovery-full-drain",
    "lost-ack-after-persistence",
    "delayed-stale-future-out-of-order",
    "high-vpd",
    "malformed-rejected",
    "legacy-fixtures",
)
INVARIANTS: dict[str, tuple[str, ...]] = dict.fromkeys(SCENARIOS, ("sp-inv-001", "sp-inv-002", "sp-inv-003"))
INVARIANTS["delayed-stale-future-out-of-order"] = ("sp-inv-003", "sp-inv-004")
INVARIANTS["malformed-rejected"] = ("sp-inv-005",)
INVARIANTS["legacy-fixtures"] = ("sp-inv-005",)

ENV = {
    key: value
    for key, value in os.environ.items()
    if key in {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "DOCKER_CONFIG"}
}


class HarnessError(RuntimeError):
    """Bounded error safe for the public report."""


def command(argv: list[str], *, cwd: Path | None = None, timeout: int = 120, diagnostics: Path | None = None) -> str:
    result = subprocess.run(  # nosec B603
        argv, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        if diagnostics is not None:
            diagnostics.write_text(result.stderr[-16000:])
        # Child output is not safe to publish (Docker/git can expose environment details).
        raise HarnessError(f"{argv[0]} operation failed (exit {result.returncode})")
    return result.stdout


def revision(source: Path) -> str:
    sha = command(["git", "rev-parse", "HEAD"], cwd=source).strip()
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise HarnessError("invalid Git identity")
    if command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source).strip():
        raise HarnessError("source has tracked modifications; commit before running")
    return sha


def compose_config(core_image: str, edge_image: str, harness_image: str) -> dict[str, Any]:
    app_env = {
        "DATABASE_URL": "postgresql+psycopg://verification:verification@postgres:5432/verification",
        "DEPLOYMENT_MODE": "staging",
        "STAGING_DEVICE_PREFIX": "edge-staging-",
        "MQTT_HOST": "mqtt",
        "MQTT_TOPIC_PREFIX": "verification",
        "GRAFANA_CLOUD_EXPORT_ENABLED": "false",
        "WORKER_HEALTH_FILE": "/health/worker.json",
    }
    app = {
        "image": core_image,
        "environment": app_env,
        "volumes": ["health:/health"],
        "depends_on": {"postgres": {"condition": "service_healthy"}},
    }
    services: dict[str, Any] = {
        "postgres": {
            "image": "postgres:16-alpine",
            "environment": {
                "POSTGRES_USER": "verification",
                "POSTGRES_PASSWORD": "verification",  # nosec B105 - isolated synthetic test database
                "POSTGRES_DB": "verification",
            },
            "volumes": ["database:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U verification"],
                "interval": "1s",
                "timeout": "3s",
                "retries": 60,
            },
        },
        "mqtt": {
            "image": "eclipse-mosquitto:2",
            "command": [
                "sh",
                "-c",
                'printf "listener 1883\\nallow_anonymous true\\n" > /tmp/test.conf; exec mosquitto -c /tmp/test.conf',
            ],
        },
        "migrate": {**app, "command": ["alembic", "upgrade", "head"]},
        "api": {
            **app,
            "command": ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            "depends_on": {"migrate": {"condition": "service_completed_successfully"}},
        },
        "worker": {
            **app,
            "command": ["python", "-m", "app.mqtt_worker"],
            "depends_on": {"migrate": {"condition": "service_completed_successfully"}},
        },
        "proxy": {"image": harness_image, "command": ["python", "/harness/proxy.py"]},
        "edge": {
            "image": edge_image,
            "command": ["python", "/harness/edge_driver.py"],
            "volumes": ["spool:/data", "driver:/harness:ro"],
            "environment": {
                "PYTHONPATH": "/app",
                "DEVICE_ID": DEVICE,
                "MOCK_SENSORS": "true",
                "HTTP_ENABLED": "true",
                "CORE_HTTP_URL": "http://proxy:8090/telemetry",
                "HTTP_TIMEOUT_SECONDS": "2",
                "MQTT_HOST": "mqtt",
                "MQTT_TOPIC_PREFIX": "verification",
                "POLL_INTERVAL_SECONDS": "1",
                "CAMERA_ENABLED": "false",
                "PHOTO_UPLOAD_ENABLED": "false",
                "INDICATOR_ENABLED": "false",
                "INDICATOR_BACKEND": "mock",
                "TELEMETRY_SPOOL_DB_PATH": "/data/spool.sqlite3",
                "LOCAL_STORAGE_DIR": "/data/legacy",
                "LOCAL_EVENT_DIR": "/data/events",
                "WATCHDOG_HEARTBEAT_FILE": "/data/heartbeat.json",
                "TELEMETRY_SPOOL_RETRY_SCHEDULE_SECONDS": "1,1,1",
                "TELEMETRY_SPOOL_RETRY_JITTER": "0",
                "TELEMETRY_SPOOL_RATE_LIMIT_PER_SECOND": "2",
                "TELEMETRY_SPOOL_BATCH_SIZE": "1",
                "TELEMETRY_SPOOL_CAPACITY_MB": "65536",
            },
        },
        "driver-init": {
            "image": harness_image,
            "command": ["cp", "/harness/edge_driver.py", "/driver/edge_driver.py"],
            "volumes": ["driver:/driver"],
        },
    }
    services["edge"]["depends_on"] = {"driver-init": {"condition": "service_completed_successfully"}}
    for service in services.values():
        service["networks"] = ["isolated"]
        service["logging"] = {"driver": "json-file", "options": {"max-size": "1m", "max-file": "1"}}
        service["mem_limit"] = "512m"
        service["cpus"] = 1.0
        service["pids_limit"] = 128
    return {
        "services": services,
        "networks": {"isolated": {"internal": True}},
        "volumes": {name: {} for name in ("health", "database", "spool", "driver")},
    }


def validate_isolation(config: dict[str, Any]) -> None:
    if config["networks"] != {"isolated": {"internal": True}}:
        raise HarnessError("network must be private and internal")
    for service in config["services"].values():
        if any(key in service for key in ("privileged", "devices", "network_mode", "pid", "cap_add", "env_file")):
            raise HarnessError("unsafe service configuration")
        if any(not port.startswith("127.0.0.1::") for port in service.get("ports", [])):
            raise HarnessError("ports must use ephemeral loopback binding")
        if any(volume.split(":")[0] not in config["volumes"] for volume in service.get("volumes", [])):
            raise HarnessError("only owned named volumes allowed")
        if service.get("environment", {}).get("GRAFANA_CLOUD_EXPORT_ENABLED", "false") != "false":
            raise HarnessError("external export prohibited")
    if any(value for value in config["volumes"].values()):
        raise HarnessError("external/named volumes prohibited")


def utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def wait_for(probe: Any, *, timeout: int = 90) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(0.2)
    raise HarnessError("bounded observation deadline exceeded")


class ComposeTransport(httpx.BaseTransport):
    """Reach test services without publishing internal-network ports or adding egress."""

    def __init__(self, harness: Any):
        self.harness = harness

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        message = json.dumps({"method": request.method, "url": str(request.url), "body": request.content.decode()})
        try:
            result = json.loads(
                self.harness.compose("exec", "-T", "proxy", "python", "/harness/http_request.py", message)
            )
        except (HarnessError, ValueError, subprocess.SubprocessError) as exc:
            raise httpx.ConnectError("internal test request unavailable", request=request) from exc
        return httpx.Response(result["status"], content=result["body"], request=request)


class Harness:
    def __init__(self, output: Path):
        self.output = output.resolve()
        self.project = f"sp-cross-{uuid.uuid4().hex[:16]}"
        self.compose_file = self.output / "compose.json"
        self.client = httpx.Client(timeout=6, trust_env=False, transport=ComposeTransport(self))
        self.urls: dict[str, str] = {}
        self.results: list[dict[str, Any]] = []
        self.samples: dict[str, str] = {}
        self.sequence = 0
        self.epoch = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)

    def compose(self, *args: str) -> str:
        return command(
            [
                "docker",
                "compose",
                "--env-file",
                str(self.output / "empty.env"),
                "-p",
                self.project,
                "-f",
                str(self.compose_file),
                *args,
            ],
            timeout=240,
            diagnostics=self.output / "compose-error.log",
        )

    def url(self, name: str, port: int) -> str:
        if (name, port) not in {("api", 8000), ("edge", 8091), ("proxy", 8090)}:
            raise HarnessError("unexpected internal endpoint")
        return f"http://{name}:{port}"

    def get(self, owner: str, path: str) -> Any:
        response = self.client.get(self.urls[owner] + path)
        response.raise_for_status()
        return response.json()

    def control(self, mode: str) -> None:
        self.client.post(self.urls["proxy"] + "/control", json={"mode": mode}).raise_for_status()

    def records(self) -> list[dict[str, Any]]:
        return self.get("edge", "/records")

    def history(self) -> list[dict[str, Any]]:
        return self.get("api", f"/api/v1/devices/{DEVICE}/telemetry?limit=500")

    def sample(self, *, timestamp: str | None = None, high_vpd: bool = False) -> str:
        self.sequence += 1
        timestamp = timestamp or (self.epoch + timedelta(seconds=self.sequence)).isoformat().replace("+00:00", "Z")
        body: dict[str, Any] = {"timestamp": timestamp}
        if high_vpd:
            body.update(temperature=38.0, humidity=25.0)
        self.client.post(self.urls["edge"] + "/sample", json=body).raise_for_status()
        row = wait_for(lambda: next((r for r in self.records() if r["observed_at"] == timestamp), None))
        self.samples[row["record_id"]] = timestamp
        return row["record_id"]

    def pending(self, ids: list[str]) -> bool:
        selected = [r for r in self.records() if r["record_id"] in ids]
        return len(selected) == len(ids) and all(r["state"] in {"pending", "in_flight"} for r in selected)

    def drain(self) -> None:
        wait_for(
            lambda: len(self.records()) == len(self.samples) and all(r["state"] == "delivered" for r in self.records())
        )
        wait_for(lambda: len(self.history()) == len(self.samples))

    def counts(self) -> dict[str, int]:
        # Read API and SQL independently; ingestion may advance between snapshots.
        def snapshot() -> Any:
            rows = self.history()
            ids = [r["record_id"] for r in rows]
            stored = json.loads(
                self.compose(
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "verification",
                    "-tA",
                    "-c",
                    "SELECT COALESCE(json_agg(record_id),'[]') FROM telemetry_events "
                    "WHERE device_id='edge-staging-cross-repo'",
                )
            )
            return (rows, ids, stored) if set(ids) == set(stored) and len(ids) == len(stored) else None

        rows, ids, stored = wait_for(snapshot)
        expected = set(self.samples)
        if any(r["timestamp_utc"] != self.samples.get(r["record_id"]) for r in rows):
            raise HarnessError("sp-inv-003 observation time changed")
        return {
            "generated": len(expected),
            "persisted": len(stored),
            "read_back": len(ids),
            "duplicates": len(stored) - len(set(stored)),
            "missing": len(expected - set(stored)),
            "unexpected": len(set(stored) - expected),
        }

    def checkpoint(self, name: str, *, pending: bool = False) -> None:
        counts = self.counts()
        if counts["duplicates"] or counts["unexpected"] or (not pending and counts["missing"]):
            raise HarnessError("sp-inv-001/002 identity or count mismatch")
        self.results.append(
            {
                "scenario_id": name,
                "status": "PASS",
                "counts": counts,
                "finished_at_utc": utc(),
                "pending_expected": pending,
                "invariant_ids": list(INVARIANTS[name]),
            }
        )

    def scenarios(self) -> None:
        self.sample(timestamp=(self.epoch - timedelta(days=3)).isoformat().replace("+00:00", "Z"))
        self.drain()
        if self.get("api", f"/api/v1/operator/edges/{DEVICE}/reliability")["freshness"]["status"] != "STALE":
            raise HarnessError("sp-inv-004 stale input became healthy")
        self.sample()
        self.drain()
        self.checkpoint("normal-delivery")
        self.control("outage")
        mirror = self.sample()
        wait_for(lambda: any(r["record_id"] == mirror for r in self.history()) and self.pending([mirror]))
        row = next(r for r in self.records() if r["record_id"] == mirror)
        response = self.client.post(self.urls["api"] + "/api/v1/edge/telemetry", json=row["payload"])
        response.raise_for_status()
        if response.json().get("status") != "duplicate":
            raise HarnessError("sp-inv-002 replay was not duplicate")
        self.control("pass")
        self.drain()
        self.checkpoint("duplicate-http-mqtt")

        # Stop both Core ingestion paths: MQTT PUBACK cannot complete the spool.
        self.control("outage")
        self.compose("stop", "worker")
        backlog = [self.sample() for _ in range(8)]
        wait_for(lambda: self.pending(backlog))
        self.checkpoint("core-outage-spool-growth", pending=True)
        before = {r["record_id"] for r in self.records()}
        self.compose("restart", "edge")
        self.urls["edge"] = self.url("edge", 8091)
        wait_for(lambda: {r["record_id"] for r in self.records()} == before and self.pending(backlog))
        self.checkpoint("edge-restart-pending", pending=True)
        self.compose("start", "worker")
        self.control("pass")
        fresh = self.sample()
        wait_for(lambda: any(r["record_id"] == fresh and r["state"] == "delivered" for r in self.records()))
        if not any(r["record_id"] in backlog and r["state"] != "delivered" for r in self.records()):
            raise HarnessError("fresh delivery not observed while backlog remained")
        self.checkpoint("fresh-during-backlog-replay", pending=True)
        self.drain()
        self.checkpoint("core-recovery-full-drain")

        self.compose("stop", "worker")  # ensure HTTP commit, not MQTT, proves lost ACK
        self.control("lost-ack")
        lost = self.sample()
        wait_for(
            lambda: (
                self.get("proxy", "/")["lost"] > 0
                and any(r["record_id"] == lost for r in self.history())
                and self.pending([lost])
            )
        )
        self.control("pass")
        self.drain()
        if next(r for r in self.records() if r["record_id"] == lost)["attempt_count"] < 2:
            raise HarnessError("lost ACK did not cause a retry")
        self.checkpoint("lost-ack-after-persistence")
        self.compose("start", "worker")

        for offset in (181, 121, 61):
            self.sample(
                timestamp=(datetime.now(UTC) - timedelta(seconds=offset))
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                high_vpd=True,
            )
        hot = self.sample(
            timestamp=(datetime.now(UTC) - timedelta(seconds=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            high_vpd=True,
        )
        self.drain()
        payload = next(r["payload"] for r in self.records() if r["record_id"] == hot)
        if payload["pods"]["pod_1"]["metrics"]["air_vpd_kpa"] <= 3:
            raise HarnessError("Edge formatter did not derive high VPD")
        self.compose("exec", "-T", "api", "python", "-c", (ROOT / "tests/cross_repo/estimator_replay.py").read_text())
        state = self.get("api", f"/api/v1/state/latest?node_id={DEVICE}")
        if state["schema_version"] != "state_v1" or (state["env"].get("vpd_kpa") or 0) <= 1.6:
            raise HarnessError("canonical high VPD not produced")
        persisted = self.get("api", f"/api/v1/devices/{DEVICE}/latest")
        if (
            persisted["record_id"] != hot
            or next(r for r in persisted["readings"] if r["pod_key"] == "pod_1")["metrics"]["air_vpd_kpa"] <= 3
        ):
            raise HarnessError("high VPD not persisted")
        self.get("api", f"/api/v1/sensor-health/latest?node_id={DEVICE}")
        anomalies = self.get("api", f"/api/v1/anomalies/active?node_id={DEVICE}")
        if "HIGH_VPD" not in {item["type"] for item in anomalies}:
            raise HarnessError("canonical HIGH_VPD anomaly missing")
        self.get("api", f"/health/summary?node_id={DEVICE}")
        # Also exercise production latest/window/device selection and worker wiring.
        worker_sample = self.sample(timestamp=utc(), high_vpd=True)
        self.drain()
        self.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "from app.state_estimator_worker import run_once; assert run_once() == 1",
        )
        worker_state = self.get("api", f"/api/v1/state/latest?node_id={DEVICE}")
        if (
            worker_state["state_id"] == state["state_id"]
            or datetime.fromisoformat(worker_state["ts"].replace("Z", "+00:00"))
            != datetime.fromisoformat(self.samples[worker_sample].replace("Z", "+00:00"))
            or (worker_state["env"].get("vpd_kpa") or 0) <= 1.6
        ):
            raise HarnessError("production estimator worker did not advance canonical state")
        self.checkpoint("high-vpd")
        self.sample(timestamp=(self.epoch - timedelta(days=2)).isoformat().replace("+00:00", "Z"))
        self.drain()
        latest = self.get("api", f"/api/v1/devices/{DEVICE}/latest")
        if latest["record_id"] == list(self.samples)[-1]:
            raise HarnessError("delayed replay replaced latest observation")
        future = self.sample(
            timestamp=(datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        self.drain()
        reliability = self.get("api", f"/api/v1/operator/edges/{DEVICE}/reliability")
        if reliability["status"] != "UNKNOWN" or reliability["freshness"]["status"] != "UNKNOWN":
            raise HarnessError("sp-inv-004 future input became healthy")
        if self.get("api", f"/api/v1/devices/{DEVICE}/latest")["record_id"] != future:
            raise HarnessError("future observation identity lost")
        self.checkpoint("delayed-stale-future-out-of-order")
        invalid = dict(self.records()[0]["payload"])
        invalid.update(record_id="malformed-check", timestamp_utc="invalid-time")
        response = self.client.post(self.urls["api"] + "/api/v1/edge/telemetry", json=invalid)
        response.raise_for_status()
        if response.json().get("status") != "rejected":
            raise HarnessError("sp-inv-005 malformed observation not rejected")
        self.checkpoint("malformed-rejected")
        for version in ("v1", "v2"):
            fixture = json.loads((ROOT / "tests/fixtures/contracts" / f"telemetry_{version}.json").read_text())
            node = f"edge-staging-legacy-{version}"
            fixture["device_id"] = node
            if "record_id" in fixture:
                fixture["record_id"] = f"legacy-{version}"
            self.compose(
                "exec",
                "-T",
                "mqtt",
                "mosquitto_pub",
                "-h",
                "mqtt",
                "-q",
                "1",
                "-t",
                f"verification/{node}/telemetry",
                "-m",
                json.dumps(fixture),
            )
            wait_for(lambda node=node: self.get("api", f"/api/v1/devices/{node}/telemetry"))
            response = self.client.post(self.urls["api"] + "/api/v1/edge/telemetry", json=fixture)
            response.raise_for_status()
            rows = self.get("api", f"/api/v1/devices/{node}/telemetry")
            if len(rows) != 1 or rows[0]["schema_version"] != fixture["schema_version"]:
                raise HarnessError("legacy fixture readback mismatch")
        self.checkpoint("legacy-fixtures")


def run(
    core_source: Path, edge_source: Path, output: Path, *, core_ref: str | None = None, edge_ref: str | None = None
) -> int:
    output.mkdir(parents=True, exist_ok=False)
    harness = Harness(output)
    report: dict[str, Any] = {
        "schema_version": "senior-pomidor.cross-repo-e2e.v1",
        "status": "FAIL",
        "evidence_scope": "CI",
        "started_at_utc": utc(),
        "scenarios": [],
        "future_action_invariants": "NOT_IMPLEMENTED",
    }
    started = False
    try:
        core_sha, edge_sha = revision(core_source), revision(edge_source)
        report.update(core={"git_sha": core_sha}, edge={"git_sha": edge_sha})
        endpoint = command(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]).strip()
        if not endpoint.startswith(("unix://", "npipe://")):
            raise HarnessError("only local Docker endpoints permitted")
        core_image, edge_image, driver_image = [f"{harness.project}-{x}" for x in ("core", "edge", "driver")]
        for source, image, sha, owner in (
            (core_source, core_image, core_sha, "core"),
            (edge_source, edge_image, edge_sha, "edge"),
        ):
            supplied = core_ref if owner == "core" else edge_ref
            if supplied:
                if not re.fullmatch(r"ghcr\.io/cracketus/[a-z0-9-]+@sha256:[0-9a-f]{64}", supplied):
                    raise HarnessError("published image must be pinned by digest")
                command(["docker", "pull", supplied], timeout=600)
                label = command(
                    [
                        "docker",
                        "image",
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                        supplied,
                    ]
                ).strip()
                if label != sha:
                    raise HarnessError("OCI revision differs from selected Git SHA")
                command(["docker", "tag", supplied, image])
                report[owner]["registry_ref"] = supplied
            else:
                # Export only tracked committed bytes; no secrets/untracked files in build context.
                with tempfile.TemporaryDirectory(prefix="sp-cross-build-") as directory:
                    context = Path(directory)
                    archive = context / "source.tar"
                    command(["git", "archive", "--format=tar", f"--output={archive}", sha], cwd=source)
                    with tarfile.open(archive) as stream:
                        stream.extractall(context / "source", filter="data")
                    args = ["docker", "build", "--label", f"org.opencontainers.image.revision={sha}", "-t", image]
                    if owner == "edge":
                        args += ["--build-arg", "INSTALL_HARDWARE_DEPS=false"]
                    command([*args, str(context / "source")], timeout=900)
            image_id = command(["docker", "image", "inspect", "--format", "{{.Id}}", image]).strip()
            report[owner]["image_id"] = image_id
        driver_dir = output / "driver"
        driver_dir.mkdir()
        for name in ("edge_driver.py", "proxy.py", "http_request.py"):
            (driver_dir / name).write_bytes((ROOT / "tests/cross_repo" / name).read_bytes())
        (driver_dir / "Dockerfile").write_text("FROM python:3.12-slim\nCOPY *.py /harness/\n")
        command(["docker", "build", "-t", driver_image, str(driver_dir)], timeout=600)
        config = compose_config(core_image, edge_image, driver_image)
        validate_isolation(config)
        harness.compose_file.write_text(json.dumps(config))
        (output / "empty.env").write_text("")
        report["config_sha256"] = hashlib.sha256(harness.compose_file.read_bytes()).hexdigest()
        harness.compose("config", "--quiet")
        # Random, task-owned project; never adopt existing containers/resources.
        if harness.compose("ps", "-aq").strip():
            raise HarnessError("refusing to adopt an existing project")
        started = True
        harness.compose("up", "-d")
        harness.urls = {
            name: harness.url(name, port) for name, port in (("api", 8000), ("edge", 8091), ("proxy", 8090))
        }
        wait_for(lambda: harness.get("api", "/ready"))
        wait_for(lambda: isinstance(harness.records(), list))
        harness.scenarios()
        report["status"] = "PASS"
    except (HarnessError, OSError, subprocess.SubprocessError, httpx.HTTPError, KeyError, ValueError) as exc:
        report["error_code"] = (
            str(exc) if isinstance(exc, HarnessError) else type(exc).__name__
        )  # bounded, no raw subprocess/request values
    finally:
        report["scenarios"] = harness.results
        report["finished_at_utc"] = utc()
        if started:
            try:
                logs = harness.compose("logs", "--no-color", "--tail", "100")
                (output / "services.log").write_text(logs[-200000:])
            except (HarnessError, OSError, subprocess.SubprocessError):
                report["diagnostics_status"] = "FAIL"
            finally:
                try:
                    harness.compose("down", "--timeout", "10")
                except (HarnessError, OSError, subprocess.SubprocessError):
                    report["status"] = "FAIL"
                    report["cleanup_status"] = "FAIL"
        harness.client.close()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", type=Path, default=ROOT)
    parser.add_argument("--edge-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory for bounded evidence")
    parser.add_argument("--core-image", help="optional existing ghcr.io image pinned by digest")
    parser.add_argument("--edge-image", help="optional existing ghcr.io image pinned by digest")
    args = parser.parse_args()
    return run(
        args.core_source.resolve(),
        args.edge_source.resolve(),
        args.output.resolve(),
        core_ref=args.core_image,
        edge_ref=args.edge_image,
    )


if __name__ == "__main__":
    sys.exit(main())
