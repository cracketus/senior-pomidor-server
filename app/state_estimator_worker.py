from __future__ import annotations

import logging
import signal
import sys
from threading import Event

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.models import Device
from app.state_estimator.config import load_estimator_runtime
from app.state_estimator.models import EstimatorHistory
from app.state_estimator.persistence import estimate_latest_from_telemetry
from app.worker_health import write_worker_health

configure_logging()
logger = logging.getLogger(__name__)
stop_event = Event()
histories: dict[str, EstimatorHistory] = {}


def run_once() -> int:
    with SessionLocal() as db:
        devices = db.scalars(select(Device).order_by(Device.device_id)).all()
        for device in devices:
            estimate_latest_from_telemetry(
                db,
                node_id=device.device_id,
                timezone=settings.state_estimator_timezone,
                private_log_dir=settings.state_estimator_private_log_dir,
                history=histories.setdefault(device.device_id, EstimatorHistory()),
                config_path=settings.state_estimator_config_path,
            )
        return len(devices)


def main() -> int:
    if not settings.state_estimator_enabled:
        write_worker_health("state_estimator_disabled")
        return 0

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    write_worker_health("state_estimator_starting")
    estimator_config, _calibration = load_estimator_runtime(
        settings.state_estimator_config_path,
        timezone=settings.state_estimator_timezone,
    )
    while not stop_event.is_set():
        try:
            count = run_once()
            write_worker_health("state_estimator_healthy", devices=count)
        except Exception:
            logger.exception("State estimator worker cycle failed")
            write_worker_health("state_estimator_failed")
        stop_event.wait(estimator_config.state_period_seconds)
    write_worker_health("state_estimator_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
