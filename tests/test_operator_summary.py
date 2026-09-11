import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from sqlalchemy.exc import SQLAlchemyError

from app.models import AnomalyRecord, StateSnapshot, TelemetryEvent
from app.operator_summary import (
    DecisionsResponse,
    OperatorSummaryService,
    PhotoView,
    PlantView,
    Reason,
    StatusResponse,
    anomaly_status,
    project_state,
    unknown_edge_reliability,
)


def test_operator_views_are_versioned_and_decisions_are_explicitly_unimplemented(client_factory) -> None:
    client = client_factory()
    response = client.get("/api/v1/operator/decisions")
    assert response.status_code == 200
    body = response.json()
    assert DecisionsResponse.model_validate(body).data.items == []
    assert body["schema_version"] == "senior-pomidor.operator.v1"
    assert body["availability"] == "NOT_IMPLEMENTED"


def test_all_operator_views_validate_against_published_schema(client_factory) -> None:
    schema_path = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "operator-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    client = client_factory()
    for view in ("status", "plants", "edges", "anomalies", "photos", "decisions"):
        response = client.get(f"/api/v1/operator/{view}")
        assert response.status_code == 200
        validator.validate(response.json())

    edge = json.loads(
        (
            schema_path.parent.parent.parent / "tests" / "fixtures" / "contracts" / "operator_edge_reliability_v1.json"
        ).read_text(encoding="utf-8")
    )
    edges_body = client.get("/api/v1/operator/edges").json()
    edges_body["data"] = {"items": [edge], "returned_count": 1, "has_more": False}
    validator.validate(edges_body)
    status_body = client.get("/api/v1/operator/status").json()
    status_body["data"]["edge"] = [edge]
    validator.validate(status_body)


def test_operator_plants_and_edges_use_persisted_rows(client_factory) -> None:
    client = client_factory()
    assert client.get("/api/v1/operator/plants").status_code == 200
    assert client.get("/api/v1/operator/edges").status_code == 200
    assert client.get("/api/v1/operator/status").status_code == 200
    assert (
        StatusResponse.model_validate(client.get("/api/v1/operator/status").json()).data.host.availability
        == "NOT_IMPLEMENTED"
    )


def test_state_projection_preserves_quality_and_bounded_soil_probes() -> None:
    projected = project_state(
        StateSnapshot(
            state_id="state-1",
            node_id="pi-001",
            ts=datetime(2026, 9, 11, 12, tzinfo=UTC),
            generated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            payload_jsonb={
                "quality": {"level": "DEGRADED", "state_confidence": 0.72},
                "env": {},
                "soil": {"probes": [{"id": "soil-1", "position": "top", "moisture_pct": 44.0, "private": "omit"}]},
                "plant": {},
            },
        )
    )
    assert projected is not None
    assert projected.status == "WARN"
    assert projected.confidence == 0.72
    assert projected.soil.probes[0].moisture_pct == 44.0
    assert not hasattr(projected.soil.probes[0], "private")


def test_state_projection_rejects_non_finite_and_overflow_numbers() -> None:
    projected = project_state(
        StateSnapshot(
            state_id="state-invalid-numbers",
            node_id="pi-001",
            ts=datetime(2026, 9, 11, 12, tzinfo=UTC),
            generated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            payload_jsonb={
                "quality": {"level": "GOOD", "state_confidence": float("nan")},
                "env": {"air_temp_c": float("inf"), "rh_pct": 55.0},
                "soil": {"temp_c": 20.0, "probes": [{"id": "soil-1", "moisture_pct": 10**10000}]},
                "plant": {"leaf_temp_c": float("-inf")},
            },
        )
    )
    assert projected is not None
    assert projected.status == "OK"
    assert projected.confidence is None
    assert projected.env.air_temp_c is None
    assert projected.plant.leaf_temp_c is None
    assert projected.soil.probes[0].moisture_pct is None


