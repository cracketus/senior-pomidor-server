"""Exercise actual HTTP serialization, including relationship loads."""

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError


def payload(index, device="budget-edge"):
    return {
        "schema_version": "senior-pomidor.edge.telemetry.v2",
        "record_id": f"budget:{device}:{index}",
        "device_id": device,
        "timestamp_utc": f"2026-09-01T12:00:{index:02d}Z",
        "pods": [{"pod_key": "pod-1", "soil_moisture_percent": 42.0}],
    }


@pytest.mark.parametrize("devices", [1, 20])
def test_latest_query_count_does_not_scale_per_device(client, devices):
    for i in range(devices):
        for sequence in (1, 2):
            assert client.post("/api/v1/edge/telemetry", json=payload(sequence, f"budget-{i:02d}")).status_code == 202
    statements = []

    def count(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        response = client.get("/api/v1/devices/latest")
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == devices
    assert [r["device_id"] for r in rows] == sorted(r["device_id"] for r in rows)
    assert all(r["record_id"].endswith(":2") and len(r["readings"]) == 1 for r in rows)
    assert len(statements) <= 3, statements


@pytest.mark.parametrize(("route", "budget"), [("latest", 3), ("telemetry?limit=20", 3)])
def test_single_device_read_query_budget(client, route, budget):
    for i in range(20):
        assert client.post("/api/v1/edge/telemetry", json=payload(i)).status_code == 202
    statements = []

    def count(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        response = client.get(f"/api/v1/devices/budget-edge/{route}")
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    assert response.status_code == 200
    assert len(statements) <= budget, statements


@pytest.mark.parametrize("table", ["devices", "telemetry_events", "pod_readings"])
def test_storage_failure_rolls_back_and_retry_succeeds(client, table):
    def fail(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lower().startswith(f"insert into {table}"):
            raise OperationalError("synthetic write failure", {}, RuntimeError("injected"))

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        response = client.post("/api/v1/edge/telemetry", json=payload(1))
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert response.status_code == 503
    assert response.json()["status"] == "retry"
    assert client.get("/api/v1/devices").json() == []
    assert client.get("/api/v1/devices/budget-edge/telemetry").json() == []
    retry = client.post("/api/v1/edge/telemetry", json=payload(1))
    assert retry.status_code == 202
    assert retry.json()["status"] == "accepted"
    assert len(client.get("/api/v1/devices/budget-edge/telemetry").json()) == 1
