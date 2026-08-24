import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.health_summary import _bounded_unique_reasons, build_health_summary
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


def healthy_reliability() -> dict:
    return {
        "watchdog": {"state": "healthy", "result": "healthy", "suppression": False, "configured": True},
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 0,
            "backlog_count": 0,
            "in_flight_count": 0,
            "worker_state": "running",
        },
        "application": {
            "process_running": True,
            "systemd_available": True,
            "systemd_service_active": True,
            "systemd_active_state": "active",
        },
    }


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
    assert body["components"]["edge_reliability"] == {
        "status": "UNKNOWN",
        "reason_codes": ["edge_reliability_telemetry_missing"],
        "watchdog": {"status": "UNKNOWN"},
        "spool": {"status": "UNKNOWN"},
        "application": {"status": "UNKNOWN"},
    }


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
    assert summary["components"]["edge_reliability"]["status"] == "UNKNOWN"
    assert summary["components"]["edge_reliability"]["reason_codes"] == ["edge_reliability_telemetry_stale"]
    db_session.close()
    engine.dispose()


def test_build_health_summary_reports_healthy_edge_reliability(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    with Session(engine) as db_session:
        db_session.add(
            TelemetryEvent(
                device_id="pi-001",
                timestamp_utc=now - timedelta(seconds=12),
                schema_version="senior-pomidor.edge.telemetry.v2",
                source="http",
                raw_payload_jsonb={},
                system_health_jsonb=healthy_reliability(),
                received_at=now,
            )
        )
        db_session.add(SensorHealthSnapshot(health_id="health-1", node_id="pi-001", ts=now, payload_jsonb={}))
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

    assert summary["components"]["edge_reliability"] == {
        "status": "OK",
        "age_seconds": 12.0,
        "reason_codes": [],
        "watchdog": {
            "status": "OK",
            "state": "healthy",
            "result": "healthy",
            "suppression": False,
            "configured": True,
        },
        "spool": {"status": "OK", "reported_status": "OK", "disk_status": "OK"},
        "application": {
            "status": "OK",
            "process_running": True,
            "systemd_available": True,
            "systemd_service_active": True,
        },
    }
    engine.dispose()


def test_build_health_summary_legacy_reliability_is_unknown(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    with Session(engine) as db_session:
        db_session.add(
            TelemetryEvent(
                device_id="pi-001",
                timestamp_utc=now,
                schema_version="senior-pomidor.edge.telemetry.v2",
                source="http",
                raw_payload_jsonb={},
                system_health_jsonb={"rpi_core": {"cpu_temp_c": 45.0}},
                received_at=now,
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

    assert summary["components"]["telemetry"]["status"] == "OK"
    assert summary["components"]["edge_reliability"]["status"] == "UNKNOWN"
    assert summary["components"]["edge_reliability"]["reason_codes"] == [
        "edge_watchdog_missing",
        "edge_spool_missing",
        "edge_application_missing",
    ]
    engine.dispose()


def test_health_summary_marks_reliability_unavailable_on_database_failure(tmp_path, monkeypatch) -> None:
    class FailingSession:
        def scalar(self, *_args, **_kwargs):
            raise SQLAlchemyError("database unavailable")

    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    health_file = tmp_path / "worker-health.json"
    health_file.write_text(json.dumps({"status": "healthy", "updated_at": now.isoformat()}), encoding="utf-8")
    monkeypatch.setattr("app.health_summary.check_readiness", lambda *_args: ready_state())

    summary = build_health_summary(
        FailingSession(),
        worker_health_file=str(health_file),
        now=now,
        node_id="pi-001",
        readiness_engine=None,
    )

    assert summary["components"]["edge_reliability"]["reason_codes"] == ["edge_reliability_telemetry_unavailable"]


def test_summary_reasons_are_deduplicated_ordered_and_bounded() -> None:
    reasons = [{"code": f"reason_{index}", "message": f"message {index}"} for index in range(25)] + [
        {"code": "reason_0", "message": "duplicate"}
    ]

    bounded = _bounded_unique_reasons(reasons)

    assert len(bounded) == 20
    assert [reason["code"] for reason in bounded] == [f"reason_{index}" for index in range(20)]
