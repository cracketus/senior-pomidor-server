import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCKER_E2E") != "1",
    reason="set RUN_DOCKER_E2E=1 to run Docker Compose end-to-end tests",
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "senior-pomidor-server-e2e"
BASE_URL = "http://127.0.0.1:18080"
GRAFANA_BASE_URL = "http://127.0.0.1:13000"
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
    "API_PUBLISHED_PORT": "18080",
    "GRAFANA_PUBLISHED_PORT": "13000",
    "POSTGRES_PUBLISHED_PORT": "15432",
    "MQTT_PUBLISHED_PORT": "11883",
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
    }
)


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(COMPOSE_ENV)
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
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
            "senior_pomidor",
            "-d",
            "senior_pomidor",
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
        "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor",
        "-c",
        sql,
        check=check,
    )


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


def assert_grafana_provisioning() -> None:
    compose("--profile", "observability", "up", "-d", "grafana")
    wait_for_grafana()

    with httpx.Client(base_url=GRAFANA_BASE_URL, auth=("admin", "admin"), timeout=10) as client:
        datasource = client.get("/api/datasources/uid/senior-pomidor-postgres")
        assert datasource.status_code == 200
        assert datasource.json()["name"] == "Senior Pomidor PostgreSQL"

        dashboard = client.get("/api/dashboards/uid/senior-pomidor-telemetry")
        assert dashboard.status_code == 200
        assert dashboard.json()["dashboard"]["title"] == "Senior Pomidor Telemetry"

        alert_rules = client.get("/api/v1/provisioning/alert-rules")
        assert alert_rules.status_code == 200
        alert_titles = {rule["title"] for rule in alert_rules.json()}
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
        }.issubset(alert_titles)


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


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": "2026-06-07T12:00:00Z",
        "pods": [
            {
                "pod_key": "pod-1",
                "soil_moisture_percent": 42.5,
                "soil_temperature_c": 20.0,
                "air_temperature_c": 24.0,
                "air_humidity_percent": 60.0,
            }
        ],
    }


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

        with httpx.Client(base_url=BASE_URL, timeout=10) as client:
            health = client.get("/health")
            assert health.status_code == 200

            telemetry = client.post("/api/v1/edge/telemetry", json=telemetry_payload())
            assert telemetry.status_code == 202

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

        assert_grafana_reader_permissions()
        assert_grafana_provisioning()
    finally:
        compose("down", "-v", "--remove-orphans", check=False)
        shutil.rmtree(E2E_DATA_ROOT, ignore_errors=True)