def test_status_keeps_available_response_when_one_component_read_fails(client_factory, monkeypatch) -> None:
    client = client_factory()

    def fail_plants(self, limit=100):
        raise SQLAlchemyError("synthetic")

    monkeypatch.setattr(OperatorSummaryService, "plants", fail_plants)
    response = client.get("/api/v1/operator/status")
    assert response.status_code == 200
    body = response.json()
    assert body["completeness"] == "PARTIAL"
    assert any(reason["code"] == "nodes_unavailable" for reason in body["reasons"])


def test_anomaly_severity_vocabulary_maps_to_operator_status() -> None:
    assert anomaly_status("HIGH") == "ALERT"
    assert anomaly_status("CRITICAL") == "ALERT"
    assert anomaly_status("MEDIUM") == "WARN"
    assert anomaly_status("unknown-value") == "UNKNOWN"


def test_status_includes_active_anomaly_reason_and_escalation(monkeypatch) -> None:
    class Result:
        def all(self):
            return [
                AnomalyRecord(
                    anomaly_id="a-1",
                    node_id="pi-001",
                    type="heat",
                    status="ACTIVE",
                    severity="CRITICAL",
                    ts=datetime(2026, 9, 11, 12, tzinfo=UTC),
                    state_id=None,
                    payload_jsonb={},
                )
            ]

    class FakeDB:
        def scalars(self, query):
            return Result()

        def scalar(self, query):
            return 3

        def rollback(self):
            return None

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    monkeypatch.setattr(service, "plants", lambda limit=100: ([], False))
    monkeypatch.setattr(service, "edges", lambda limit=100: ([], False))
    _, _, _, reasons, _ = service.status()
    assert any(reason.code == "active_anomaly_alert" and reason.status == "ALERT" for reason in reasons)


def test_status_aggregates_active_anomalies_beyond_display_limit(monkeypatch) -> None:
    class Result:
        def all(self):
            return ["WARN"] * 100 + ["CRITICAL"]

    class FakeDB:
        def scalars(self, query):
            return Result()

        def scalar(self, query):
            return 3

        def rollback(self):
            return None

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    monkeypatch.setattr(service, "plants", lambda limit=100: ([], False))
    monkeypatch.setattr(service, "edges", lambda limit=100: ([], False))
    _, _, _, reasons, _ = service.status()
    assert any(reason.code == "active_anomaly_alert" for reason in reasons)


def test_status_selects_newest_state_across_nodes(monkeypatch) -> None:
    older = StateSnapshot(
        state_id="state-old",
        node_id="pi-001",
        ts=datetime(2026, 9, 11, 10, tzinfo=UTC),
        generated_at=datetime(2026, 9, 11, 10, tzinfo=UTC),
        payload_jsonb={"quality": {"level": "GOOD"}, "env": {}, "soil": {}, "plant": {}},
    )
    newer = StateSnapshot(
        state_id="state-new",
        node_id="pi-002",
        ts=datetime(2026, 9, 11, 11, tzinfo=UTC),
        generated_at=datetime(2026, 9, 11, 11, tzinfo=UTC),
        payload_jsonb={"quality": {"level": "DEGRADED"}, "env": {}, "soil": {}, "plant": {}},
    )

    class FakeDB:
        def __init__(self):
            self.scalar_calls = 0

        def scalar(self, query):
            self.scalar_calls += 1
            return newer if self.scalar_calls == 1 else None

        def rollback(self):
            return None

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    plants = [
        PlantView(node_id="pi-001", observed_at_utc=newer.ts, state_id=older.state_id, pods=[]),
        PlantView(node_id="pi-002", observed_at_utc=newer.ts, state_id=newer.state_id, pods=[]),
    ]
    monkeypatch.setattr(service, "plants", lambda limit=100: (plants, False))
    monkeypatch.setattr(service, "edges", lambda limit=100: ([], False))
    _, _, state, _, _ = service.status()
    assert state is not None
    assert state.state_id == "state-new"


