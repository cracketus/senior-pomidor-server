import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA_V2

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCKER_E2E") != "1",
    reason="set RUN_DOCKER_E2E=1 to run Docker Compose end-to-end tests",
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = os.getenv("SENIOR_POMIDOR_E2E_PROJECT", f"senior-pomidor-server-e2e-{os.getpid()}")
if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", PROJECT_NAME):
    raise RuntimeError("SENIOR_POMIDOR_E2E_PROJECT must be a bounded Compose project name")
BASE_URL = "http://127.0.0.1:18080"
GRAFANA_BASE_URL = "http://127.0.0.1:13000"
EDGE_ALERT_TITLES = (
    "Edge reliability unavailable or stale",
    "Edge watchdog critical",
    "Edge spool or disk critical",
    "Edge aggregate critical",
    "Edge application inactive",
)
READONLY_TABLES = (
    "devices",
    "telemetry_events",
    "pod_readings",
    "pod_errors",
    "photos",
    "telemetry_pod_readings_flat",
    "state_snapshots",
    "sensor_health_snapshots",
    "anomaly_records",
    "estimator_diagnostics",
)
COMPOSE_ENV = {
    "APP_IMAGE": "senior-pomidor-server:e2e",
    "POSTGRES_DB": "senior_pomidor_e2e",
    "POSTGRES_USER": "senior_pomidor_e2e",
    "POSTGRES_PASSWORD": "synthetic-e2e-database-only",
    "DATABASE_URL": "postgresql+psycopg://senior_pomidor_e2e:synthetic-e2e-database-only@postgres:5432/senior_pomidor_e2e",
    "GRAFANA_DB_USER": "grafana_e2e_reader",
    "GRAFANA_DB_PASSWORD": "synthetic-e2e-grafana-only",
    "GRAFANA_ADMIN_USER": "e2e-admin",
    "GRAFANA_ADMIN_PASSWORD": "synthetic-e2e-admin-only",
    "LAN_BIND_ADDRESS": "127.0.0.1",
    "POSTGRES_BIND_ADDRESS": "127.0.0.1",
    "API_PUBLISHED_PORT": "18080",
    "GRAFANA_PUBLISHED_PORT": "13000",
    "POSTGRES_PUBLISHED_PORT": "15432",
    "MQTT_PUBLISHED_PORT": "11883",
    "MQTT_TOPIC_PREFIX": f"qualification/{PROJECT_NAME}",
    "MQTT_HOST": "mosquitto",
    "MQTT_PORT": "1883",
    "MQTT_USERNAME": "",
    "MQTT_PASSWORD": "",
    "PHOTO_UPLOAD_TOKEN": "",
    "TELEMETRY_UPLOAD_TOKEN": "",
    "GRAFANA_CLOUD_EXPORT_ENABLED": "false",
    "GRAFANA_CLOUD_REMOTE_WRITE_URL": "",
    "GRAFANA_CLOUD_INSTANCE_ID": "",
    "GRAFANA_CLOUD_API_TOKEN": "",
    "COMPOSE_PROFILES": "",
}
E2E_DATA_ROOT = Path(tempfile.gettempdir()) / PROJECT_NAME
COMPOSE_ENV.update(
    {
        "POSTGRES_DATA_DIR": (E2E_DATA_ROOT / "postgres").as_posix(),
        "GRAFANA_DATA_DIR": (E2E_DATA_ROOT / "grafana").as_posix(),
        "MOSQUITTO_DATA_DIR": (E2E_DATA_ROOT / "mosquitto").as_posix(),
        "PHOTO_DATA_DIR": (E2E_DATA_ROOT / "photos").as_posix(),
        "ESTIMATOR_PRIVATE_DATA_DIR": (E2E_DATA_ROOT / "estimator-private").as_posix(),
        "OLLAMA_DATA_DIR": (E2E_DATA_ROOT / "ollama").as_posix(),
        "E2E_GRAFANA_PROVISIONING_DIR": (E2E_DATA_ROOT / "grafana-provisioning").as_posix(),
    }
)

