"""Replay actual persisted observations through the production estimator and storage.

Observation time drives the deterministic warning-duration policy; no wall-clock
sleep or altered thresholds. Transport/persistence has already run before this step.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models import TelemetryEvent
from app.state_estimator.adapters import observations_from_event
from app.state_estimator.config import load_estimator_runtime
from app.state_estimator.estimator import estimate_state
from app.state_estimator.models import EstimatorContext, EstimatorHistory
from app.state_estimator.persistence import persist_estimator_result

config, calibration = load_estimator_runtime()
history = EstimatorHistory()
with SessionLocal() as db:
    events = db.scalars(
        select(TelemetryEvent)
        .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
        .where(TelemetryEvent.device_id == "edge-staging-cross-repo")
        .order_by(TelemetryEvent.timestamp_utc)
    ).all()
    for event in events:
        result = estimate_state(
            observations_from_event(event),
            context=EstimatorContext(node_id=event.device_id),
            config=config,
            calibration=calibration,
            history=history,
        )
        persist_estimator_result(db, result)
