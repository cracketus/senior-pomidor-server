from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Device, TelemetryEvent
from app.services import persist_telemetry_result
from app.validation import TELEMETRY_SCHEMA_V2


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA_V2,
        "record_id": "concurrent:pi-001:0001",
        "device_id": "pi-001",
        "timestamp_utc": "2026-08-19T12:00:00Z",
        "pods": {"pod-1": {"enabled": True, "metrics": {"soil_moisture_percent": 42.5}}},
    }


def test_concurrent_identical_record_id_has_one_accepted_one_duplicate_and_one_row(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    timestamp = datetime(2026, 8, 19, 12, tzinfo=UTC)
    with session_local() as db:
        db.add(
            Device(
                device_id="pi-001",
                first_seen_at=timestamp,
                last_seen_at=timestamp,
                last_payload_at=timestamp,
            )
        )
        db.commit()

    start = Barrier(2)

    def submit() -> str:
        with session_local() as db:
            start.wait()
            return persist_telemetry_result(db, telemetry_payload(), source="http").outcome

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = sorted(executor.map(lambda _index: submit(), range(2)))

        with session_local() as db:
            count = db.scalar(select(func.count()).select_from(TelemetryEvent))
        assert outcomes == ["accepted", "duplicate"]
        assert count == 1
    finally:
        engine.dispose()