COMPOSE_SENSITIVE_ENV = {
    "APP_IMAGE",
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DATA_DIR",
    "PHOTO_DATA_DIR",
    "ESTIMATOR_PRIVATE_DATA_DIR",
    "MOSQUITTO_DATA_DIR",
    "GRAFANA_DATA_DIR",
    "OLLAMA_DATA_DIR",
    "LAN_BIND_ADDRESS",
    "POSTGRES_BIND_ADDRESS",
    "API_PUBLISHED_PORT",
    "MQTT_PUBLISHED_PORT",
    "POSTGRES_PUBLISHED_PORT",
    "GRAFANA_PUBLISHED_PORT",
    "OLLAMA_PUBLISHED_PORT",
    "COMPOSE_PROFILES",
    "COMPOSE_FILE",
    "COMPOSE_ENV_FILES",
    "COMPOSE_PROJECT_NAME",
    "GRAFANA_CLOUD_EXPORT_ENABLED",
    "GRAFANA_CLOUD_REMOTE_WRITE_URL",
    "GRAFANA_CLOUD_INSTANCE_ID",
    "GRAFANA_CLOUD_API_TOKEN",
    "GRAFANA_DB_USER",
    "GRAFANA_DB_PASSWORD",
    "E2E_GRAFANA_PROVISIONING_DIR",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "PHOTO_UPLOAD_TOKEN",
    "TELEMETRY_UPLOAD_TOKEN",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
}


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in COMPOSE_SENSITIVE_ENV:
        env.pop(key, None)
    env.update(COMPOSE_ENV)
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "-f",
            "docker-compose.e2e.yml",
            "-p",
            PROJECT_NAME,
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def wait_for_postgres() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = compose(
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            COMPOSE_ENV["POSTGRES_USER"],
            "-d",
            COMPOSE_ENV["POSTGRES_DB"],
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise AssertionError("postgres did not become ready")


def wait_for_api() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{BASE_URL}/ready", timeout=2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("api did not become ready")


def wait_for_grafana() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{GRAFANA_BASE_URL}/api/health", timeout=2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("grafana did not become ready")


def apply_grafana_reader_grants() -> None:
    compose("exec", "-T", "postgres", "sh", "/docker-entrypoint-initdb.d/20-grafana-reader.sh")


def grafana_reader_psql(sql: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        (
            f"postgresql://{COMPOSE_ENV['GRAFANA_DB_USER']}:{COMPOSE_ENV['GRAFANA_DB_PASSWORD']}"
            f"@localhost:5432/{COMPOSE_ENV['POSTGRES_DB']}"
        ),
        "-c",
        sql,
        check=check,
    )


def assert_disposable_data_root() -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = E2E_DATA_ROOT.resolve()
    assert resolved.parent == temp_root
    assert resolved.name == PROJECT_NAME
    assert resolved.name.startswith("senior-pomidor-server-e2e-")


def assert_local_docker_context() -> None:
    result = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    assert re.fullmatch(r"(?:npipe|unix)://.+", result.stdout.strip())


def assert_compose_isolation() -> None:
    config = json.loads(compose("--profile", "observability", "config", "--format", "json").stdout)
    for service in config["services"].values():
        for port in service.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1"

    assert "grafana-cloud-exporter" not in config["services"]
    all_profiles = json.loads(compose("--profile", "*", "config", "--format", "json").stdout)
    exporter = all_profiles["services"]["grafana-cloud-exporter"]["environment"]
    assert str(exporter["GRAFANA_CLOUD_EXPORT_ENABLED"]).lower() == "false"
    assert exporter["GRAFANA_CLOUD_REMOTE_WRITE_URL"] == ""
    assert exporter["GRAFANA_CLOUD_INSTANCE_ID"] == ""
    assert exporter["GRAFANA_CLOUD_API_TOKEN"] == ""

    expected_sources = {
        "postgres": COMPOSE_ENV["POSTGRES_DATA_DIR"],
        "grafana": COMPOSE_ENV["GRAFANA_DATA_DIR"],
        "mosquitto": COMPOSE_ENV["MOSQUITTO_DATA_DIR"],
        "api": COMPOSE_ENV["PHOTO_DATA_DIR"],
        "worker": COMPOSE_ENV["PHOTO_DATA_DIR"],
        "state-estimator-worker": COMPOSE_ENV["ESTIMATOR_PRIVATE_DATA_DIR"],
    }
    for service, source in expected_sources.items():
        assert any(
            volume["type"] == "bind" and volume["source"] == source for volume in config["services"][service]["volumes"]
        )


def emit_bounded_failure_evidence() -> None:
    for args in (("ps", "-a"), ("logs", "--tail", "200", "--no-color")):
        result = compose(*args, check=False)
        output = (result.stdout + result.stderr)[-40000:]
        print(f"docker-e2e {' '.join(args)} (bounded):\n{output}", file=sys.stderr)


def assert_no_existing_project_containers() -> None:
    result = compose("ps", "-a", "-q", check=False)
    assert result.returncode == 0, "Docker daemon is unavailable; existing project state cannot be verified"
    assert result.stdout.strip() == "", "refusing to delete data while task project containers still exist"


def cleanup_task_owned_stack() -> None:
    result = compose("--profile", "*", "down", "--remove-orphans", "--timeout", "30", check=False)
    if result.returncode != 0:
        emit_bounded_failure_evidence()
        raise AssertionError("Compose cleanup failed; preserving task-owned bind state for recovery")
    deadline = time.monotonic() + 30
    remaining = compose("ps", "-a", "-q", check=False)
    while remaining.returncode == 0 and remaining.stdout.strip() and time.monotonic() < deadline:
        time.sleep(1)
        remaining = compose("ps", "-a", "-q", check=False)
    if remaining.returncode != 0 or remaining.stdout.strip():
        emit_bounded_failure_evidence()
        raise AssertionError("Compose cleanup is unverified; preserving task-owned bind state for recovery")
    assert_disposable_data_root()
    permissions = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--mount",
            f"type=bind,source={E2E_DATA_ROOT},target=/task-state",
            "postgres:16-alpine",
            "chmod",
            "-R",
            "a+rwX",
            "/task-state",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if permissions.returncode != 0:
        raise AssertionError("Task-owned bind permissions could not be normalized; preserving state for recovery")
    shutil.rmtree(E2E_DATA_ROOT, ignore_errors=False)


def application_psql(sql: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        COMPOSE_ENV["POSTGRES_USER"],
        "-d",
        COMPOSE_ENV["POSTGRES_DB"],
        "-c",
        sql,
        check=check,
    )


def scalar_int(result: subprocess.CompletedProcess[str]) -> int:
    values = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
    assert len(values) == 1, result.stdout
    return int(values[0])


def wait_for_record_count(record_id: str, expected: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = grafana_reader_psql(f"SELECT count(*) FROM public.telemetry_events WHERE record_id = '{record_id}';")
        if scalar_int(result) == expected:
            return
        time.sleep(0.5)
    raise AssertionError(f"record {record_id} did not reach persisted count {expected}")


def wait_for_worker_outcome(record_id: str, outcome: str) -> None:
    expected = f"telemetry_ingest outcome={outcome} source=mqtt record_id={record_id}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = compose("logs", "--tail", "100", "--no-color", "worker", check=False)
        if expected in result.stdout + result.stderr:
            return
        time.sleep(0.5)
    raise AssertionError(f"worker did not log bounded {outcome} outcome for {record_id}")


def assert_grafana_reader_permissions() -> None:
    for table in READONLY_TABLES:
        result = grafana_reader_psql(f"SELECT count(*) FROM public.{table};")
        assert result.returncode == 0, result.stderr

    denied_statements = (
        """
        INSERT INTO public.devices (device_id, first_seen_at, last_seen_at, last_payload_at)
        VALUES ('readonly-denied', now(), now(), now());
        """,
        "UPDATE public.devices SET last_payload_at = now() WHERE device_id = 'pi-001';",
        "DELETE FROM public.devices WHERE device_id = 'pi-001';",
    )
    for statement in denied_statements:
        result = grafana_reader_psql(statement, check=False)
        assert result.returncode != 0
        assert "permission denied" in result.stderr.lower()


def alert_query_count(sql: str) -> int:
    bounded_sql = sql.strip().removesuffix(";")
    return scalar_int(grafana_reader_psql(f"SELECT count(*) FROM ({bounded_sql}) AS alert_rows;"))


def assert_grafana_provisioning() -> dict[str, str]:
    compose("--profile", "observability", "up", "-d", "grafana")
    wait_for_grafana()

    with httpx.Client(
        base_url=GRAFANA_BASE_URL,
        auth=(COMPOSE_ENV["GRAFANA_ADMIN_USER"], COMPOSE_ENV["GRAFANA_ADMIN_PASSWORD"]),
        timeout=10,
    ) as client:
        datasource = client.get("/api/datasources/uid/senior-pomidor-postgres")
        assert datasource.status_code == 200
        assert datasource.json()["name"] == "Senior Pomidor PostgreSQL"

        dashboard = client.get("/api/dashboards/uid/senior-pomidor-telemetry")
        assert dashboard.status_code == 200
        assert dashboard.json()["dashboard"]["title"] == "Senior Pomidor Telemetry"

        edge_dashboard = client.get("/api/dashboards/uid/senior-pomidor-edge-reliability")
        assert edge_dashboard.status_code == 200
        assert edge_dashboard.json()["dashboard"]["title"] == "Senior Pomidor Edge Reliability"

        alert_rules = client.get("/api/v1/provisioning/alert-rules")
        assert alert_rules.status_code == 200
        rules_by_title = {rule["title"]: rule for rule in alert_rules.json()}
        alert_titles = set(rules_by_title)
        assert {
            "Device telemetry stale",
            "Pod telemetry stale",
            "Pod sensor errors",
            "System health threshold crossed",
            "System health probe errors",
            "Critical dry soil",
            "VPD too low",
            "VPD condensation risk",
            "VPD high",
            "VPD stress",
            "VPD critical",
            "VPD emergency",
            "State VPD guardrail crossed",
            "State VPD critical",
            "State confidence low",
            "Active high or critical anomaly",
            "State snapshot stale",
            "Edge reliability unavailable or stale",
            "Edge watchdog critical",
            "Edge spool or disk critical",
            "Edge aggregate critical",
            "Edge application inactive",
        }.issubset(alert_titles)

        scheduler = client.get("/api/prometheus/grafana/api/v1/rules")
        assert scheduler.status_code == 200

    queries: dict[str, str] = {}
    for title in EDGE_ALERT_TITLES:
        rule = rules_by_title[title]
        query = next(item for item in rule["data"] if item["refId"] == "A")["model"]["rawSql"]
        assert isinstance(query, str)
        assert query.strip()
        queries[title] = query
    return queries


def edge_alert_scheduler_snapshot() -> dict[str, dict[str, str]]:
    response = httpx.get(
        f"{GRAFANA_BASE_URL}/api/prometheus/grafana/api/v1/rules",
        auth=(COMPOSE_ENV["GRAFANA_ADMIN_USER"], COMPOSE_ENV["GRAFANA_ADMIN_PASSWORD"]),
        timeout=10,
    )
    assert response.status_code == 200, response.text
    snapshots: dict[str, dict[str, str]] = {}
    for group in response.json().get("data", {}).get("groups", []):
        for rule in group.get("rules", []):
            title = rule.get("name") or rule.get("labels", {}).get("alertname")
            if title in EDGE_ALERT_TITLES:
                snapshots[title] = {
                    "state": str(rule.get("state", "")).lower(),
                    "health": str(rule.get("health", "")).lower(),
                    "last_evaluation": str(rule.get("lastEvaluation", "")),
                    "last_error": str(rule.get("lastError", rule.get("error", ""))),
                }
    return snapshots


def wait_for_edge_alert_states(
    firing: set[str],
    *,
    after: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + 150
    latest: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        latest = edge_alert_scheduler_snapshot()
        if set(latest) != set(EDGE_ALERT_TITLES):
            time.sleep(1)
            continue
        if any(
            not latest[title]["last_evaluation"] or latest[title]["last_evaluation"].startswith("0001-")
            for title in EDGE_ALERT_TITLES
        ):
            time.sleep(1)
            continue
        if after is not None and any(
            latest[title]["last_evaluation"] == after[title]["last_evaluation"] for title in EDGE_ALERT_TITLES
        ):
            time.sleep(1)
            continue
        expected = {title: ("firing" if title in firing else "inactive") for title in EDGE_ALERT_TITLES}
        states_match = all(
            latest[title]["health"] == "ok" and latest[title]["state"] == state for title, state in expected.items()
        )
        if states_match:
            return latest
        time.sleep(1)
    bounded = {title: latest.get(title, {}) for title in EDGE_ALERT_TITLES}
    raise AssertionError(f"Grafana evaluator states did not converge: {bounded}")


def compose_service_container_id(service: str) -> str:
    result = compose("ps", "-q", service)
    container_id = result.stdout.strip()
    assert container_id, f"{service} container id not found"
    return container_id


def assert_container_healthy(service: str) -> None:
    container_id = compose_service_container_id(service)
    deadline = time.monotonic() + 60
    health = None
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .State.Health}}", container_id],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        health = json.loads(result.stdout)
        if health["Status"] == "healthy":
            return
        time.sleep(1)
    assert health is not None
    assert health["Status"] == "healthy", f"{service} health was {health}"


def assert_migration_completed() -> None:
    result = compose("ps", "-a", "-q", "migrate")
    container_id = result.stdout.strip()
    assert container_id, "migrate container id not found"
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.ExitCode}}", container_id],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    assert inspect.stdout.strip() == "0"


