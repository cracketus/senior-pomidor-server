from __future__ import annotations

import logging
import re
import signal
import sys
from datetime import UTC, date, datetime, time, timedelta
from threading import Event
from time import perf_counter
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.daily_story import (
    DailyStoryError,
    build_daily_story_context,
    build_environment_context,
    generate_story,
    load_environment_context,
    load_prompts,
    render_user_prompt,
)
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.models import DailyStoryRun
from app.ollama import OllamaClient
from app.worker_health import write_worker_health

configure_logging()
logger = logging.getLogger(__name__)
stop_event = Event()
SCHEDULE_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MAX_ERROR_CHARS = 1000


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_runtime_settings(config: Settings) -> tuple[time, ZoneInfo]:
    if not SCHEDULE_PATTERN.fullmatch(config.daily_story_schedule_time):
        raise DailyStoryError("DAILY_STORY_SCHEDULE_TIME must use HH:MM in 24-hour time")
    try:
        timezone = ZoneInfo(config.daily_story_timezone)
    except ZoneInfoNotFoundError as exc:
        raise DailyStoryError("DAILY_STORY_TIMEZONE must be a valid IANA timezone") from exc
    if config.daily_story_lookback_hours <= 0:
        raise DailyStoryError("DAILY_STORY_LOOKBACK_HOURS must be positive")
    if config.daily_story_poll_interval_seconds < 1:
        raise DailyStoryError("DAILY_STORY_POLL_INTERVAL_SECONDS must be positive")
    if config.daily_story_max_attempts < 1 or config.daily_story_ollama_request_retries < 1:
        raise DailyStoryError("Daily story retry limits must be at least one")
    if config.daily_story_retry_delay_minutes < 0 or config.daily_story_stale_after_minutes < 1:
        raise DailyStoryError("Daily story retry/stale intervals are invalid")
    if config.daily_story_memory_entries < 0:
        raise DailyStoryError("DAILY_STORY_MEMORY_ENTRIES must not be negative")
    if config.daily_story_max_environment_context_chars < 512:
        raise DailyStoryError("DAILY_STORY_MAX_ENVIRONMENT_CONTEXT_CHARS must be at least 512")
    hour, minute = (int(part) for part in config.daily_story_schedule_time.split(":"))
    return time(hour=hour, minute=minute), timezone


def scheduled_utc(story_date: date, schedule_time: time, timezone: ZoneInfo) -> datetime:
    local_naive = datetime.combine(story_date, schedule_time)
    candidate = local_naive.replace(tzinfo=timezone, fold=0)
    round_trip = candidate.astimezone(UTC).astimezone(timezone)
    if round_trip.replace(tzinfo=None) != local_naive:
        candidate = round_trip
    return candidate.astimezone(UTC)


def _insert_claim(db: Session, values: dict[str, object]) -> bool:
    dialect = db.get_bind().dialect.name
    table = cast(Any, DailyStoryRun.__table__)
    if dialect == "postgresql":
        statement: Any = (
            postgresql_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[table.c.node_id, table.c.story_date])
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[table.c.node_id, table.c.story_date])
        )
    else:
        raise DailyStoryError(f"Unsupported database dialect for daily story claims: {dialect}")
    result = cast(Any, db.execute(statement))
    return bool(result.rowcount)


