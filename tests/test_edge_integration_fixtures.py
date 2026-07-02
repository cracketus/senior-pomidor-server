import base64
import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import mqtt_worker
from app.config import Settings, get_settings
from app.db import get_db
from app.main import app
from app.models import Base

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "edge_integration"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def integration_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    def override_settings() -> Settings:
        return Settings(
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path / "photos"),
            photo_upload_token=None,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    monkeypatch.setattr(mqtt_worker, "SessionLocal", testing_session_local)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def mqtt_message(topic: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode("utf-8"))


def assert_fixture_visible(client: TestClient, payload: dict[str, Any], *, expected_source: str) -> None:
    device_id = payload["device_id"]

    latest = client.get(f"/api/v1/devices/{device_id}/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["device_id"] == device_id
    assert body["source"] == expected_source
    assert body["schema_version"] == payload["schema_version"]
    assert body["timestamp_utc"] == payload["timestamp_utc"]

    readings = {reading["pod_key"]: reading for reading in body["plant"]["readings"]}
    assert readings
    first_pod_key = next(iter(readings))
    assert "soil_moisture_percent" in readings[first_pod_key]["metrics"]

    errors = body["plant"]["errors"]
    assert errors
    assert all(error["pod_key"] and error["message"] for error in errors)

    system_health = body["system_health"]
    assert system_health["rpi_core"]["cpu_temp_c"] > 0
    assert "wifi_rssi_dbm" in system_health["rpi_core"]
    assert system_health["network"]["wifi_connected"] is True
    assert system_health["network"]["wifi_profile_count"] == 2
    assert body["health_alerts"]

    history = client.get(f"/api/v1/devices/{device_id}/telemetry?pod={first_pod_key}")
    assert history.status_code == 200
    assert len(history.json()) == 1


def test_mqtt_edge_fixture_is_visible_through_api(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_mqtt.json")

    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], fixture["payload"]))

    assert_fixture_visible(integration_client, fixture["payload"], expected_source="mqtt")


def test_http_fallback_edge_fixture_is_visible_through_api(integration_client: TestClient) -> None:
    payload = load_fixture("telemetry_mqtt.json")["payload"]

    response = integration_client.post("/api/v1/edge/telemetry", json=payload)

    assert response.status_code == 202
    assert_fixture_visible(integration_client, payload, expected_source="http")


def test_photo_fixture_metadata_and_download_are_visible_through_api(integration_client: TestClient) -> None:
    fixture = load_fixture("photo_http_request.json")
    file_fixture = fixture["file"]
    content = base64.b64decode(file_fixture["content_base64"])

    response = integration_client.post(
        "/api/v1/edge/photos",
        data=fixture["form"],
        files={
            file_fixture["field_name"]: (
                file_fixture["filename"],
                content,
                file_fixture["content_type"],
            )
        },
    )

    assert response.status_code == 202
    photo = response.json()["photo"]
    assert photo["device_id"] == fixture["form"]["device_id"]
    assert photo["photo_id"] == fixture["form"]["photo_id"]
    assert photo["file_size_bytes"] == len(content)

    photos = integration_client.get(f"/api/v1/devices/{fixture['form']['device_id']}/photos")
    assert photos.status_code == 200
    assert [item["photo_id"] for item in photos.json()] == [fixture["form"]["photo_id"]]

    recent = integration_client.get("/api/v1/photos/recent?limit=1")
    assert recent.status_code == 200
    assert recent.json()[0]["photo_id"] == fixture["form"]["photo_id"]

    download = integration_client.get(f"/api/v1/photos/{fixture['form']['photo_id']}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/jpeg"
    assert download.content == content