def test_status_keeps_active_alert_when_nodes_are_unavailable(client_factory, monkeypatch) -> None:
    client = client_factory()

    def fail_status(self):
        return [], [], None, [Reason(code="active_anomaly_alert", status="ALERT", message="active alert")], True

    monkeypatch.setattr(OperatorSummaryService, "status", fail_status)
    response = client.get("/api/v1/operator/status")
    assert response.status_code == 200
    assert response.json()["status"] == "ALERT"


def test_malformed_photo_rows_are_omitted_from_operator_projection() -> None:
    class Result:
        def order_by(self, *args):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    photo_id="photo-invalid",
                    device_id="pi-001",
                    captured_at_utc=datetime(2026, 9, 11, 12, tzinfo=UTC),
                    content_type="image/jpeg",
                    file_size_bytes=-1,
                    sha256="a" * 64,
                    sharpness_score=None,
                )
            ]

    class FakeDB:
        def scalars(self, query):
            return Result()

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    items, has_more = service.photos(node_id=None, since_hours=24, limit=25)
    assert items == []
    assert has_more is False


def test_non_finite_photo_sharpness_is_projected_as_null() -> None:
    class Result:
        def order_by(self, *args):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    photo_id="photo-non-finite",
                    device_id="pi-001",
                    captured_at_utc=datetime(2026, 9, 11, 12, tzinfo=UTC),
                    content_type="image/jpeg",
                    file_size_bytes=10,
                    sha256="a" * 64,
                    sharpness_score=float("nan"),
                ),
                SimpleNamespace(
                    photo_id="photo-infinite",
                    device_id="pi-001",
                    captured_at_utc=datetime(2026, 9, 11, 12, tzinfo=UTC),
                    content_type="image/jpeg",
                    file_size_bytes=10,
                    sha256="b" * 64,
                    sharpness_score=float("inf"),
                ),
            ]

    class FakeDB:
        def scalars(self, query):
            return Result()

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    items, has_more = service.photos(node_id=None, since_hours=24, limit=25)
    assert has_more is False
    assert [item.sharpness_score for item in items] == [None, None]


def test_photo_without_timestamp_is_omitted_from_operator_projection() -> None:
    class Result:
        def order_by(self, *args):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    photo_id="photo-no-timestamp",
                    device_id="pi-001",
                    captured_at_utc=None,
                    content_type="image/jpeg",
                    file_size_bytes=10,
                    sha256="a" * 64,
                    sharpness_score=None,
                )
            ]

    class FakeDB:
        def scalars(self, query):
            return Result()

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    items, has_more = service.photos(node_id=None, since_hours=24, limit=25)
    assert items == []
    assert has_more is False


def test_plants_without_observation_are_not_reported_ok(client_factory, monkeypatch) -> None:
    client = client_factory()
    plant = PlantView(node_id="pi-001", observed_at_utc=None, state_id=None, pods=[])
    monkeypatch.setattr(OperatorSummaryService, "plants", lambda self, limit=100: ([plant], False))
    response = client.get("/api/v1/operator/plants")
    assert response.status_code == 200
    assert response.json()["status"] == "UNKNOWN"


def test_plants_with_invalid_fresh_telemetry_are_not_reported_ok(client_factory, monkeypatch) -> None:
    client = client_factory()
    plant = PlantView(node_id="pi-001", observed_at_utc=datetime.now(UTC), state_id=None, pods=[])
    monkeypatch.setattr(OperatorSummaryService, "plants", lambda self, limit=100: ([plant], False))
    response = client.get("/api/v1/operator/plants")
    assert response.status_code == 200
    assert response.json()["status"] == "UNKNOWN"


def test_empty_anomalies_are_not_reported_ok(client_factory) -> None:
    response = client_factory().get("/api/v1/operator/anomalies")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNKNOWN"
    assert body["availability"] == "UNAVAILABLE"


