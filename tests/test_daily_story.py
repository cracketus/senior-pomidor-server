import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.daily_story import DailyStoryError, build_daily_story_context, generate_story, load_prompts, render_user_prompt
from app.daily_story_worker import claim_due_run, process_run, scheduled_utc
from app.db import get_db
from app.main import app
from app.models import AnomalyRecord, Base, DailyStoryRun, SensorHealthSnapshot
from app.ollama import OllamaError, OllamaResponse
from app.services import persist_telemetry
from app.validation import TELEMETRY_SCHEMA_V2


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        with SessionLocal() as db:
            yield db
    finally:
        engine.dispose()


def telemetry_payload(node_id: str, timestamp: datetime, moisture: float) -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA_V2,
        "device_id": node_id,
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "pods": {
            "pod-1": {
                "enabled": True,
                "soil_moisture_percent": moisture,
                "air_temperature_c": 22.0,
                "errors": [{"sensor": "soil", "message": "intermittent"}],
            }
        },
        "system_health": {
            "rpi_core": {"cpu_temp_c": 80.0},
            "errors": [{"sensor": "network", "message": "probe failed"}],
        },
    }


def settings(**overrides) -> Settings:
    values = {
        "daily_story_node_id": "pi-001",
        "daily_story_schedule_time": "09:00",
        "daily_story_timezone": "Europe/Vienna",
        "daily_story_lookback_hours": 24,
        "daily_story_max_attempts": 3,
        "daily_story_retry_delay_minutes": 15,
        "daily_story_stale_after_minutes": 15,
        "daily_story_ollama_request_retries": 1,
    }
    values.update(overrides)
    return Settings(**values)


def test_model_enforces_unique_node_date_and_story_status(db_session) -> None:
    now = datetime(2026, 7, 15, 7, 0, tzinfo=UTC)
    first = DailyStoryRun(
        node_id="pi-001",
        story_date=date(2026, 7, 15),
        window_start_utc=now - timedelta(days=1),
        window_end_utc=now,
        scheduled_at_utc=now,
        started_at_utc=now,
        completed_at_utc=now,
        status="succeeded",
        attempt_count=1,
        story="I grew steadily today.",
        model="test",
        ollama_options_jsonb={},
    )
    db_session.add(first)
    db_session.commit()
    duplicate = DailyStoryRun(
        node_id=first.node_id,
        story_date=first.story_date,
        window_start_utc=first.window_start_utc,
        window_end_utc=first.window_end_utc,
        scheduled_at_utc=first.scheduled_at_utc,
        started_at_utc=first.started_at_utc,
        status="running",
        attempt_count=1,
        model="test",
        ollama_options_jsonb={},
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_context_filters_exact_node_window_and_summarizes_health(db_session) -> None:
    start = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)
    end = datetime(2026, 7, 15, 7, 0, tzinfo=UTC)
    persist_telemetry(db_session, telemetry_payload("pi-001", start, 40), source="test")
    persist_telemetry(db_session, telemetry_payload("pi-001", start + timedelta(hours=1), 46), source="test")
    persist_telemetry(db_session, telemetry_payload("pi-001", end, 99), source="test")
    persist_telemetry(db_session, telemetry_payload("pi-002", start + timedelta(minutes=30), 1), source="test")
    db_session.add_all(
        [
            AnomalyRecord(
                anomaly_id="a1",
                node_id="pi-001",
                type="HIGH_HEAT",
                status="ACTIVE",
                severity="HIGH",
                ts=start + timedelta(minutes=5),
                state_id=None,
                payload_jsonb={},
            ),
            AnomalyRecord(
                anomaly_id="a2",
                node_id="pi-001",
                type="HIGH_HEAT",
                status="CLEARED",
                severity="HIGH",
                ts=start + timedelta(minutes=10),
                state_id=None,
                payload_jsonb={},
            ),
            AnomalyRecord(
                anomaly_id="other",
                node_id="pi-002",
                type="LEAK",
                status="ACTIVE",
                severity="HIGH",
                ts=start + timedelta(minutes=10),
                state_id=None,
                payload_jsonb={},
            ),
            SensorHealthSnapshot(
                health_id="h1",
                node_id="pi-001",
                ts=start + timedelta(minutes=1),
                payload_jsonb={"overall_status": "OK", "sensors": [{"sensor_id": "soil", "status": "OK"}]},
            ),
            SensorHealthSnapshot(
                health_id="h2",
                node_id="pi-001",
                ts=start + timedelta(minutes=2),
                payload_jsonb={"overall_status": "WARN", "sensors": [{"sensor_id": "soil", "status": "STALE"}]},
            ),
        ]
    )
    db_session.commit()

    context = build_daily_story_context(
        db_session, node_id="pi-001", window_start=start, window_end=end, max_chars=10_000
    )

    assert context.telemetry_event_count == 2
    assert context.summary["node_id"] == "pi-001"
    moisture = context.summary["pods"]["pod-1"]["soil_moisture_percent"]
    assert moisture == {
        "count": 2,
        "min": 40.0,
        "max": 46.0,
        "average": 43.0,
        "first": 40.0,
        "last": 46.0,
        "change": 6.0,
    }
    assert {(item["status"], item["count"]) for item in context.summary["anomalies"]} == {
        ("ACTIVE", 1),
        ("CLEARED", 1),
    }
    assert context.summary["sensor_health"]["sensors"]["soil"]["latest_status"] == "STALE"
    assert context.summary["sensor_health"]["sensors"]["soil"]["changes"][0]["from"] == "OK"
    assert context.summary["errors"]["system_health"][0]["count"] == 2
    assert "pi-002" not in json.dumps(context.summary)