def assert_mosquitto_bind_mount() -> None:
    result = compose("config", "--format", "json")
    config = json.loads(result.stdout)
    mosquitto_volumes = config["services"]["mosquitto"]["volumes"]
    assert any(
        volume["type"] == "bind"
        and volume["source"] == COMPOSE_ENV["MOSQUITTO_DATA_DIR"]
        and volume["target"] == "/mosquitto/data"
        for volume in mosquitto_volumes
    )


def healthy_reliability() -> dict:
    return {
        "watchdog": {
            "state": "healthy",
            "result": "healthy",
            "suppression": False,
            "configured": True,
            "attempt_count": 0,
            "restart_count": 0,
            "reboot_count": 0,
        },
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 0,
            "backlog_count": 0,
            "in_flight_count": 0,
            "dead_letter_count": 0,
            "disk_usage_percent": 25,
            "worker_state": "running",
        },
        "application": {
            "service_manager": "systemd",
            "process_running": True,
            "process_uptime_seconds": 3600,
            "systemd_available": True,
            "systemd_active_state": "active",
            "systemd_sub_state": "running",
            "systemd_service_active": True,
        },
        "aggregate": {
            "schema_version": "senior-pomidor.edge.health.v1",
            "state": "OK",
            "reasons": [],
        },
    }


