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
BASE_URL = "http://127.0.0.1:8000"


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT_NAME, *args],
        cwd=ROOT,
        text=True,
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
        compose("run", "--rm", "api", "alembic", "upgrade", "head")
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
    finally:
        compose("down", "-v", "--remove-orphans", check=False)