def test_context_is_bounded_and_empty_window_does_not_claim_other_node(db_session) -> None:
    start = datetime(2026, 7, 14, tzinfo=UTC)
    context = build_daily_story_context(
        db_session, node_id="pi-001", window_start=start, window_end=start + timedelta(days=1), max_chars=512
    )
    assert context.telemetry_event_count == 0
    assert len(json.dumps(context.summary, separators=(",", ":"), sort_keys=True)) <= 512


class FakeClient:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return OllamaResponse(text=result, metrics={"eval_count": 10})


def test_generation_retries_validation_and_sends_schema_options_and_keep_alive() -> None:
    client = FakeClient(
        [
            "not-json",
            json.dumps({"story": "x" * 281}),
            json.dumps({"story": "I am thriving today!"}),
        ]
    )
    result = generate_story(
        client,
        model="llama3.2:3b",
        system_prompt="system",
        user_prompt="user",
        options={"seed": 42},
        keep_alive="0",
        retry_attempts=3,
    )
    assert result.story == "I am thriving today!"
    assert result.request_attempts == 3
    assert client.calls[0]["format_schema"]["properties"]["story"]["maxLength"] == 280
    assert client.calls[0]["options"] == {"seed": 42}
    assert client.calls[0]["keep_alive"] == "0"


def test_generation_does_not_retry_permanent_http_error() -> None:
    client = FakeClient([OllamaError("bad request", retryable=False)])
    with pytest.raises(DailyStoryError, match="bad request"):
        generate_story(
            client,
            model="test",
            system_prompt="system",
            user_prompt="user",
            options={},
            keep_alive="0",
            retry_attempts=3,
        )
    assert len(client.calls) == 1


def test_prompt_files_require_tokens_and_render_deterministically(tmp_path) -> None:
    system_path = tmp_path / "system.txt"
    user_path = tmp_path / "user.txt"
    system_path.write_text("system", encoding="utf-8")
    user_path.write_text("{{NODE_ID}} {{WINDOW_START_UTC}} {{WINDOW_END_UTC}} {{CONTEXT_JSON}}", encoding="utf-8")
    system_prompt, template = load_prompts(str(system_path), str(user_path))
    rendered = render_user_prompt(
        template,
        node_id="pi-001",
        window_start=datetime(2026, 7, 14, tzinfo=UTC),
        window_end=datetime(2026, 7, 15, tzinfo=UTC),
        summary={"b": 2, "a": 1},
    )
    assert system_prompt == "system"
    assert rendered.endswith('{"a":1,"b":2}')
    user_path.write_text("missing tokens", encoding="utf-8")
    with pytest.raises(DailyStoryError, match="missing required tokens"):
        load_prompts(str(system_path), str(user_path))


