import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_db
from app.main import app
from app.models import TelemetryEvent
from app.operator_edge_reliability import build_operator_edge_reliability
from app.telemetry import normalize_system_health

NOW = datetime(2026, 8, 24, 12, 0, 12, tzinfo=UTC)


def healthy_system_health() -> dict:
    return {
        "watchdog": {
            "state": "healthy",
            "result": "healthy",
            "suppression": False,
            "configured": True,
            "attempt_count": 0,
            "restart_count": 0,
            "reboot_count": 0,
            "last_healthy_heartbeat_at_utc": "2026-08-24T12:00:00Z",
        },
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 0,
            "backlog_count": 0,
            "in_flight_count": 0,
            "dead_letter_count": 0,
            "oldest_pending_age_seconds": None,
            "outage_duration_seconds": None,
            "disk_usage_percent": 25,
            "last_delivery_result": "accepted",
            "last_successful_delivery_at_utc": "2026-08-24T12:00:00Z",
            "last_error_code": None,
            "worker_state": "running",
            "worker_last_heartbeat_at_utc": "2026-08-24T12:00:00Z",
        },
        "application": {
            "process_running": True,
            "process_uptime_seconds": 3600,
            "systemd_available": True,
            "systemd_active_state": "active",
            "systemd_sub_state": "running",
            "systemd_service_active": True,
        },
    }


def event(
    *, observed_at: datetime | object | None = None, health: object | None = None, event_id: int = 1
) -> TelemetryEvent:
    return TelemetryEvent(
        id=event_id,
        record_id="spool:pi-001:test",
        device_id="pi-001",
        timestamp_utc=observed_at if observed_at is not None else NOW - timedelta(seconds=12),
        schema_version="senior-pomidor.edge.telemetry.v2",
        source="http",
        raw_payload_jsonb={"private": "must-not-project"},
        system_health_jsonb=healthy_system_health() if health is None else health,
        received_at=NOW - timedelta(seconds=11),
    )


def dumped(model) -> dict:
    return model.model_dump(mode="json")


def test_builder_projects_healthy_reliability_with_all_optional_keys() -> None:
    result = dumped(build_operator_edge_reliability(event(), now=NOW))

    assert result["status"] == "OK"
    assert result["freshness"] == {"status": "FRESH", "age_seconds": 12, "max_age_seconds": 1200}
    assert result["reasons"] == []
    assert result["watchdog"]["status"] == "OK"
    assert result["spool"]["oldest_pending_age_seconds"] is None
    assert result["application"]["status"] == "OK"


@pytest.mark.parametrize(
    ("mutation", "expected_status", "expected_code"),
    [
        (("watchdog", "state", "recovering"), "WARN", "edge_watchdog_recovering"),
        (("watchdog", "suppression", True), "ALERT", "edge_watchdog_suppressed"),
        (("spool", "pending_count", 3), "WARN", "edge_spool_backlog"),
        (("spool", "status", "DEGRADED"), "ALERT", "edge_spool_degraded"),
        (("application", "process_running", False), "ALERT", "edge_application_process_stopped"),
    ],
)
def test_builder_uses_evaluator_status_and_reason_mappings(mutation, expected_status, expected_code) -> None:
    health = healthy_system_health()
    block, field, value = mutation
    health[block][field] = value

    result = dumped(build_operator_edge_reliability(event(health=health), now=NOW))

    assert result["status"] == expected_status
    assert expected_code in [reason["code"] for reason in result["reasons"]]


def test_builder_preserves_evaluator_order_for_simultaneous_findings() -> None:
    health = healthy_system_health()
    health["watchdog"].update({"state": "recovering", "result": "restart_failed"})
    health["spool"].update({"status": "BACKLOG", "disk_status": "WARNING"})
    health["application"]["process_running"] = False

    result = dumped(build_operator_edge_reliability(event(health=health), now=NOW))

    assert [reason["code"] for reason in result["reasons"]] == [
        "edge_watchdog_restart_failed",
        "edge_watchdog_restart_recovery",
        "edge_spool_backlog",
        "edge_spool_disk_warning",
        "edge_application_process_stopped",
    ]


