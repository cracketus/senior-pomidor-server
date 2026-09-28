"""Synthetic alert evidence for the disposable Docker E2E stack only."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import AnomalyRecord, Device, PodError, PodReading, StateSnapshot, TelemetryEvent

PLANT_RULES = {
    "Device telemetry stale",
    "Pod telemetry stale",
    "Pod sensor errors",
    "System health threshold crossed",
    "System health probe errors",
    "Critical dry soil",
    "VPD too low",
    "VPD condensation risk",
    "VPD high",
    "VPD stress",
    "VPD critical",
    "VPD emergency",
    "Edge network health failures",
    "State VPD guardrail crossed",
    "State VPD critical",
    "State confidence low",
    "Active high or critical anomaly",
    "State snapshot stale",
}
PREFIX = "alert-test-"


def snapshot(client: httpx.Client) -> dict[str, dict[str, Any]]:
    response = client.get("/api/prometheus/grafana/api/v1/rules")
    response.raise_for_status()
    return {
        rule["name"]: rule
        for group in response.json()["data"]["groups"]
        for rule in group["rules"]
        if rule.get("name") in PLANT_RULES
    }


def wait_states(client: httpx.Client, names: set[str], state: str, *, healthy: bool = True) -> dict:
    deadline = time.monotonic() + 120
    latest = {}
    while time.monotonic() < deadline:
        latest = snapshot(client)
        if set(latest) == PLANT_RULES and all(
            latest[name].get("state", "").lower() == state
            and ((latest[name].get("health", "").lower() == "ok") == healthy)
            and not str(latest[name].get("lastEvaluation", "0001-")).startswith("0001-")
            for name in names
        ):
            return latest
        time.sleep(1)
    bounded = {name: {key: latest.get(name, {}).get(key) for key in ("state", "health", "lastError")} for name in names}
    raise AssertionError(f"alert states did not converge to {state}: {bounded}")


def seed(engine: Engine) -> None:
    now = datetime.now(UTC)
    # One stable identity per disjoint threshold band; current timestamps allow
    # even the one-minute emergency query to remain relevant through a 30s hold.
    with Session(engine) as db:
        for index, vpd in enumerate([1.0, 0.45, 0.3, 1.4, 2.0, 3.0, 4.5]):
            node = f"{PREFIX}{index}"
            observed = now - timedelta(minutes=25) if index == 0 else now
            db.add(Device(device_id=node, first_seen_at=observed, last_seen_at=now, last_payload_at=observed))
            db.flush()
            event = TelemetryEvent(
                device_id=node,
                record_id=f"alert-test:{index}",
                timestamp_utc=observed,
                received_at=now,
                schema_version="senior-pomidor.edge.telemetry.v2",
                source="test",
                raw_payload_jsonb={},
                system_health_jsonb={
                    "rpi_core": {"cpu_temp_c": 90.0},
                    "network": {"wifi_connected": False},
                    "errors": [{"sensor": "synthetic", "message": "synthetic failure"}],
                },
            )
            db.add(event)
            db.flush()
            db.add(
                PodReading(
                    telemetry_event_id=event.id,
                    device_id=node,
                    pod_key="pod-1",
                    enabled=True,
                    soil_moisture_percent=5.0,
                    air_vpd_kpa=vpd,
                    metrics_jsonb={},
                )
            )
            db.add(
                PodError(
                    telemetry_event_id=event.id,
                    device_id=node,
                    pod_key="pod-1",
                    sensor="synthetic",
                    message="synthetic failure",
                )
            )
            db.add(
                StateSnapshot(
                    state_id=f"alert-state:{index}",
                    node_id=node,
                    ts=now - timedelta(minutes=25) if index == 1 else now,
                    generated_at=now,
                    payload_jsonb={"env": {"vpd_kpa": 3.0}, "quality": {"state_confidence": 0.2}},
                )
            )
        db.add(
            AnomalyRecord(
                anomaly_id="alert-anomaly",
                node_id=f"{PREFIX}2",
                type="SYNTHETIC",
                status="ACTIVE",
                severity="HIGH",
                ts=now,
                payload_jsonb={},
            )
        )
        db.commit()


def recover(engine: Engine) -> None:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(update(Device).where(Device.device_id.startswith(PREFIX)).values(last_payload_at=now))
        connection.execute(
            update(TelemetryEvent)
            .where(TelemetryEvent.device_id.startswith(PREFIX))
            .values(timestamp_utc=now, system_health_jsonb={})
        )
        connection.execute(
            update(PodReading)
            .where(PodReading.device_id.startswith(PREFIX))
            .values(soil_moisture_percent=42.0, air_vpd_kpa=1.0)
        )
        connection.execute(delete(PodError).where(PodError.device_id.startswith(PREFIX)))
        connection.execute(
            update(StateSnapshot)
            .where(StateSnapshot.node_id.startswith(PREFIX))
            .values(ts=now, payload_jsonb={"env": {"vpd_kpa": 1.0}, "quality": {"state_confidence": 1.0}})
        )
        connection.execute(
            update(AnomalyRecord).where(AnomalyRecord.node_id.startswith(PREFIX)).values(status="RESOLVED")
        )


def cleanup(engine: Engine) -> None:
    with engine.begin() as connection:
        for model in (AnomalyRecord, StateSnapshot):
            connection.execute(delete(model).where(model.node_id.startswith(PREFIX)))
        for device_model in (PodError, PodReading, TelemetryEvent, Device):
            connection.execute(delete(device_model).where(device_model.device_id.startswith(PREFIX)))