def test_status_escalates_stale_persisted_state(client_factory, monkeypatch) -> None:
    client = client_factory()
    snapshot = StateSnapshot(
        state_id="state-stale",
        node_id="pi-001",
        ts=datetime(2026, 9, 11, 6, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 11, 6, 0, tzinfo=UTC),
        payload_jsonb={"quality": {"level": "GOOD", "state_confidence": 0.9}, "env": {}, "soil": {}, "plant": {}},
    )
    state = project_state(snapshot)
    assert state is not None
    plant = PlantView(node_id="pi-001", observed_at_utc=state.observed_at_utc, state_id=state.state_id, pods=[])
    monkeypatch.setattr(
        OperatorSummaryService,
        "status",
        lambda self: ([plant], [], state, [], False),
    )
    response = client.get("/api/v1/operator/status")
    assert response.status_code == 200
    assert response.json()["status"] == "WARN"
    assert response.json()["freshness"] == "STALE"


def test_plants_reports_stale_collection_freshness(client_factory, monkeypatch) -> None:
    client = client_factory()
    plant = PlantView(
        node_id="pi-001",
        observed_at_utc=datetime(2026, 9, 11, 6, 0, tzinfo=UTC),
        state_id=None,
        pods=[],
    )
    monkeypatch.setattr(OperatorSummaryService, "plants", lambda self, limit=100: ([plant], False))
    response = client.get("/api/v1/operator/plants")
    assert response.status_code == 200
    assert response.json()["freshness"] == "STALE"


def test_status_includes_unimplemented_host_in_aggregate(client_factory, monkeypatch) -> None:
    client = client_factory()
    now = datetime.now(UTC)
    state = project_state(
        StateSnapshot(
            state_id="state-current",
            node_id="pi-001",
            ts=now,
            generated_at=now,
            payload_jsonb={"quality": {"level": "GOOD", "state_confidence": 0.9}, "env": {}, "soil": {}, "plant": {}},
        )
    )
    assert state is not None
    plant = PlantView(node_id="pi-001", observed_at_utc=now, state_id=state.state_id, pods=[])
    monkeypatch.setattr(OperatorSummaryService, "status", lambda self: ([plant], [], state, [], False))
    assert client.get("/api/v1/operator/status").json()["status"] == "UNKNOWN"


def test_photos_with_stale_evidence_are_not_reported_ok(client_factory, monkeypatch) -> None:
    client = client_factory()
    photo = PhotoView(
        photo_id="photo-1",
        node_id="pi-001",
        captured_at_utc=datetime(2026, 9, 11, 6, 0, tzinfo=UTC),
        content_type="image/jpeg",
        file_size_bytes=10,
        sha256="a" * 64,
        sharpness_score=None,
    )
    monkeypatch.setattr(OperatorSummaryService, "photos", lambda self, node_id, since_hours, limit: ([photo], False))
    response = client.get("/api/v1/operator/photos")
    assert response.status_code == 200
    assert response.json()["status"] == "WARN"


def test_malformed_edge_health_projects_unknown_instead_of_raising() -> None:
    now = datetime.now(UTC)
    event = TelemetryEvent(
        id=1,
        record_id="record-1",
        device_id="pi-001",
        timestamp_utc=now,
        schema_version="senior-pomidor.edge.telemetry.v2",
        source="http",
        raw_payload_jsonb={},
        system_health_jsonb={"watchdog": {"attempt_count": "not-an-int"}},
        received_at=now,
    )
    projected = unknown_edge_reliability(event, now)
    assert projected.status == "UNKNOWN"
    assert projected.reasons[0].code == "edge_reliability_malformed"


def test_devices_without_telemetry_are_projected_as_unknown_edges(monkeypatch) -> None:
    class Result:
        def order_by(self, *args):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [
                type("Device", (), {"device_id": "pi-no-telemetry"})(),
            ]

    class FakeDB:
        def scalars(self, query):
            return Result()

        def scalar(self, query):
            return None

    service = OperatorSummaryService(FakeDB(), now=lambda: datetime(2026, 9, 11, 12, tzinfo=UTC))
    items, has_more = service.edges()
    assert has_more is False
    assert len(items) == 1
    assert items[0].device_id == "pi-no-telemetry"
    assert items[0].status == "UNKNOWN"
    assert items[0].reasons[0].code == "edge_reliability_telemetry_unavailable"
