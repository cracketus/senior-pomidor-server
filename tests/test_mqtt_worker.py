import json
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import mqtt_worker
from app.models import Base, TelemetryEvent
from app.validation import TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": "2026-06-07T12:00:00Z",
        "pods": [{"pod_key": "pod-1", "soil_moisture_percent": 42.5}],
    }


def telemetry_v2_payload() -> dict:
    payload = telemetry_payload()
    payload["schema_version"] = TELEMETRY_SCHEMA_V2
    payload["system_health"] = {
        "rpi_core": {"wifi_rssi_dbm": -82.0},
        "errors": [{"sensor": "rpi_wifi_rssi", "message": "weak signal"}],
    }
    return payload


def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def dispose_session_factory(testing_session_local) -> None:
    testing_session_local.kw["bind"].dispose()


def mqtt_message(topic: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode("utf-8"))


def test_mqtt_worker_accepts_valid_payload(monkeypatch):
    TestingSessionLocal = session_factory()
    try:
        monkeypatch.setattr(mqtt_worker, "SessionLocal", TestingSessionLocal)

        mqtt_worker.on_message(None, None, mqtt_message("senior-pomidor/pi-001/telemetry", telemetry_payload()))

        with TestingSessionLocal() as db:
            event = db.scalar(select(TelemetryEvent))
            assert event is not None
            assert event.device_id == "pi-001"
            assert event.source == "mqtt"
    finally:
        dispose_session_factory(TestingSessionLocal)


def test_mqtt_worker_accepts_v2_system_health(monkeypatch):
    TestingSessionLocal = session_factory()
    try:
        monkeypatch.setattr(mqtt_worker, "SessionLocal", TestingSessionLocal)

        mqtt_worker.on_message(None, None, mqtt_message("senior-pomidor/pi-001/telemetry", telemetry_v2_payload()))

        with TestingSessionLocal() as db:
            event = db.scalar(select(TelemetryEvent))
            assert event is not None
            assert event.schema_version == TELEMETRY_SCHEMA_V2
            assert event.system_health_jsonb["rpi_core"]["wifi_rssi_dbm"] == -82.0
    finally:
        dispose_session_factory(TestingSessionLocal)


def test_mqtt_worker_rejects_topic_device_mismatch(monkeypatch):
    TestingSessionLocal = session_factory()
    try:
        monkeypatch.setattr(mqtt_worker, "SessionLocal", TestingSessionLocal)

        mqtt_worker.on_message(None, None, mqtt_message("senior-pomidor/pi-002/telemetry", telemetry_payload()))

        with TestingSessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(TelemetryEvent))
            assert count == 0
    finally:
        dispose_session_factory(TestingSessionLocal)