def test_builder_keeps_available_blocks_when_other_blocks_are_missing() -> None:
    health = {"spool": healthy_system_health()["spool"]}

    result = dumped(build_operator_edge_reliability(event(health=health), now=NOW))

    assert result["status"] == "UNKNOWN"
    assert result["watchdog"]["status"] == "UNKNOWN"
    assert result["watchdog"]["state"] is None
    assert result["spool"]["status"] == "OK"
    assert result["spool"]["reported_status"] == "OK"
    assert result["application"]["status"] == "UNKNOWN"
    assert [reason["code"] for reason in result["reasons"]] == [
        "edge_watchdog_missing",
        "edge_application_missing",
    ]


@pytest.mark.parametrize(("age", "expected"), [(0, "FRESH"), (1200, "FRESH"), (1200.001, "STALE")])
def test_freshness_exact_boundaries(age: float, expected: str) -> None:
    result = dumped(build_operator_edge_reliability(event(observed_at=NOW - timedelta(seconds=age)), now=NOW))

    assert result["freshness"]["status"] == expected
    assert result["freshness"]["age_seconds"] == age


def test_stale_projection_keeps_values_but_only_unknown_statuses() -> None:
    result = dumped(build_operator_edge_reliability(event(observed_at=NOW - timedelta(seconds=1200.001)), now=NOW))

    assert result["status"] == "UNKNOWN"
    assert result["reasons"] == [
        {
            "code": "edge_reliability_telemetry_stale",
            "status": "UNKNOWN",
            "message": "Edge reliability telemetry is stale",
        }
    ]
    assert result["watchdog"]["state"] == "healthy"
    assert {result[name]["status"] for name in ("watchdog", "spool", "application")} == {"UNKNOWN"}


@pytest.mark.parametrize("observed_at", [NOW + timedelta(milliseconds=1), "invalid"])
def test_future_or_invalid_timestamp_hides_reliability_details(observed_at: object) -> None:
    result = dumped(build_operator_edge_reliability(event(observed_at=observed_at), now=NOW))

    assert result["freshness"] == {"status": "UNKNOWN", "age_seconds": None, "max_age_seconds": 1200}
    assert result["status"] == "UNKNOWN"
    assert result["reasons"][0]["code"] == "edge_reliability_telemetry_unavailable"
    assert result["watchdog"]["state"] is None
    assert result["spool"]["pending_count"] is None
    assert result["application"]["process_running"] is None


def test_projection_excludes_private_and_unrestricted_fields() -> None:
    health = healthy_system_health()
    health["watchdog"].update({"reason": "private reason", "boot_id": "private-boot"})
    health["spool"].update({"last_error_detail": "private detail", "database_path": "/private/path"})
    health["application"].update(
        {"process_id": 42, "systemd_main_pid": 42, "systemd_service_name": "private-service", "errors": {}}
    )

    serialized = build_operator_edge_reliability(event(health=health), now=NOW).model_dump_json()

    for forbidden in (
        "raw_payload",
        "private reason",
        "private-boot",
        "private detail",
        "/private/path",
        "private-service",
        "process_id",
        "systemd_main_pid",
        '"errors"',
    ):
        assert forbidden not in serialized


def test_copied_edge_fixture_replays_bounded_counters_timestamps_and_percent() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "edge_integration" / "telemetry_reliability.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))["payload"]
    normalized_health = normalize_system_health(payload)

    result = dumped(build_operator_edge_reliability(event(health=normalized_health), now=NOW))

    assert result["watchdog"]["attempt_count"] == 1
    assert result["watchdog"]["restart_count"] == 1
    assert result["watchdog"]["reboot_count"] == 0
    assert result["watchdog"]["last_healthy_heartbeat_at_utc"].endswith("Z")
    assert result["spool"]["pending_count"] == 3
    assert result["spool"]["backlog_count"] == 4
    assert result["spool"]["dead_letter_count"] == 1
    assert result["spool"]["disk_usage_percent"] == pytest.approx(27.5)
    assert 0 <= result["spool"]["disk_usage_percent"] <= 100
    assert result["spool"]["worker_last_heartbeat_at_utc"].endswith("Z")


