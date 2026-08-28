import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import mqtt_worker
from app.environment_boundary import DeploymentMode, validate_environment_device
from app.validation import ValidationError

ROOT = Path(__file__).resolve().parents[1]
STAGING_COMPOSE = (ROOT / "docker-compose.staging.yml").read_text(encoding="utf-8")
BASE_COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
STAGING_ENV = (ROOT / "deploy/senior-pomidor-staging.env.example").read_text(encoding="utf-8")
PRODUCTION_ENV = (ROOT / "deploy/senior-pomidor.env.example").read_text(encoding="utf-8")


def telemetry_payload(device_id: str) -> dict[str, Any]:
    payload = json.loads((ROOT / "tests/fixtures/contracts/telemetry_v2.json").read_text(encoding="utf-8"))
    payload["device_id"] = device_id
    payload["record_id"] = f"spool:{device_id}:20260702T120000Z"
    return payload


def test_environment_identity_boundary_is_fail_closed() -> None:
    assert (
        validate_environment_device(
            "edge-staging-balcony-01",
            deployment_mode="staging",
            staging_device_prefix="edge-staging-",
        )
        == "edge-staging-balcony-01"
    )
    assert (
        validate_environment_device(
            "balcony-01",
            deployment_mode="production",
            staging_device_prefix="edge-staging-",
        )
        == "balcony-01"
    )
    invalid_pairs: tuple[tuple[str, DeploymentMode], ...] = (
        ("balcony-01", "staging"),
        ("edge-staging-balcony-01", "production"),
    )
    for device_id, mode in invalid_pairs:
        with pytest.raises(ValidationError):
            validate_environment_device(
                device_id,
                deployment_mode=mode,
                staging_device_prefix="edge-staging-",
            )


def test_development_and_rehearsal_preserve_fixture_compatibility() -> None:
    modes: tuple[DeploymentMode, ...] = ("development", "rehearsal")
    for mode in modes:
        assert validate_environment_device(
            "pi-001",
            deployment_mode=mode,
            staging_device_prefix="edge-staging-",
        )
        assert validate_environment_device(
            "edge-staging-pi-001",
            deployment_mode=mode,
            staging_device_prefix="edge-staging-",
        )


def test_staging_http_ingress_rejects_non_staging_identity_before_persistence(
    client_factory: Callable[..., TestClient],
) -> None:
    client = client_factory(deployment_mode="staging")
    rejected = client.post("/api/v1/edge/telemetry", json=telemetry_payload("pi-001"))
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get("/api/v1/devices").json() == []

    accepted = client.post("/api/v1/edge/telemetry", json=telemetry_payload("edge-staging-pi-001"))
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "accepted"


def test_production_http_ingress_rejects_reserved_staging_identity(
    client_factory: Callable[..., TestClient],
) -> None:
    client = client_factory(deployment_mode="production")
    rejected = client.post(
        "/api/v1/edge/telemetry",
        json=telemetry_payload("edge-staging-pi-001"),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get("/api/v1/devices").json() == []


def test_staging_photo_ingress_uses_the_same_identity_boundary(
    client_factory: Callable[..., TestClient],
) -> None:
    client = client_factory(deployment_mode="staging")
    response = client.post(
        "/api/v1/edge/photos",
        data={
            "photo_id": "photo-001",
            "device_id": "pi-001",
            "captured_at_utc": "2026-07-02T12:00:00Z",
            "schema_version": "senior-pomidor.edge.photo.v1",
        },
        files={"photo": ("photo.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "device is outside the staging identity boundary"}


def test_staging_mqtt_ingress_rejects_non_staging_identity_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = telemetry_payload("pi-001")
    message: Any = SimpleNamespace(
        payload=json.dumps(payload).encode(),
        topic=f"{mqtt_worker.settings.mqtt_topic_prefix}/pi-001/telemetry",
    )
    monkeypatch.setattr(mqtt_worker.settings, "deployment_mode", "staging")

    def unexpected_database_access() -> None:
        raise AssertionError("rejected staging identity reached the database")

    monkeypatch.setattr(mqtt_worker, "SessionLocal", unexpected_database_access)
    mqtt_worker.on_message(SimpleNamespace(), SimpleNamespace(), message)


def test_staging_compose_is_explicitly_isolated_and_export_disabled() -> None:
    required = (
        "DEPLOYMENT_MODE: staging",
        "senior-pomidor.environment: staging",
        'senior-pomidor.external-export: "disabled"',
        "STAGING_DATABASE_URL:?",
        "STAGING_MQTT_TOPIC_PREFIX:?",
        'GRAFANA_CLOUD_EXPORT_ENABLED: "false"',
        'GRAFANA_CLOUD_REMOTE_WRITE_URL: ""',
        '"127.0.0.1:${STAGING_API_PUBLISHED_PORT:?',
        '"127.0.0.1:${STAGING_MQTT_PUBLISHED_PORT:?',
        "STAGING_POSTGRES_DATA_DIR:?",
        "STAGING_MOSQUITTO_DATA_DIR:?",
        "STAGING_GRAFANA_DATA_DIR:?",
    )
    for marker in required:
        assert marker in STAGING_COMPOSE
    assert "external: true" not in STAGING_COMPOSE
    assert STAGING_COMPOSE.count("ports: !override") == 2
    assert "cloud-export" not in STAGING_ENV
    assert "./data/staging/" in STAGING_ENV
    assert "STAGING_MOSQUITTO_PASSWORD_FILE" in STAGING_ENV
    assert "STAGING_MOSQUITTO_ACL_FILE" in STAGING_ENV
    assert "STAGING_INTEROP_NETWORK=senior-pomidor-staging-interop" in STAGING_ENV
    assert "senior-pomidor-staging/#" in (ROOT / "deploy/staging/mosquitto.acl.example").read_text(encoding="utf-8")


def test_production_and_staging_modes_are_explicit_without_api_contract_change() -> None:
    assert "DEPLOYMENT_MODE: ${DEPLOYMENT_MODE:-development}" in BASE_COMPOSE
    assert "DEPLOYMENT_MODE=production" in PRODUCTION_ENV
    assert "DEPLOYMENT_MODE=staging" in STAGING_ENV