def claim_due_run(db: Session, config: Settings, *, now: datetime | None = None) -> DailyStoryRun | None:
    schedule_time, timezone = validate_runtime_settings(config)
    now_utc = ensure_utc(now or datetime.now(UTC))
    story_date = now_utc.astimezone(timezone).date()
    due_at = scheduled_utc(story_date, schedule_time, timezone)
    if now_utc < due_at:
        return None
    values: dict[str, object] = {
        "node_id": config.daily_story_node_id,
        "story_date": story_date,
        "window_start_utc": due_at - timedelta(hours=config.daily_story_lookback_hours),
        "window_end_utc": due_at,
        "scheduled_at_utc": due_at,
        "started_at_utc": now_utc,
        "completed_at_utc": None,
        "status": "running",
        "attempt_count": 1,
        "story": None,
        "model": config.daily_story_ollama_model,
        "ollama_options_jsonb": config.daily_story_ollama_options_json,
        "system_prompt": None,
        "user_prompt": None,
        "environment_context_jsonb": None,
        "input_summary_jsonb": None,
        "runtime_metrics_jsonb": None,
        "error_details": None,
    }
    inserted = _insert_claim(db, values)
    db.commit()
    query = select(DailyStoryRun).where(
        DailyStoryRun.node_id == config.daily_story_node_id,
        DailyStoryRun.story_date == story_date,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    run = db.scalar(query)
    if run is None:
        raise DailyStoryError("Daily story claim disappeared")
    if inserted:
        return run
    if run.status in {"succeeded", "skipped_no_data"}:
        db.rollback()
        return None
    started = ensure_utc(run.started_at_utc)
    completed = ensure_utc(run.completed_at_utc) if run.completed_at_utc is not None else None
    if run.status == "running":
        stale_at = started + timedelta(minutes=config.daily_story_stale_after_minutes)
        if now_utc < stale_at:
            db.rollback()
            return None
    elif run.status == "failed":
        retry_at = (completed or started) + timedelta(minutes=config.daily_story_retry_delay_minutes)
        if now_utc < retry_at:
            db.rollback()
            return None
    if run.attempt_count >= config.daily_story_max_attempts:
        if run.status == "running":
            run.status = "failed"
            run.completed_at_utc = now_utc
            run.error_details = "Stale daily story run exhausted its retry limit"
            db.commit()
        else:
            db.rollback()
        return None
    run.status = "running"
    run.attempt_count += 1
    run.started_at_utc = now_utc
    run.completed_at_utc = None
    run.story = None
    run.error_details = None
    run.runtime_metrics_jsonb = None
    db.commit()
    return run


def process_run(
    db: Session,
    run: DailyStoryRun,
    config: Settings,
    *,
    client: OllamaClient,
    system_prompt: str,
    user_template: str,
    base_environment_context: dict[str, Any],
    now: datetime | None = None,
) -> DailyStoryRun:
    started = perf_counter()

    def completion_time() -> datetime:
        return ensure_utc(now or datetime.now(UTC))

    try:
        context = build_daily_story_context(
            db,
            node_id=run.node_id,
            window_start=run.window_start_utc,
            window_end=run.window_end_utc,
            max_chars=config.daily_story_max_context_chars,
        )
        environment_context = build_environment_context(
            db,
            node_id=run.node_id,
            story_date=run.story_date,
            base_context=base_environment_context,
            memory_entries=config.daily_story_memory_entries,
            max_chars=config.daily_story_max_environment_context_chars,
        )
        user_prompt = render_user_prompt(
            user_template,
            node_id=run.node_id,
            window_start=run.window_start_utc,
            window_end=run.window_end_utc,
            environment_context=environment_context,
            summary=context.summary,
        )
        run.system_prompt = system_prompt
        run.user_prompt = user_prompt
        run.environment_context_jsonb = environment_context
        run.input_summary_jsonb = context.summary
        run.ollama_options_jsonb = config.daily_story_ollama_options_json
        if context.telemetry_event_count == 0:
            run.status = "skipped_no_data"
            run.story = None
            run.completed_at_utc = completion_time()
            run.runtime_metrics_jsonb = {"elapsed_seconds": round(perf_counter() - started, 3), "ollama_called": False}
            db.commit()
            return run
        generated = generate_story(
            client,
            model=config.daily_story_ollama_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            options=config.daily_story_ollama_options_json,
            keep_alive=config.daily_story_ollama_keep_alive,
            retry_attempts=config.daily_story_ollama_request_retries,
        )
        run.status = "succeeded"
        run.story = generated.story
        run.completed_at_utc = completion_time()
        run.error_details = None
        run.runtime_metrics_jsonb = {
            "elapsed_seconds": round(perf_counter() - started, 3),
            "ollama_called": True,
            "request_attempts": generated.request_attempts,
            **generated.metrics,
        }
    except Exception as exc:
        logger.exception("Daily story run failed for node=%s date=%s", run.node_id, run.story_date)
        run.status = "failed"
        run.story = None
        run.completed_at_utc = completion_time()
        run.error_details = str(exc)[:MAX_ERROR_CHARS]
        run.runtime_metrics_jsonb = {"elapsed_seconds": round(perf_counter() - started, 3)}
    db.commit()
    return run


def run_cycle(
    db: Session,
    config: Settings,
    *,
    client: OllamaClient,
    system_prompt: str,
    user_template: str,
    base_environment_context: dict[str, Any],
    now: datetime | None = None,
) -> DailyStoryRun | None:
    run = claim_due_run(db, config, now=now)
    if run is None:
        return None
    return process_run(
        db,
        run,
        config,
        client=client,
        system_prompt=system_prompt,
        user_template=user_template,
        base_environment_context=base_environment_context,
        now=now,
    )


def main() -> int:
    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        validate_runtime_settings(settings)
        system_prompt, user_template = load_prompts(
            settings.daily_story_system_prompt_path, settings.daily_story_user_prompt_path
        )
        base_environment_context = load_environment_context(
            settings.daily_story_environment_context_path,
            settings.daily_story_max_environment_context_chars,
        )
        client = OllamaClient(
            host=settings.daily_story_ollama_host,
            timeout_seconds=settings.daily_story_ollama_timeout_seconds,
        )
    except Exception as exc:
        logger.exception("Daily story worker startup failed")
        write_worker_health("daily_story_failed", error=str(exc)[:MAX_ERROR_CHARS])
        return 1

    write_worker_health("daily_story_waiting")
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                run = run_cycle(
                    db,
                    settings,
                    client=client,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    base_environment_context=base_environment_context,
                )
            if run is None:
                write_worker_health("daily_story_waiting")
            else:
                write_worker_health(f"daily_story_{run.status}", run_id=run.id, story_date=run.story_date.isoformat())
        except Exception as exc:
            logger.exception("Daily story worker cycle failed")
            write_worker_health("daily_story_failed", error=str(exc)[:MAX_ERROR_CHARS])
        stop_event.wait(settings.daily_story_poll_interval_seconds)
    write_worker_health("daily_story_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