def telemetry_payload(sequence: int = 0, *, health: dict | None = None) -> dict:
    observed = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5) + timedelta(seconds=sequence)
    return {
        "schema_version": TELEMETRY_SCHEMA_V2,
        "record_id": f"docker:pi-001:telemetry-{sequence}",
        "device_id": "pi-001",
        "timestamp_utc": observed.isoformat().replace("+00:00", "Z"),
        "pods": [
            {
                "pod_key": "pod-1",
                "soil_moisture_percent": 42.5,
                "soil_temperature_c": 20.0,
                "air_temperature_c": 24.0,
                "air_humidity_percent": 60.0,
            }
        ],
        "system_health": health if health is not None else healthy_reliability(),
    }


def publish_mqtt(payload: dict) -> None:
    result = compose(
        "exec",
        "-T",
        "mosquitto",
        "mosquitto_pub",
        "-h",
        "127.0.0.1",
        "-t",
        f"{COMPOSE_ENV['MQTT_TOPIC_PREFIX']}/{payload['device_id']}/telemetry",
        "-m",
        json.dumps(payload, separators=(",", ":")),
    )
    assert result.returncode == 0, result.stderr


def post_telemetry(client: httpx.Client, payload: dict) -> None:
    response = client.post("/api/v1/edge/telemetry", json=payload)
    assert response.status_code == 202, response.text
    assert response.json() == {"record_id": payload["record_id"], "status": "accepted"}


