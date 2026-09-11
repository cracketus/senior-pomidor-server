import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.map import (
    ChannelMetric,
    ChannelSelector,
    EffectiveInterval,
    EvidenceKind,
    EvidenceMode,
    EvidenceReason,
    EvidenceValidity,
    RawEvidenceErrorCode,
    RawEvidenceReader,
    RawEvidenceReadError,
    RawEvidenceRequest,
    Unit,
    canonical_evidence_bytes,
    compute_evidence_digest,
)
from app.map.raw_reader import RAW_EVIDENCE_SQL, normalize_evidence_rows
from app.models import Base, PodError, PodReading, TelemetryEvent
from app.services import persist_telemetry_result

NOW = datetime(2026, 6, 7, 12, 30, tzinfo=UTC)
START = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
END = datetime(2026, 6, 7, 12, 20, tzinfo=UTC)
DIGEST = "a" * 64


def selector(**updates):
    values = {
        "source_id": "synthetic-source-1",
        "storage_device_id": "synthetic-device-1",
        "channel_id": "synthetic-channel-a-v1",
        "pod_key": "pod-a",
        "metric_name": ChannelMetric.SOIL_MOISTURE_PERCENT,
        "error_sensors": ("soil",),
        "unit": Unit.PERCENT,
        "minimum": 0.0,
        "maximum": 100.0,
        "max_age_seconds": 1200,
        "effective_interval": EffectiveInterval(
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        ),
        "profile_id": "synthetic-soil-profile",
        "profile_version": "v1",
    }
    values.update(updates)
    return ChannelSelector(**values)


def request(**updates):
    values = {
        "selectors": (selector(),),
        "window_start": START,
        "window_end": END,
        "mode": EvidenceMode.RECONSTRUCTED,
        "data_cutoff": NOW,
        "topology_revision_id": "synthetic-r001",
        "topology_digest": DIGEST,
    }
    values.update(updates)
    return RawEvidenceRequest(**values)


def row(
    row_type,
    row_id,
    observed,
    received,
    *,
    record_id=None,
    pod_key=None,
    enabled=None,
    values=None,
    sensor=None,
    error_detail=None,
):
    return {
        "row_type": row_type,
        "row_id": row_id,
        "event_id": row_id // 10 if row_type != "event" else row_id,
        "record_id": record_id,
        "source_id": "synthetic-source-1",
        "observation_at": observed,
        "received_at": received,
        "source_schema_version": "senior-pomidor.edge.telemetry.v2",
        "pod_key": pod_key,
        "enabled": enabled,
        "values_jsonb": values,
        "sensor": sensor,
        "error_detail": error_detail,
    }


def normalize(rows, *, raw_request=None):
    raw_request = raw_request or request()
    return normalize_evidence_rows(raw_request, rows, evaluation_time=NOW, data_cutoff=NOW)


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"selectors": ()}, "at least 1"),
        ({"window_end": START}, "half-open"),
        ({"window_start": END - timedelta(days=8)}, "7 days"),
        ({"data_cutoff": END - timedelta(seconds=1)}, "data_cutoff"),
    ],
)
def test_request_rejects_unbounded_or_invalid_time_scope(updates, match):
    with pytest.raises(ValidationError, match=match):
        request(**updates)


def test_point_query_allows_exact_snapshot_instant_without_extending_cutoff():
    point = RawEvidenceRequest(
        selectors=request().selectors,
        window_start=END,
        window_end=END + timedelta(microseconds=1),
        mode=EvidenceMode.RECONSTRUCTED,
        data_cutoff=END,
        point_query_at=END,
        topology_revision_id="synthetic-r001",
        topology_digest=DIGEST,
    )
    assert point.point_query_at == END
    assert point.data_cutoff == END


def test_request_rejects_duplicates_ambiguous_sources_and_submicroseconds():
    with pytest.raises(ValidationError, match="duplicate channel"):
        request(selectors=(selector(), selector()))
    with pytest.raises(ValidationError, match="multiple sources"):
        request(
            selectors=(
                selector(),
                selector(source_id="synthetic-source-2", channel_id="synthetic-channel-b-v1"),
            )
        )
    payload = request().model_dump(mode="json")
    payload["window_start"] = "2026-06-07T12:00:00.1234567Z"
    with pytest.raises(ValidationError, match="finer than microseconds"):
        RawEvidenceRequest.model_validate(payload)
    with pytest.raises(ValidationError, match="duplicate error sensors"):
        selector(error_sensors=("soil", "soil"))
    with pytest.raises(ValidationError, match="at least 1"):
        selector(error_sensors=())
    with pytest.raises(ValidationError, match="duplicate channel"):
        request(
            selectors=(
                selector(),
                selector(metric_name=ChannelMetric.SOIL_TEMPERATURE_C, unit=Unit.CELSIUS),
            )
        )
    with pytest.raises(ValidationError, match="globally unique"):
        request(
            selectors=(
                selector(),
                selector(
                    source_id="synthetic-source-2",
                    storage_device_id="synthetic-device-2",
                    channel_id="synthetic-channel-a-v1",
                ),
            )
        )


