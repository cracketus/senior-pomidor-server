from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.device_lifecycle import set_device_lifecycle, show_device_lifecycle
from app.models import (
    AnomalyRecord,
    Base,
    Device,
    DeviceLifecycleEvent,
    DeviceLifecycleState,
    StateSnapshot,
    TelemetryEvent,
)
from app.operator_summary import OperatorSummaryService
from app.services import persist_telemetry
from app.state_estimator.persistence import latest_state_or_estimate
from app.validation import ValidationError
from tools.lifecycle import parse_admin_args


def make_db() -> tuple[Engine, Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_lifecycle_show_does_not_require_expected_state() -> None:
    args = parse_admin_args(["show", "pi-001"])

    assert args.expected_state is None


def test_lifecycle_transition_is_guarded_audited_and_idempotent() -> None:
    engine, db = make_db()
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    db.add(Device(device_id="pi-001", first_seen_at=now, last_seen_at=now, last_payload_at=now))
    db.commit()

    lifecycle_call = cast(Callable[..., dict[str, object]], set_device_lifecycle)
    with pytest.raises(TypeError):
        lifecycle_call(db, device_id="pi-001", target_state="DECOMMISSIONED", reason_code="retired", apply=False)
    with pytest.raises(ValidationError, match="--apply"):
        set_device_lifecycle(
            db,
            device_id="pi-001",
            target_state="DECOMMISSIONED",
            reason_code="retired",
            expected_state="ACTIVE",
            apply=False,
        )
    changed = set_device_lifecycle(
        db,
        device_id="pi-001",
        target_state=DeviceLifecycleState.DECOMMISSIONED,
        expected_state="ACTIVE",
        reason_code="retired",
        apply=True,
        changed_at=now,
    )
    repeated = set_device_lifecycle(
        db,
        device_id="pi-001",
        target_state="DECOMMISSIONED",
        expected_state="DECOMMISSIONED",
        reason_code="retired_again",
        apply=True,
    )

    assert changed["changed"] is True
    assert repeated["changed"] is False
    assert db.scalar(select(DeviceLifecycleEvent.id)) is not None
    assert len(db.scalars(select(DeviceLifecycleEvent)).all()) == 1
    report = show_device_lifecycle(db, "pi-001")
    assert report["state"] == "DECOMMISSIONED"
    assert report["changed_at"] == "2026-09-13T12:00:00Z"
    events = cast(list[dict[str, object]], report["events"])
    assert events[0]["changed_at"] == "2026-09-13T12:00:00Z"
    db.close()
    engine.dispose()


def test_decommissioned_ingress_is_retained_without_reactivation() -> None:
    engine, db = make_db()
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    db.add(
        Device(
            device_id="pi-001",
            first_seen_at=now,
            last_seen_at=now,
            last_payload_at=now,
            lifecycle_state="DECOMMISSIONED",
        )
    )
    db.commit()
    persist_telemetry(
        db,
        {
            "schema_version": "senior-pomidor.edge.telemetry.v2",
            "device_id": "pi-001",
            "timestamp_utc": "2026-09-13T12:01:00Z",
            "pods": {},
        },
        "mqtt",
    )
    device = db.get(Device, "pi-001")
    assert device is not None
    assert device.lifecycle_state == "DECOMMISSIONED"
    assert db.scalar(select(TelemetryEvent).where(TelemetryEvent.device_id == "pi-001")) is not None
    db.close()
    engine.dispose()


def test_database_rejects_unknown_lifecycle_state() -> None:
    engine, db = make_db()
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    db.add(
        Device(
            device_id="pi-invalid",
            first_seen_at=now,
            last_seen_at=now,
            last_payload_at=now,
            lifecycle_state="UNKNOWN",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()
    engine.dispose()


def test_targeted_operator_anomaly_history_remains_readable() -> None:
    engine, db = make_db()
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    db.add(
        Device(
            device_id="pi-retired",
            first_seen_at=now,
            last_seen_at=now,
            last_payload_at=now,
            lifecycle_state="DECOMMISSIONED",
        )
    )
    db.add(
        AnomalyRecord(
            anomaly_id="anomaly-retired",
            node_id="pi-retired",
            type="LOW_STATE_CONFIDENCE",
            status="CLEARED",
            severity="WARN",
            ts=now,
            state_id=None,
            payload_jsonb={},
        )
    )
    db.commit()

    targeted, _ = OperatorSummaryService(db, now=lambda: now).anomalies(node_id="pi-retired", since_hours=24, limit=100)
    aggregate, _ = OperatorSummaryService(db, now=lambda: now).anomalies(node_id=None, since_hours=24, limit=100)

    assert [item.node_id for item in targeted] == ["pi-retired"]
    assert aggregate == []
    db.close()
    engine.dispose()


def test_decommissioned_device_keeps_latest_persisted_state() -> None:
    engine, db = make_db()
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    db.add(
        Device(
            device_id="pi-retired-state",
            first_seen_at=now,
            last_seen_at=now,
            last_payload_at=now,
            lifecycle_state="DECOMMISSIONED",
        )
    )
    payload = {"state_id": "state-retained", "node_id": "pi-retired-state"}
    db.add(
        StateSnapshot(
            state_id="state-retained",
            node_id="pi-retired-state",
            ts=now,
            generated_at=now,
            payload_jsonb=payload,
        )
    )
    db.commit()

    assert latest_state_or_estimate(db, node_id="pi-retired-state", timezone="Europe/Vienna") == payload
    db.close()
    engine.dispose()