def assert_grafana_alert_transitions(
    client: httpx.Client,
    queries: dict[str, str],
    no_data_snapshot: dict[str, dict[str, str]],
) -> None:
    unavailable = "Edge reliability unavailable or stale"
    watchdog = "Edge watchdog critical"
    spool = "Edge spool or disk critical"
    aggregate = "Edge aggregate critical"
    application = "Edge application inactive"

    for query in queries.values():
        assert alert_query_count(query) == 0

    healthy_snapshot = wait_for_edge_alert_states(set(), after=no_data_snapshot)

    application_psql(
        "UPDATE telemetry_events SET timestamp_utc = now() - interval '21 minutes' "
        "WHERE id = (SELECT id FROM telemetry_events WHERE device_id = 'pi-001' "
        "ORDER BY timestamp_utc DESC, id DESC LIMIT 1);"
    )
    assert alert_query_count(queries[unavailable]) == 1
    stale_snapshot = wait_for_edge_alert_states({unavailable}, after=healthy_snapshot)
    post_telemetry(client, telemetry_payload(1))
    assert alert_query_count(queries[unavailable]) == 0
    recovered_snapshot = wait_for_edge_alert_states(set(), after=stale_snapshot)

    contradictory_process_only = healthy_reliability()
    contradictory_process_only["application"] = {
        "service_manager": "none",
        "process_running": True,
        "systemd_service_active": False,
    }
    post_telemetry(client, telemetry_payload(2, health=contradictory_process_only))
    assert alert_query_count(queries[application]) == 0
    contradictory_snapshot = wait_for_edge_alert_states(set(), after=recovered_snapshot)

    critical = healthy_reliability()
    critical["watchdog"].update({"state": "suppressed", "suppression": True})
    critical["spool"].update({"status": "DEGRADED", "disk_status": "CRITICAL"})
    critical["aggregate"]["state"] = "CRITICAL"
    critical["application"].update({"process_running": False, "systemd_service_active": False})
    post_telemetry(client, telemetry_payload(3, health=critical))
    assert alert_query_count(queries[watchdog]) == 1
    assert alert_query_count(queries[spool]) == 1
    assert alert_query_count(queries[aggregate]) == 1
    assert alert_query_count(queries[application]) == 1
    critical_snapshot = wait_for_edge_alert_states(
        {watchdog, spool, aggregate, application},
        after=contradictory_snapshot,
    )

    post_telemetry(client, telemetry_payload(4))
    assert alert_query_count(queries[watchdog]) == 0
    assert alert_query_count(queries[spool]) == 0
    assert alert_query_count(queries[aggregate]) == 0
    assert alert_query_count(queries[application]) == 0
    wait_for_edge_alert_states(set(), after=critical_snapshot)