def test_scheduler_runs_today_only_skips_no_data_and_prevents_duplicate(db_session) -> None:
    config = settings()
    assert claim_due_run(db_session, config, now=datetime(2026, 7, 15, 6, 59, tzinfo=UTC)) is None
    now = datetime(2026, 7, 15, 7, 1, tzinfo=UTC)
    run = claim_due_run(db_session, config, now=now)
    assert run is not None
    assert run.story_date == date(2026, 7, 15)
    client = FakeClient([])
    processed = process_run(
        db_session,
        run,
        config,
        client=client,
        system_prompt="system",
        user_template="{{NODE_ID}} {{WINDOW_START_UTC}} {{WINDOW_END_UTC}} {{CONTEXT_JSON}}",
        now=now,
    )
    assert processed.status == "skipped_no_data"
    assert processed.story is None
    assert client.calls == []
    assert claim_due_run(db_session, config, now=now + timedelta(hours=1)) is None
    assert len(db_session.scalars(select(DailyStoryRun)).all()) == 1


def test_scheduler_recovers_stale_running_row_in_place(db_session) -> None:
    config = settings()
    first_now = datetime(2026, 7, 15, 7, 1, tzinfo=UTC)
    first = claim_due_run(db_session, config, now=first_now)
    assert first is not None
    assert claim_due_run(db_session, config, now=first_now + timedelta(minutes=14)) is None
    recovered = claim_due_run(db_session, config, now=first_now + timedelta(minutes=16))
    assert recovered is not None
    assert recovered.id == first.id
    assert recovered.attempt_count == 2


def test_schedule_handles_dst_ambiguity_and_nonexistent_time() -> None:
    timezone = ZoneInfo("Europe/Vienna")
    assert scheduled_utc(date(2026, 10, 25), time(2, 30), timezone) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert scheduled_utc(date(2026, 3, 29), time(2, 30), timezone) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)


def test_daily_story_api_filters_and_excludes_private_fields(client) -> None:
    override = app.dependency_overrides[get_db]
    generator = override()
    db = next(generator)
    now = datetime(2026, 7, 15, 7, 0, tzinfo=UTC)
    try:
        for index, node_id in enumerate(("pi-001", "pi-001", "pi-002"), start=1):
            db.add(
                DailyStoryRun(
                    node_id=node_id,
                    story_date=date(2026, 7, 13 + index),
                    window_start_utc=now - timedelta(days=1),
                    window_end_utc=now,
                    scheduled_at_utc=now,
                    started_at_utc=now,
                    completed_at_utc=now,
                    status="succeeded",
                    attempt_count=1,
                    story=f"story {index}",
                    model="test-model",
                    ollama_options_jsonb={"seed": 1},
                    system_prompt="private",
                    user_prompt="private",
                    input_summary_jsonb={"private": True},
                    error_details=None,
                )
            )
        db.commit()
    finally:
        generator.close()

    latest = client.get("/api/v1/daily-stories/latest?node_id=pi-001")
    assert latest.status_code == 200
    assert latest.json()["story"] == "story 2"
    assert set(latest.json()) == {
        "run_id",
        "node_id",
        "story_date",
        "window_start_utc",
        "window_end_utc",
        "status",
        "story",
        "model",
        "generated_at_utc",
    }
    ranged = client.get("/api/v1/daily-stories/range?node_id=pi-001&from=2026-07-15&limit=1")
    assert ranged.status_code == 200
    assert [item["story"] for item in ranged.json()] == ["story 2"]
    assert client.get("/api/v1/daily-stories/latest?node_id=missing").status_code == 404
    assert client.get("/api/v1/daily-stories/range?node_id=missing").status_code == 404
