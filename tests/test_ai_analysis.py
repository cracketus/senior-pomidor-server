from datetime import UTC, datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai_analysis import (
    analyze_contexts,
    build_prompt_inputs,
    render_prompt,
    select_photo_contexts,
)
from app.models import Base
from app.services import persist_photo, persist_telemetry
from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2
from tools.analyze_recent_photos import main as analyze_recent_photos_main


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with SessionLocal() as db:
        yield db


def telemetry_payload(
    *,
    device_id: str = "pi-001",
    timestamp: str = "2026-06-07T12:00:00Z",
    schema_version: str = TELEMETRY_SCHEMA,
) -> dict:
    payload = {
        "schema_version": schema_version,
        "device_id": device_id,
        "timestamp_utc": timestamp,
        "pods": {
            "pod-1": {
                "enabled": True,
                "soil_moisture_percent": 42.5,
                "leaf_temp_c": 21.2,
                "battery_mv": 5010,
                "errors": [{"sensor": "soil", "message": "intermittent"}],
            }
        },
    }
    if schema_version == TELEMETRY_SCHEMA_V2:
        payload["system_health"] = {
            "rpi_core": {
                "cpu_temp_c": 56.4,
                "wifi_rssi_dbm": -68.0,
                "disk_usage_percent": 34.2,
                "io_wait_percent": 1.7,
            },
            "errors": [],
        }
    return payload


def seed_photo(
    db,
    tmp_path,
    *,
    photo_id: str = "photo-1",
    device_id: str = "pi-001",
    captured_at_utc: str = "2026-06-07T12:05:00Z",
):
    photo, _created = persist_photo(
        db,
        photo_id=photo_id,
        device_id=device_id,
        captured_at_utc=captured_at_utc,
        schema_version=PHOTO_SCHEMA,
        sharpness_score=0.91,
        content_type="image/jpeg",
        content=b"\xff\xd8fake-jpeg\xff\xd9",
        storage_dir=str(tmp_path / "photos"),
    )
    return photo


def test_select_photo_contexts_matches_nearby_telemetry(db_session, tmp_path):
    inside = persist_telemetry(db_session, telemetry_payload(timestamp="2026-06-07T12:00:00Z"), source="test")
    persist_telemetry(db_session, telemetry_payload(timestamp="2026-06-07T11:40:00Z"), source="test")
    persist_telemetry(
        db_session,
        telemetry_payload(device_id="pi-002", timestamp="2026-06-07T12:04:00Z"),
        source="test",
    )
    seed_photo(db_session, tmp_path, photo_id="old-photo", captured_at_utc="2026-06-07T10:00:00Z")
    seed_photo(db_session, tmp_path, photo_id="photo-1", captured_at_utc="2026-06-07T12:05:00Z")

    contexts = select_photo_contexts(
        db_session,
        limit=5,
        device_id="pi-001",
        since_hours=1,
        telemetry_window=timedelta(minutes=10),
        now=datetime(2026, 6, 7, 12, 30, tzinfo=UTC),
    )

    assert [context.photo.photo_id for context in contexts] == ["photo-1"]
    assert [event.id for event in contexts[0].telemetry_events] == [inside.id]


def test_prompt_inputs_include_photo_and_telemetry_summary(db_session, tmp_path):
    persist_telemetry(
        db_session,
        telemetry_payload(schema_version=TELEMETRY_SCHEMA_V2),
        source="test",
    )
    seed_photo(db_session, tmp_path)
    context = select_photo_contexts(db_session, limit=1, telemetry_window=timedelta(minutes=30))[0]

    prompt_inputs = build_prompt_inputs(context)
    prompt = render_prompt(prompt_inputs)

    assert prompt_inputs["photo"]["photo_id"] == "photo-1"
    reading = prompt_inputs["telemetry"][0]["readings"][0]
    assert reading["metrics"]["soil_moisture_percent"] == 42.5
    assert reading["metrics"]["battery_mv"] == 5010.0
    assert prompt_inputs["telemetry"][0]["errors"][0]["message"] == "intermittent"
    assert prompt_inputs["telemetry"][0]["system_health"]["rpi_core"]["cpu_temp_c"] == 56.4
    assert "telemetry_correlations" in prompt


class FakeAnalyzer:
    def analyze(self, image_path, prompt: str) -> str:
        assert image_path.is_file()
        if "photo-fail" in prompt:
            raise RuntimeError("model unavailable")
        return '{"visible_condition":"ok"}'


def test_analyze_contexts_writes_jsonl_success_and_failure(db_session, tmp_path):
    persist_telemetry(db_session, telemetry_payload(), source="test")
    seed_photo(db_session, tmp_path, photo_id="photo-ok")
    seed_photo(db_session, tmp_path, photo_id="photo-fail", captured_at_utc="2026-06-07T12:06:00Z")
    contexts = select_photo_contexts(db_session, limit=2, telemetry_window=timedelta(minutes=30))
    output_path = tmp_path / "results.jsonl"

    records = analyze_contexts(
        contexts,
        FakeAnalyzer(),
        output_path=output_path,
        model="fake-vision",
        ollama_host="http://localhost:11434",
        analyzed_at=datetime(2026, 6, 7, 13, 0, tzinfo=UTC),
    )

    written = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert records == written
    assert len(written) == 2
    success = next(record for record in written if record["photo_id"] == "photo-ok")
    failure = next(record for record in written if record["photo_id"] == "photo-fail")
    assert success["analysis"] == '{"visible_condition":"ok"}'
    assert success["error"] is None
    assert failure["analysis"] is None
    assert failure["error"] == "model unavailable"


def test_cli_dry_run_prints_selected_inputs(tmp_path, capsys):
    db_path = tmp_path / "analysis.sqlite"
    database_url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with SessionLocal() as db:
        persist_telemetry(db, telemetry_payload(), source="test")
        seed_photo(db, tmp_path, photo_id="photo-cli")

    exit_code = analyze_recent_photos_main(["--database-url", database_url, "--dry-run", "--limit", "1"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["count"] == 1
    assert output["photos"][0]["photo_id"] == "photo-cli"
    assert output["photos"][0]["prompt_inputs"]["telemetry"][0]["readings"][0]["pod_key"] == "pod-1"