def upload_photo(client: httpx.Client) -> httpx.Response:
    return client.post(
        "/api/v1/edge/photos",
        data={
            "photo_id": "docker-photo-1",
            "device_id": "pi-001",
            "captured_at_utc": "2026-06-07T12:00:00Z",
            "schema_version": PHOTO_SCHEMA,
            "sharpness_score": "0.91",
        },
        files={"photo": ("photo.jpg", b"\xff\xd8docker-jpeg\xff\xd9", "image/jpeg")},
    )


def test_docker_compose_stack_ingests_and_serves_data():
    assert_disposable_data_root()
    assert_local_docker_context()
    assert_compose_isolation()
    assert_no_existing_project_containers()
    shutil.rmtree(E2E_DATA_ROOT, ignore_errors=True)
    for key in (
        "POSTGRES_DATA_DIR",
        "GRAFANA_DATA_DIR",
        "MOSQUITTO_DATA_DIR",
        "PHOTO_DATA_DIR",
        "ESTIMATOR_PRIVATE_DATA_DIR",
        "OLLAMA_DATA_DIR",
    ):
        data_dir = Path(COMPOSE_ENV[key])
        data_dir.mkdir(parents=True, exist_ok=True)
        data_dir.chmod(0o777)
    provisioning_dir = Path(COMPOSE_ENV["E2E_GRAFANA_PROVISIONING_DIR"])
    shutil.copytree(ROOT / "docker/grafana/provisioning", provisioning_dir)
    edge_alerts_file = provisioning_dir / "alerting/edge-reliability-alerts.yml"
    source_alerts = edge_alerts_file.read_text(encoding="utf-8")
    assert source_alerts.count("    interval: 60s") == 1
    assert source_alerts.count("        for: 5m") == 2
    assert source_alerts.count("        for: 1m") == 3
    fast_alerts = source_alerts.replace("    interval: 60s", "    interval: 10s", 1)
    fast_alerts = fast_alerts.replace("        for: 5m", "        for: 0s")
    fast_alerts = fast_alerts.replace("        for: 1m", "        for: 0s")
    edge_alerts_file.write_text(fast_alerts, encoding="utf-8")
    try:
        compose("up", "-d", "--build")
        assert_migration_completed()
        apply_grafana_reader_grants()
        wait_for_postgres()
        wait_for_api()
        assert_container_healthy("postgres")
        assert_container_healthy("mosquitto")
        assert_container_healthy("api")
        assert_container_healthy("worker")
        assert_container_healthy("state-estimator-worker")
        assert_mosquitto_bind_mount()
        assert compose("ps", "-q", "grafana-cloud-exporter").stdout.strip() == ""

        alert_queries = assert_grafana_provisioning()
        for query in alert_queries.values():
            assert alert_query_count(query) == 0
        no_data_snapshot = wait_for_edge_alert_states(set())

        with httpx.Client(base_url=BASE_URL, timeout=10) as client:
            health = client.get("/health")
            assert health.status_code == 200
            ready = client.get("/ready")
            assert ready.status_code == 200

            first_payload = telemetry_payload()
            telemetry = client.post("/api/v1/edge/telemetry", json=first_payload)
            assert telemetry.status_code == 202
            assert telemetry.json() == {"record_id": first_payload["record_id"], "status": "accepted"}

            publish_mqtt(first_payload)
            wait_for_worker_outcome(first_payload["record_id"], "duplicate")

            duplicate = client.post("/api/v1/edge/telemetry", json=first_payload)
            assert duplicate.status_code == 202
            assert duplicate.json() == {"record_id": first_payload["record_id"], "status": "duplicate"}

            wait_for_record_count(first_payload["record_id"], 1)

            latest = client.get("/api/v1/devices/pi-001/latest")
            assert latest.status_code == 200
            assert latest.json()["record_id"] == first_payload["record_id"]
            assert latest.json()["system_health"]["watchdog"]["state"] == "healthy"

            history = client.get("/api/v1/devices/pi-001/telemetry?limit=100")
            assert history.status_code == 200
            assert [event["record_id"] for event in history.json()] == [first_payload["record_id"]]

            summary = client.get("/health/summary?node_id=pi-001")
            assert summary.status_code == 200
            assert summary.json()["components"]["edge_reliability"]["status"] == "OK"

            operator = client.get("/api/v1/operator/edges/pi-001/reliability")
            assert operator.status_code == 200
            assert operator.json()["schema_version"] == "senior-pomidor.operator.edge-reliability.v1"
            assert operator.json()["status"] == "OK"

            state = client.get("/api/v1/state/latest?node_id=pi-001")
            assert state.status_code == 200
            assert state.json()["schema_version"] == "state_v1"

            sensor_health = client.get("/api/v1/sensor-health/latest?node_id=pi-001")
            assert sensor_health.status_code == 200

            active_anomalies = client.get("/api/v1/anomalies/active?node_id=pi-001")
            assert active_anomalies.status_code == 200

            first_photo = upload_photo(client)
            assert first_photo.status_code == 202

            second_photo = upload_photo(client)
            assert second_photo.status_code == 200

            photos = client.get("/api/v1/devices/pi-001/photos")
            assert photos.status_code == 200
            assert len(photos.json()) == 1

            download = client.get("/api/v1/photos/docker-photo-1")
            assert download.status_code == 200
            assert download.headers["content-type"] == "image/jpeg"
            assert download.content == b"\xff\xd8docker-jpeg\xff\xd9"

            assert_grafana_alert_transitions(client, alert_queries, no_data_snapshot)

        assert_grafana_reader_permissions()
    except BaseException:
        emit_bounded_failure_evidence()
        raise
    finally:
        cleanup_task_owned_stack()