def test_percent_range_is_explicit_and_boolean_bounds_are_rejected():
    with pytest.raises(ValidationError, match=r"explicit 0\.\.100"):
        selector(maximum=1.0)
    with pytest.raises(ValidationError, match="finite numbers"):
        selector(minimum=False)
    with pytest.raises(ValidationError, match="percent metrics must use PERCENT"):
        selector(unit=Unit.CELSIUS)
    with pytest.raises(ValidationError, match="only percent metrics may use it"):
        selector(metric_name=ChannelMetric.SOIL_TEMPERATURE_C)


def test_normalization_preserves_seed_omission_errors_disabled_invalid_and_future_clock():
    old = START - timedelta(minutes=10)
    rows = [
        row("event", 1, old, old + timedelta(seconds=2), values={"watchdog": {"state": "BACKLOG"}}),
        row(
            "reading",
            10,
            old,
            old + timedelta(seconds=2),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 50.0},
        ),
        # A later omission is a source receipt only and cannot replace the seed.
        row("event", 2, START - timedelta(minutes=2), START - timedelta(minutes=1)),
        row("event", 3, START + timedelta(minutes=1), START + timedelta(minutes=2)),
        row(
            "reading",
            30,
            START + timedelta(minutes=1),
            START + timedelta(minutes=2),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 101.0},
        ),
        row(
            "error",
            31,
            START + timedelta(minutes=3),
            START + timedelta(minutes=4),
            pod_key="pod-a",
            sensor="soil",
            error_detail="synthetic private diagnostic",
        ),
        row(
            "reading",
            40,
            START + timedelta(minutes=5),
            START + timedelta(minutes=6),
            pod_key="pod-a",
            enabled=False,
            values={"soil_moisture_percent": 48.0},
        ),
        row("event", 5, NOW + timedelta(minutes=1), NOW - timedelta(minutes=1)),
        row(
            "reading",
            50,
            NOW + timedelta(minutes=1),
            NOW - timedelta(minutes=1),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 49.0},
        ),
    ]

    batch = normalize(rows)
    channel_items = [item for item in batch.items if item.channel_id]
    assert [item.evidence_kind for item in channel_items] == [
        EvidenceKind.CHANNEL_VALUE,
        EvidenceKind.CHANNEL_INVALID_VALUE,
        EvidenceKind.EXPLICIT_ERROR,
        EvidenceKind.DISABLED_CHANNEL,
        EvidenceKind.CHANNEL_INVALID_VALUE,
    ]
    assert channel_items[0].value == 50.0
    assert channel_items[1].reason == EvidenceReason.OUT_OF_RANGE
    assert channel_items[2].detail_digest
    assert "synthetic private" not in batch.model_dump_json()
    assert channel_items[3].reason == EvidenceReason.DISABLED
    assert channel_items[4].validity == EvidenceValidity.CLOCK_INVALID
    receipt = next(item for item in batch.items if item.health_facts)
    assert receipt.health_facts[0].path == "system_health.watchdog.state"
    assert receipt.health_facts[0].value == "BACKLOG"


def test_latest_pre_window_invalidating_evidence_is_the_only_channel_seed():
    rows = [
        row(
            "reading",
            10,
            START - timedelta(minutes=15),
            START - timedelta(minutes=14),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 45.0},
        ),
        row(
            "error",
            21,
            START - timedelta(minutes=5),
            START - timedelta(minutes=4),
            pod_key="pod-a",
            sensor="soil",
            error_detail="synthetic failure",
        ),
    ]
    items = normalize(rows).items
    channel_items = [item for item in items if item.channel_id]
    assert len(channel_items) == 1
    assert channel_items[0].evidence_kind == EvidenceKind.EXPLICIT_ERROR


def test_pre_window_seed_respects_each_channel_max_age():
    raw_request = request(selectors=(selector(max_age_seconds=60),))
    rows = [
        row(
            "reading",
            10,
            START - timedelta(minutes=2),
            START - timedelta(minutes=1),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 45.0},
        )
    ]

    assert not any(item.channel_id for item in normalize(rows, raw_request=raw_request).items)


