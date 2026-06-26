import os
import subprocess
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
)
COMPOSE_ENV = {
    "API_PUBLISHED_PORT": "18080",
    "GRAFANA_PUBLISHED_PORT": "13000",
    "POSTGRES_PUBLISHED_PORT": "15432",
    "MQTT_PUBLISHED_PORT": "11883",
}


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(COMPOSE_ENV)
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT_NAME, *args],
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
            response = httpx.get(f"{BASE_URL}/health", timeout=2)
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
        }.issubset(alert_titles)


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": "2026-06-07T12:00:00Z",
        "pods": [{"pod_key": "pod-1", "soil_moisture_percent": 42.5}],
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
    try:
        compose("up", "-d", "--build", "postgres", "mosquitto")
        wait_for_postgres()
        compose("build", "api")
        compose("run", "--rm", "api", "alembic", "upgrade", "head")
        apply_grafana_reader_grants()
        compose("up", "-d", "--build", "api", "worker")
        wait_for_api()

        with httpx.Client(base_url=BASE_URL, timeout=10) as client:
            telemetry = client.post("/api/v1/edge/telemetry", json=telemetry_payload())
            assert telemetry.status_code == 202

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
