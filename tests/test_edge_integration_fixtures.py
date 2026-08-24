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


def assert_reliability_visible(client: TestClient, payload: dict[str, Any], *, expected_source: str) -> None:
    response = client.get(f"/api/v1/devices/{payload['device_id']}/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == expected_source
    health = body["system_health"]
    source_health = payload["system_health"]
    assert health["watchdog"] == {
        key: value for key, value in source_health["watchdog"].items() if key != "unknown_watchdog_field"
    }
    assert health["spool"] == {
        key: value
        for key, value in source_health["spool"].items()
        if key not in {"last_error_detail", "worker_last_error", "unknown_spool_field"}
    }
    assert health["application"] == {
        key: value
        for key, value in source_health["application"].items()
        if key not in {"errors", "unknown_application_field"}
    }
    serialized = json.dumps(health)
    for forbidden in (
        "last_error_detail",
        "worker_last_error",
        "synthetic nested error",
        "unknown_watchdog_field",
        "unknown_spool_field",
        "unknown_application_field",
    ):
        assert forbidden not in serialized

    history = client.get(f"/api/v1/devices/{payload['device_id']}/telemetry")
    assert history.status_code == 200
    assert history.json() == [body]


def test_mqtt_edge_fixture_is_visible_through_api(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_mqtt.json")

    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], fixture["payload"]))

    assert_fixture_visible(integration_client, fixture["payload"], expected_source="mqtt")


def test_http_fallback_edge_fixture_is_visible_through_api(integration_client: TestClient) -> None:
    payload = load_fixture("telemetry_mqtt.json")["payload"]

    response = integration_client.post("/api/v1/edge/telemetry", json=payload)

    assert response.status_code == 202
    assert response.json() == {"record_id": payload["record_id"], "status": "accepted"}
    assert_fixture_visible(integration_client, payload, expected_source="http")


def test_mqtt_then_http_is_duplicate_by_shared_record_id(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_mqtt.json")
    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], fixture["payload"]))

    response = integration_client.post("/api/v1/edge/telemetry", json=fixture["payload"])

    assert response.status_code == 202
    assert response.json() == {"record_id": fixture["payload"]["record_id"], "status": "duplicate"}
    assert_fixture_visible(integration_client, fixture["payload"], expected_source="mqtt")


def test_http_then_mqtt_creates_no_second_row(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_mqtt.json")
    response = integration_client.post("/api/v1/edge/telemetry", json=fixture["payload"])
    assert response.json()["status"] == "accepted"

    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], fixture["payload"]))

    assert_fixture_visible(integration_client, fixture["payload"], expected_source="http")


def test_reliability_fixture_passes_mqtt_persistence_and_read_path(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_reliability.json")

    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], fixture["payload"]))

    assert_reliability_visible(integration_client, fixture["payload"], expected_source="mqtt")


def test_reliability_fixture_cross_transport_replay_is_duplicate(integration_client: TestClient) -> None:
    fixture = load_fixture("telemetry_reliability.json")
    payload = fixture["payload"]
    accepted = integration_client.post("/api/v1/edge/telemetry", json=payload)

    mqtt_worker.on_message(None, None, mqtt_message(fixture["topic"], payload))
    duplicate = integration_client.post("/api/v1/edge/telemetry", json=payload)

    assert accepted.status_code == 202
    assert accepted.json() == {"record_id": payload["record_id"], "status": "accepted"}
    assert duplicate.status_code == 202
    assert duplicate.json() == {"record_id": payload["record_id"], "status": "duplicate"}
    assert_reliability_visible(integration_client, payload, expected_source="http")


def test_mixed_500_record_backlog_and_replays(integration_client: TestClient) -> None:
    payloads = [
        {
            "schema_version": "senior-pomidor.edge.telemetry.v2",
            "record_id": f"backlog:balcony-edge-01:{index:04d}",
            "device_id": "balcony-edge-01",
            "timestamp_utc": f"2026-08-{1 + index // 24:02d}T{index % 24:02d}:00:00Z",
            "pods": {"pod_1": {"enabled": True, "metrics": {"soil_moisture_percent": float(index % 101)}}},
        }
        for index in range(500)
    ]

    for payload in payloads:
        response = integration_client.post("/api/v1/edge/telemetry", json=payload)
        assert response.json()["status"] == "accepted"
    for payload in payloads[::50]:
        response = integration_client.post("/api/v1/edge/telemetry", json=payload)
        assert response.json()["status"] == "duplicate"

    history = integration_client.get("/api/v1/devices/balcony-edge-01/telemetry?limit=1000")
    assert history.status_code == 200
    assert len(history.json()) == 500


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