def test_operator_projection_accepts_docker_process_only_payload() -> None:
    health = {
        "watchdog": {"state": "healthy", "configured": True},
        "spool": {"status": "OK", "disk_status": "OK", "pending_count": 0, "backlog_count": 0, "in_flight_count": 0},
        "application": {"service_manager": "none", "process_running": True},
        "aggregate": {"schema_version": "senior-pomidor.edge.health.v1", "state": "OK", "reasons": []},
    }
    result = dumped(build_operator_edge_reliability(event(health=health), now=NOW))

    assert result["status"] == "OK"
    assert result["application"] == {
        "status": "OK",
        "process_running": True,
        "process_uptime_seconds": None,
        "systemd_available": None,
        "systemd_active_state": None,
        "systemd_sub_state": None,
        "systemd_service_active": None,
    }


def _current_payload(*, record_id: str = "spool:pi-001:operator") -> dict:
    observed = datetime.now(UTC).replace(microsecond=0)
    return {
        "schema_version": "senior-pomidor.edge.telemetry.v2",
        "record_id": record_id,
        "device_id": "pi-001",
        "timestamp_utc": observed.isoformat().replace("+00:00", "Z"),
        "pods": {},
        "system_health": healthy_system_health(),
    }


def test_endpoint_returns_typed_current_response(client) -> None:
    payload = _current_payload()
    assert client.post("/api/v1/edge/telemetry", json=payload).status_code == 202

    response = client.get("/api/v1/operator/edges/pi-001/reliability")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "senior-pomidor.operator.edge-reliability.v1"
    assert body["record_id"] == payload["record_id"]
    assert body["freshness"]["status"] == "FRESH"
    assert body["watchdog"]["last_healthy_heartbeat_at_utc"].endswith("Z")


def test_endpoint_rejects_unsafe_id_and_reports_missing_telemetry(client) -> None:
    invalid = client.get("/api/v1/operator/edges/unsafe%20device/reliability")
    missing = client.get("/api/v1/operator/edges/missing/reliability")

    assert invalid.status_code == 400
    assert missing.status_code == 404
    assert missing.json() == {"detail": "device telemetry not found"}


def test_endpoint_database_failure_is_bounded() -> None:
    class FailingSession:
        def scalar(self, _query):
            raise SQLAlchemyError("private SQL detail")

    def override_db():
        yield FailingSession()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/operator/edges/pi-001/reliability")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "operator reliability storage unavailable"}
    assert "private" not in response.text


def test_endpoint_query_has_deterministic_tie_break_and_no_relationship_loading() -> None:
    captured = []

    class CapturingSession:
        def scalar(self, query):
            captured.append(query)
            return event(event_id=2)

    response = app.url_path_for("operator_edge_reliability", device_id="pi-001")
    assert str(response) == "/api/v1/operator/edges/pi-001/reliability"

    from app.api import operator_edge_reliability

    operator_edge_reliability("pi-001", CapturingSession())
    query = captured[0]
    sql = str(query)
    assert "raw_payload_jsonb" not in sql
    assert "pod_readings" not in sql
    assert "pod_errors" not in sql
    assert [str(item) for item in query._order_by_clauses] == [
        "telemetry_events.timestamp_utc DESC",
        "telemetry_events.id DESC",
    ]


def test_openapi_contains_versioned_response_model(client) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/operator/edges/{device_id}/reliability"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema == {"$ref": "#/components/schemas/OperatorEdgeReliabilityV1"}
