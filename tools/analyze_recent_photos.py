from __future__ import annotations

from argparse import ArgumentParser
from datetime import timedelta
from pathlib import Path
from typing import Sequence
import json
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_analysis import (  # noqa: E402
    DEFAULT_AI_ANALYSIS_MODEL,
    DEFAULT_AI_ANALYSIS_OUTPUT,
    DEFAULT_OLLAMA_HOST,
    OllamaVisionAnalyzer,
    analyze_contexts,
    build_prompt_inputs,
    select_photo_contexts,
)
from app.config import Settings  # noqa: E402


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise ValueError("must be non-negative")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError("must be at least 1")
    return parsed


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run offline VLM analysis over stored Senior Pomidor photos.")
    parser.add_argument("--database-url", default=None, help="Database URL. Defaults to DATABASE_URL/.env settings.")
    parser.add_argument("--device-id", default=None, help="Only analyze photos for this device.")
    parser.add_argument("--limit", type=positive_int, default=5, help="Maximum recent photos to analyze.")
    parser.add_argument("--since-hours", type=non_negative_float, default=None, help="Only include recent photos.")
    parser.add_argument(
        "--telemetry-window-minutes",
        type=non_negative_float,
        default=30.0,
        help="Match telemetry within this many minutes before and after each photo.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AI_ANALYSIS_MODEL", DEFAULT_AI_ANALYSIS_MODEL),
        help="Local Ollama vision model name.",
    )
    parser.add_argument(
        "--ollama-host",
        default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        help="Ollama HTTP host.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=non_negative_float,
        default=120.0,
        help="Per-photo Ollama request timeout.",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("AI_ANALYSIS_OUTPUT", DEFAULT_AI_ANALYSIS_OUTPUT),
        help="JSONL output path. Records are appended.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print selected inputs without calling Ollama.")
    return parser


def dry_run_payload(contexts: Sequence) -> dict:
    return {
        "count": len(contexts),
        "photos": [
            {
                "photo_id": context.photo.photo_id,
                "device_id": context.photo.device_id,
                "storage_path": context.photo.storage_path,
                "telemetry_event_ids": [event.id for event in context.telemetry_events],
                "prompt_inputs": build_prompt_inputs(context),
            }
            for context in contexts
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or Settings().database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as db:
        contexts = select_photo_contexts(
            db,
            limit=args.limit,
            device_id=args.device_id,
            since_hours=args.since_hours,
            telemetry_window=timedelta(minutes=args.telemetry_window_minutes),
        )
        if args.dry_run:
            print(json.dumps(dry_run_payload(contexts), indent=2, sort_keys=True))
            return 0
        if not contexts:
            print("No photos matched the selection.")
            return 0

        analyzer = OllamaVisionAnalyzer(
            model=args.model,
            host=args.ollama_host,
            timeout_seconds=args.timeout_seconds,
        )
        output_path = Path(args.output)
        records = analyze_contexts(
            contexts,
            analyzer,
            output_path=output_path,
            model=args.model,
            ollama_host=args.ollama_host,
        )

    failures = sum(1 for record in records if record["error"])
    successes = len(records) - failures
    print(f"Wrote {len(records)} record(s) to {output_path} ({successes} succeeded, {failures} failed).")
    return 1 if records and failures == len(records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
