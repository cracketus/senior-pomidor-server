from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import TelemetryEvent
from app.operator_edge_reliability import build_operator_edge_reliability


def payload(record_id: str, observed_at: str) -> dict:
    return {
        "schema_version": "senior-pomidor.edge.telemetry.v2",
        "record_id": record_id,
        "device_id": "temporal-edge",
        "timestamp_utc": observed_at,
        "pods": {"pod_1": {"enabled": True, "metrics": {"soil_moisture_percent": 42.0}}},
    }


def test_delayed_out_of_order_delivery_preserves_observation_time_and_latest_order(client) -> None:
    newer = payload("temporal:newer", "2026-08-20T12:00:00Z")
    delayed_older = payload("temporal:older-replayed", "2026-08-19T12:00:00Z")

    assert client.post("/api/v1/edge/telemetry", json=newer).json()["status"] == "accepted"
    assert client.post("/api/v1/edge/telemetry", json=delayed_older).json()["status"] == "accepted"

    latest = client.get("/api/v1/devices/temporal-edge/latest").json()
    history = client.get("/api/v1/devices/temporal-edge/telemetry?limit=10").json()

    assert latest["record_id"] == newer["record_id"]
    assert latest["timestamp_utc"] == newer["timestamp_utc"]
    assert [event["record_id"] for event in history] == [delayed_older["record_id"], newer["record_id"]]
    assert [event["timestamp_utc"] for event in history] == [
        delayed_older["timestamp_utc"],
        newer["timestamp_utc"],
    ]
    assert all(event["received_at"] != event["timestamp_utc"] for event in history)


def test_duplicate_delivery_with_later_receive_attempt_does_not_rewrite_stored_times(client) -> None:
    observation = payload("temporal:duplicate", "2026-08-18T07:00:00Z")
    accepted = client.post("/api/v1/edge/telemetry", json=observation)
    before = client.get("/api/v1/devices/temporal-edge/latest").json()

    duplicate = client.post("/api/v1/edge/telemetry", json=observation)
    after = client.get("/api/v1/devices/temporal-edge/latest").json()

    assert accepted.json()["status"] == "accepted"
    assert duplicate.json() == {"record_id": observation["record_id"], "status": "duplicate"}
    assert after["timestamp_utc"] == before["timestamp_utc"] == observation["timestamp_utc"]
    assert after["received_at"] == before["received_at"]


@pytest.mark.parametrize(
    ("observed_at", "expected_freshness"),
    [
        (datetime(2026, 8, 26, 12, 0, tzinfo=UTC), "FRESH"),
        (datetime(2026, 8, 26, 11, 40, tzinfo=UTC), "FRESH"),
        (datetime(2026, 8, 26, 11, 39, 59, 999999, tzinfo=UTC), "STALE"),
        (datetime(2026, 8, 26, 12, 0, 0, 1, tzinfo=UTC), "UNKNOWN"),
        ("invalid", "UNKNOWN"),
    ],
)
def test_clock_skew_and_exact_freshness_boundary_fail_safe(observed_at, expected_freshness) -> None:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    event = TelemetryEvent(
        id=1,
        record_id="temporal:freshness",
        device_id="temporal-edge",
        timestamp_utc=observed_at,
        schema_version="senior-pomidor.edge.telemetry.v2",
        source="test",
        raw_payload_jsonb={},
        system_health_jsonb={},
        received_at=now + timedelta(seconds=1),
    )

    result = build_operator_edge_reliability(event, now=now)

    assert result.freshness.status == expected_freshness
    if expected_freshness != "FRESH":
        assert result.status == "UNKNOWN"


def test_europe_vienna_dst_fold_changes_local_offset_without_changing_utc_identity() -> None:
    vienna = ZoneInfo("Europe/Vienna")
    summer_side = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    winter_side = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)

    first_local = summer_side.astimezone(vienna)
    second_local = winter_side.astimezone(vienna)

    assert first_local.strftime("%Y-%m-%dT%H:%M") == second_local.strftime("%Y-%m-%dT%H:%M") == "2026-10-25T02:30"
    assert first_local.utcoffset() == timedelta(hours=2)
    assert second_local.utcoffset() == timedelta(hours=1)
    assert first_local.astimezone(UTC) == summer_side
    assert second_local.astimezone(UTC) == winter_side
