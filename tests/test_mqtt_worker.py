import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import mqtt_worker
from app.config import settings
from app.models import Base, TelemetryEvent
from app.validation import TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2
from app.worker_healthcheck import is_worker_healthy


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
        "network": {
            "wifi_connected": True,
            "wifi_profile_count": 2,
            "internet_reachable": True,
            "dns_resolution_ok": True,
            "last_recovery_result": "not_needed",
            "last_recovery_exit_code": 0,
        },
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
            assert event.system_health_jsonb["network"]["wifi_connected"] is True
            assert event.system_health_jsonb["network"]["wifi_profile_count"] == 2
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


def test_mqtt_worker_retries_initial_connect_failure():
    class FakeClient:
        def __init__(self) -> None:
            self.attempts = 0

        def connect(self, host, port, keepalive):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("broker unavailable")

    class FakeStop:
        def __init__(self) -> None:
            self.waits: list[float] = []

        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> None:
            self.waits.append(delay)

    client = FakeClient()
    stop = FakeStop()

    assert mqtt_worker.connect_with_retry(client, stop, initial_delay_seconds=0.25) is True
    assert client.attempts == 2
    assert stop.waits == [0.25]


def test_mqtt_worker_marks_connect_failure(monkeypatch, tmp_path):
    health_file = tmp_path / "worker-health.json"
    monkeypatch.setattr(settings, "worker_health_file", str(health_file))

    mqtt_worker.on_connect(SimpleNamespace(), None, None, 5)

    body = json.loads(health_file.read_text(encoding="utf-8"))
    assert body["status"] == "connect_failed"
    assert is_worker_healthy() is False


def test_mqtt_worker_marks_successful_subscribe(monkeypatch, tmp_path):
    health_file = tmp_path / "worker-health.json"
    monkeypatch.setattr(settings, "worker_health_file", str(health_file))

    class FakeClient:
        def subscribe(self, topic, qos):
            self.topic = topic
            self.qos = qos
            return mqtt_worker.mqtt.MQTT_ERR_SUCCESS, 42

    client = FakeClient()
    mqtt_worker.on_connect(client, None, None, 0)

    body = json.loads(health_file.read_text(encoding="utf-8"))
    assert body["status"] == "healthy"
    assert body["topic"] == "senior-pomidor/+/telemetry"
    assert client.qos == 1
    assert is_worker_healthy() is True


def test_worker_healthcheck_rejects_stale_or_stopped_status(monkeypatch, tmp_path):
    health_file = tmp_path / "worker-health.json"
    monkeypatch.setattr(settings, "worker_health_file", str(health_file))
    health_file.write_text(
        json.dumps(
            {
                "status": "healthy",
                "updated_at": (datetime.now(UTC) - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    assert is_worker_healthy() is False

    health_file.write_text(
        json.dumps({"status": "stopped", "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}),
        encoding="utf-8",
    )
    assert is_worker_healthy() is False
