"""Bounded reproducible properties complement, never replace, real transport E2E."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models import TelemetryEvent
from app.operator_edge_reliability import build_operator_edge_reliability
from app.validation import validate_telemetry_payload

PROPERTY = settings(
    max_examples=35, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def observation(index, offset=0):
    return {
        "schema_version": "senior-pomidor.edge.telemetry.v2",
        "record_id": f"property:{index}",
        "device_id": "property-edge",
        "timestamp_utc": (datetime(2026, 9, 1, tzinfo=UTC) + timedelta(seconds=offset))
        .isoformat()
        .replace("+00:00", "Z"),
        "pods": {"pod_1": {"enabled": True, "metrics": {"soil_moisture_percent": 42.0}}},
    }


@PROPERTY
@given(order=st.lists(st.integers(min_value=0, max_value=12), min_size=1, max_size=30))
def test_duplicate_permutation_preserves_identities_and_latest(client_factory, order):
    client = client_factory()
    # A new database per generated example, not just per pytest invocation.
    seen = set()
    for index in order:
        result = client.post("/api/v1/edge/telemetry", json=observation(index, index))
        assert result.status_code == 202
        assert result.json()["status"] == ("duplicate" if index in seen else "accepted")
        seen.add(index)
    history = client.get("/api/v1/devices/property-edge/telemetry?limit=100").json()
    assert len(history) == len(set(order))
    assert {r["record_id"] for r in history} == {f"property:{i}" for i in order}
    assert client.get("/api/v1/devices/property-edge/latest").json()["record_id"] == f"property:{max(order)}"


@PROPERTY
@given(moisture=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False), optional=st.booleans())
def test_wire_round_trip_preserves_units_and_optionality(moisture, optional):
    payload = observation(1)
    payload["pods"]["pod_1"]["metrics"]["soil_moisture_percent"] = moisture
    if optional:
        payload["system_health"] = {}
    round_trip = json.loads(json.dumps(payload, allow_nan=False))
    assert validate_telemetry_payload(round_trip) == validate_telemetry_payload(payload)
    assert round_trip["pods"]["pod_1"]["metrics"]["soil_moisture_percent"] == moisture


@PROPERTY
@given(offset=st.one_of(st.integers(min_value=-100000, max_value=-1201), st.integers(min_value=1, max_value=100000)))
def test_stale_future_and_missing_health_never_become_ok(offset):
    now = datetime(2026, 9, 1, tzinfo=UTC)
    event = TelemetryEvent(
        id=1,
        record_id="property:health",
        device_id="property-edge",
        timestamp_utc=now + timedelta(seconds=offset),
        schema_version="senior-pomidor.edge.telemetry.v2",
        source="property",
        raw_payload_jsonb={},
        system_health_jsonb={},
        received_at=now,
    )
    result = build_operator_edge_reliability(event, now=now)
    assert result.status == "UNKNOWN"
    assert result.freshness.status != "FRESH"


@PROPERTY
@given(seconds=st.integers(min_value=-7200, max_value=7200))
def test_dst_gap_fold_round_trip_preserves_observation_identity(seconds):
    for transition in (datetime(2026, 3, 29, 1, tzinfo=UTC), datetime(2026, 10, 25, 1, tzinfo=UTC)):
        observed = transition + timedelta(seconds=seconds)
        assert observed.astimezone(ZoneInfo("Europe/Vienna")).astimezone(UTC) == observed


@PROPERTY
@given(suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-", max_size=40))
def test_malformed_timestamp_cannot_partially_persist(client_factory, suffix):
    client = client_factory()
    value = observation(1)
    value["timestamp_utc"] = "invalid:" + suffix
    response = client.post("/api/v1/edge/telemetry", json=value)
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert client.get("/api/v1/devices/property-edge/telemetry").json() == []