def test_unrelated_sensor_error_does_not_fan_out_to_channel():
    rows = [
        row(
            "error",
            21,
            START + timedelta(minutes=5),
            START + timedelta(minutes=6),
            pod_key="pod-a",
            sensor="bme280",
            error_detail="synthetic failure",
        )
    ]

    assert not any(item.channel_id for item in normalize(rows).items)


def test_binding_interval_excludes_channel_fact_but_preserves_source_receipt():
    raw_request = request(
        selectors=(
            selector(
                effective_interval=EffectiveInterval(effective_from=START + timedelta(minutes=10), effective_to=END)
            ),
        )
    )
    rows = [
        row("event", 1, START + timedelta(minutes=1), START + timedelta(minutes=2)),
        row(
            "reading",
            10,
            START + timedelta(minutes=1),
            START + timedelta(minutes=2),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": 50.0},
        ),
    ]
    assert [item.evidence_kind for item in normalize(rows, raw_request=raw_request).items] == [
        EvidenceKind.SOURCE_RECEIPT
    ]


def test_legacy_and_record_identities_are_durable_and_duplicates_normalize_once():
    observed = START + timedelta(minutes=1)
    received = observed + timedelta(seconds=1)
    legacy = row(
        "reading",
        10,
        observed,
        received,
        pod_key="pod-a",
        enabled=True,
        values={"soil_moisture_percent": 10.0},
    )
    current = row("event", 2, observed, received, record_id="transport-shared-id")
    batch = normalize([legacy, legacy, current, current])
    identities = {item.event_identity for item in batch.items}
    assert identities == {"legacy:synthetic-source-1:event:1", "record:transport-shared-id"}
    assert next(item for item in batch.items if item.record_id).record_id == "transport-shared-id"


def test_health_errors_are_bounded_digests_and_native_warning_state_survives():
    health = {
        "aggregate": {
            "schema_version": "senior-pomidor.edge.health.v1",
            "state": "DEGRADED",
            "reasons": ["delivery_ambiguous"],
        },
        "errors": [{"sensor": "network", "message": "synthetic sensitive detail"}],
    }
    batch = normalize([row("event", 1, START, START + timedelta(seconds=1), values=health)])
    serialized = batch.model_dump_json()
    assert "DEGRADED" in serialized
    assert "delivery_ambiguous" in serialized
    assert "synthetic sensitive detail" not in serialized
    error_fact = next(fact for fact in batch.items[0].health_facts if fact.detail_digest)
    assert error_fact.warning_level == "warning"


