import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.health_summary import build_health_summary
from app.models import Base, SensorHealthSnapshot, TelemetryEvent
from app.readiness import ReadinessState


def ready_state() -> ReadinessState:
    return ReadinessState(
        ready=True,
        database="ok",
        migration="current",
        current_revision="head",
        head_revision="head",
    )


def test_health_summary_reports_server_health_and_bounded_worker_data(tmp_path, monkeypatch, client_factory):
    health_file = tmp_path / "worker-health.json"
    now = datetime.now(UTC)
    health_file.write_text(
        json.dumps({"status": "healthy", "updated_at": now.isoformat(), "topic": "private-topic"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.health_summary.check_readiness", lambda *_args: ready_state())
    client = client_factory(worker_health_file=str(health_file))

    response = client.get("/health/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "health_summary_v1"
    assert body["status"] == "OK"
    assert body["components"] == {
        "api": {"status": "OK"},
        "database": {"status": "OK", "migration": "current"},
        "worker": {"status": "OK", "age_seconds": body["components"]["worker"]["age_seconds"]},
        "telemetry": {"status": "OK", "scope": "server"},
        "sensor_health": {"status": "OK", "scope": "server"},
    }
    assert body["reasons"] == []
    assert body["data_freshness"] == {
        "worker_max_age_seconds": 90,
        "telemetry_max_age_seconds": 1200,
        "node_id": None,
    }


def test_health_summary_marks_missing_worker_unknown(tmp_path, monkeypatch, client_factory):
    monkeypatch.setattr("app.health_summary.check_readiness", lambda *_args: ready_state())
    client = client_factory(worker_health_file=str(tmp_path / "missing.json"))

    response = client.get("/health/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNKNOWN"
    assert body["components"]["worker"]["status"] == "UNKNOWN"
    assert body["reasons"] == [{"code": "worker_health_missing", "message": "worker health is unavailable"}]


def test_health_summary_marks_missing_node_data_unknown(tmp_path, monkeypatch, client_factory):
    health_file = tmp_path / "worker-health.json"
    fresh_worker_time = datetime.now(UTC) - timedelta(seconds=1)
    health_file.write_text(
        json.dumps({"status": "healthy", "updated_at": fresh_worker_time.isoformat()}), encoding="utf-8"
    )
    monkeypatch.setattr("app.health_summary.check_readiness", lambda *_args: ready_state())
    client = client_factory(worker_health_file=str(health_file))

    response = client.get("/health/summary?node_id=pi-001")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNKNOWN"
    assert body["components"]["telemetry"]["status"] == "UNKNOWN"
    assert body["components"]["sensor_health"]["status"] == "UNKNOWN"


def test_build_health_summary_marks_stale_node_inputs(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db_session = Session(engine)
    now = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    old = now - timedelta(minutes=21)
    db_session.add(
        TelemetryEvent(
            device_id="pi-001",
            timestamp_utc=old,
            schema_version="senior-pomidor.edge.telemetry.v2",
            source="http",
            raw_payload_jsonb={},
            system_health_jsonb=None,
            received_at=old,
        )
    )
    db_session.add(
        SensorHealthSnapshot(
            health_id="health-1",
            node_id="pi-001",
            ts=old,
            payload_jsonb={},
        )
    )
    db_session.commit()
    health_file = tmp_path / "worker-health.json"
    health_file.write_text(json.dumps({"status": "healthy", "updated_at": now.isoformat()}), encoding="utf-8")
    monkeypatch.setattr("app.health_summary.check_readiness", lambda *_args: ready_state())

    summary = build_health_summary(
        db_session,
        worker_health_file=str(health_file),
        now=now,
        node_id="pi-001",
        readiness_engine=None,
    )

    assert summary["status"] == "WARN"
    assert summary["components"]["telemetry"]["reason_code"] == "telemetry_stale"
    assert summary["components"]["sensor_health"]["reason_code"] == "sensor_health_stale"
    db_session.close()
    engine.dispose()
