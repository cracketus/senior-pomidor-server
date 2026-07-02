from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Device, Photo, TelemetryEvent
from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA
from tools.lifecycle import build_lifecycle_report


def test_lifecycle_report_counts_dry_run_candidates(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    old = now - timedelta(days=200)
    recent = now - timedelta(days=2)
    ai_dir = tmp_path / "ai"
    ai_dir.mkdir()
    old_ai_file = ai_dir / "old.jsonl"
    old_ai_file.write_text("old", encoding="utf-8")
    old_timestamp = (now - timedelta(days=200)).timestamp()
    old_ai_file.touch()

    with SessionLocal() as db:
        db.add(Device(device_id="pi-001", first_seen_at=old, last_seen_at=recent, last_payload_at=recent))
        db.add_all(
            [
                TelemetryEvent(
                    device_id="pi-001",
                    timestamp_utc=old,
                    schema_version=TELEMETRY_SCHEMA,
                    source="http",
                    raw_payload_jsonb={},
                    system_health_jsonb=None,
                    received_at=old,
                ),
                TelemetryEvent(
                    device_id="pi-001",
                    timestamp_utc=recent,
                    schema_version=TELEMETRY_SCHEMA,
                    source="http",
                    raw_payload_jsonb={},
                    system_health_jsonb=None,
                    received_at=recent,
                ),
                Photo(
                    photo_id="old-photo",
                    device_id="pi-001",
                    captured_at_utc=old,
                    schema_version=PHOTO_SCHEMA,
                    sharpness_score=None,
                    content_type="image/jpeg",
                    file_size_bytes=123,
                    storage_path="old.jpg",
                    sha256="0" * 64,
                    received_at=old,
                ),
                Photo(
                    photo_id="recent-photo",
                    device_id="pi-001",
                    captured_at_utc=recent,
                    schema_version=PHOTO_SCHEMA,
                    sharpness_score=None,
                    content_type="image/jpeg",
                    file_size_bytes=456,
                    storage_path="recent.jpg",
                    sha256="1" * 64,
                    received_at=recent,
                ),
            ]
        )
        db.commit()
        old_ai_file.touch()
        import os

        os.utime(old_ai_file, (old_timestamp, old_timestamp))

        report = build_lifecycle_report(
            db,
            now=now,
            telemetry_retention_days=180,
            photo_retention_days=180,
            grafana_data_dir=None,
            grafana_retention_days=None,
            ai_output_dir=ai_dir,
            ai_retention_days=180,
        )

    engine.dispose()
    categories = {category["name"]: category for category in report["categories"]}
    assert report["mode"] == "dry_run"
    assert report["destructive_cleanup_enabled"] is False
    assert categories["telemetry"]["candidate_count"] == 1
    assert categories["photos"]["candidate_count"] == 1
    assert categories["photos"]["candidate_bytes"] == 123
    assert categories["ai_analysis"]["candidate_count"] == 1