def test_edge_fixture_replays_through_real_ingestion_persistence_and_normalization(monkeypatch):
    fixture_path = Path("tests/fixtures/edge_integration/telemetry_mqtt.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))["payload"]
    observed = datetime.fromisoformat(payload["timestamp_utc"].replace("Z", "+00:00"))
    received = observed + timedelta(minutes=5)
    monkeypatch.setattr("app.services.now_utc", lambda: received)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            persisted = persist_telemetry_result(session, payload, "mqtt")
            event = session.scalar(select(TelemetryEvent))
            readings = list(session.scalars(select(PodReading).order_by(PodReading.id)))
            errors = list(session.scalars(select(PodError).order_by(PodError.id)))
            assert persisted.outcome == "accepted"
            assert event is not None
            event_observed = event.timestamp_utc.replace(tzinfo=UTC)
            event_received = event.received_at.replace(tzinfo=UTC)
            rows = [
                row(
                    "event",
                    event.id,
                    event_observed,
                    event_received,
                    record_id=event.record_id,
                    values=event.system_health_jsonb,
                )
            ]
            rows.extend(
                row(
                    "reading",
                    item.id * 10,
                    event_observed,
                    event_received,
                    record_id=event.record_id,
                    pod_key=item.pod_key,
                    enabled=item.enabled,
                    values={"soil_moisture_percent": item.soil_moisture_percent},
                )
                for item in readings
            )
            rows.extend(
                row(
                    "error",
                    item.id * 10 + 1,
                    event_observed,
                    event_received,
                    record_id=event.record_id,
                    pod_key=item.pod_key,
                    sensor=item.sensor,
                    error_detail=item.message,
                )
                for item in errors
            )
        replay_request = request(
            selectors=(selector(pod_key="pod_2", channel_id="synthetic-channel-b-v1"),),
            window_start=observed - timedelta(minutes=1),
            window_end=observed + timedelta(minutes=1),
            data_cutoff=received,
        )
        batch = normalize_evidence_rows(
            replay_request,
            rows,
            evaluation_time=received,
            data_cutoff=received,
        )
        assert any(item.value == 7.6 for item in batch.items)
        assert not any(item.evidence_kind == EvidenceKind.EXPLICIT_ERROR for item in batch.items)
        assert "Could not find sensor" not in batch.model_dump_json()
    finally:
        engine.dispose()


def test_canonical_digest_has_microseconds_stable_numbers_and_order():
    rows = [
        row(
            "reading",
            20,
            START + timedelta(seconds=2),
            START + timedelta(seconds=3),
            pod_key="pod-a",
            enabled=True,
            values={"soil_moisture_percent": -0.0},
        ),
        row("event", 1, START + timedelta(microseconds=1), START + timedelta(seconds=1)),
    ]
    first = normalize(rows)
    second = normalize(reversed(rows))
    canonical = canonical_evidence_bytes(first).decode()
    assert first.digest == second.digest == compute_evidence_digest(first)
    assert "2026-06-07T12:00:00.000001Z" in canonical
    assert '"value":0' in canonical
    assert first.digest == "8ad92b84ff0837bf94674c6ac0764cdd8d4a4e41f20309fcb7d4b4216c6a722c"


def test_query_is_one_bounded_union_and_counts_event_reading_error_rows():
    lowered = " ".join(RAW_EVIDENCE_SQL.lower().split())
    assert lowered.count("union all") == 2
    assert "limit 100001" in lowered
    assert "raw_payload_jsonb" not in lowered
    assert all(table in lowered for table in ("telemetry_events", "pod_readings", "pod_errors"))


def test_100001st_row_fails_explicitly_before_normalization():
    with pytest.raises(RawEvidenceReadError) as exc_info:
        normalize([{}] * 100_001)
    assert exc_info.value.code == RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED


def test_reader_rejects_non_postgresql_without_opening_a_connection():
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(RawEvidenceReadError) as exc_info:
            RawEvidenceReader(engine, clock=lambda: NOW).read(request())
        assert exc_info.value.code == RawEvidenceErrorCode.UNSUPPORTED_BACKEND
    finally:
        engine.dispose()


def test_reader_never_calls_mutable_estimator(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("mutable estimator path was called")

    monkeypatch.setattr("app.state_estimator.persistence.latest_state_or_estimate", fail_if_called)
    engine = FakeEngine()
    assert RawEvidenceReader(engine, clock=lambda: NOW).read(request()).row_count == 0


class FakeMappings:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value

    def all(self):
        return self.value


class FakeResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return FakeMappings(self.value)


class FakeBegin:
    def __init__(self):
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def rollback(self):
        self.rolled_back = True


class FakeConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def begin(self):
        self.calls.append("BEGIN")
        self.transaction = FakeBegin()
        return self.transaction

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if sql.startswith("SELECT current_setting"):
            return FakeResult({"isolation": "repeatable read", "read_only": "on", "statement_timeout": "5s"})
        if "WITH selectors" in sql:
            return FakeResult([])
        return FakeResult([])


class FakeDialect:
    name = "postgresql"


class FakeEngine:
    dialect = FakeDialect()

    def __init__(self):
        self.connection = FakeConnection()

    def connect(self):
        return self.connection


@pytest.mark.parametrize(
    ("mode", "expected_cutoff"),
    [(EvidenceMode.AS_KNOWN_CORE, END), (EvidenceMode.RECONSTRUCTED, NOW)],
)
def test_reader_sets_verified_transaction_before_read_and_applies_mode_cutoff(mode, expected_cutoff):
    engine = FakeEngine()
    batch = RawEvidenceReader(engine, clock=lambda: NOW).read(request(mode=mode))
    calls = engine.connection.calls
    assert calls[0] == "BEGIN"
    assert str(calls[1][0]) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert str(calls[2][0]) == "SET LOCAL statement_timeout = '5s'"
    assert str(calls[3][0]).startswith("SELECT current_setting")
    assert calls[4][1]["receipt_cutoff"] == expected_cutoff
    assert engine.connection.transaction.rolled_back is True
    assert batch.data_cutoff == NOW


def test_golden_fixture_round_trips():
    path = "tests/fixtures/map_raw_evidence/golden_v1.json"
    with open(path, encoding="utf-8") as handle:
        fixture = json.load(handle)
    batch = normalize(
        [
            row(
                "reading",
                20,
                START + timedelta(seconds=2),
                START + timedelta(seconds=3),
                pod_key="pod-a",
                enabled=True,
                values={"soil_moisture_percent": -0.0},
            ),
            row("event", 1, START + timedelta(microseconds=1), START + timedelta(seconds=1)),
        ]
    )
    assert fixture == {"schema_version": batch.schema_version, "digest": batch.digest}
