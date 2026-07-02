from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Photo, TelemetryEvent


@dataclass(frozen=True)
class LifecycleCategory:
    name: str
    retention_days: int | None
    candidate_count: int
    candidate_bytes: int | None
    message: str


def cutoff(now: datetime, retention_days: int | None) -> datetime | None:
    if retention_days is None:
        return None
    return now - timedelta(days=retention_days)


def telemetry_candidates(db: Session, now: datetime, retention_days: int | None) -> LifecycleCategory:
    cutoff_at = cutoff(now, retention_days)
    if cutoff_at is None:
        return LifecycleCategory("telemetry", None, 0, None, "retention disabled")
    count = (
        db.scalar(select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.timestamp_utc < cutoff_at)) or 0
    )
    return LifecycleCategory("telemetry", retention_days, int(count), None, "dry-run only")


def photo_candidates(db: Session, now: datetime, retention_days: int | None) -> LifecycleCategory:
    cutoff_at = cutoff(now, retention_days)
    if cutoff_at is None:
        return LifecycleCategory("photos", None, 0, 0, "retention disabled")
    row = db.execute(
        select(func.count(Photo.photo_id), func.coalesce(func.sum(Photo.file_size_bytes), 0)).where(
            Photo.captured_at_utc < cutoff_at
        )
    ).one()
    return LifecycleCategory("photos", retention_days, int(row[0]), int(row[1]), "dry-run only")


def file_candidates(root: Path, name: str, now: datetime, retention_days: int | None) -> LifecycleCategory:
    cutoff_at = cutoff(now, retention_days)
    if retention_days is None:
        return LifecycleCategory(name, None, 0, 0, "retention disabled")
    if cutoff_at is None or not root.exists():
        return LifecycleCategory(name, retention_days, 0, 0, "path not found")
    count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if modified < cutoff_at:
            count += 1
            total_bytes += path.stat().st_size
    return LifecycleCategory(name, retention_days, count, total_bytes, "dry-run only")


def build_lifecycle_report(
    db: Session,
    *,
    now: datetime,
    telemetry_retention_days: int | None,
    photo_retention_days: int | None,
    grafana_data_dir: Path | None,
    grafana_retention_days: int | None,
    ai_output_dir: Path | None,
    ai_retention_days: int | None,
) -> dict[str, Any]:
    categories = [
        telemetry_candidates(db, now, telemetry_retention_days),
        photo_candidates(db, now, photo_retention_days),
    ]
    if grafana_data_dir is not None:
        categories.append(file_candidates(grafana_data_dir, "grafana", now, grafana_retention_days))
    if ai_output_dir is not None:
        categories.append(file_candidates(ai_output_dir, "ai_analysis", now, ai_retention_days))
    return {
        "mode": "dry_run",
        "generated_at_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "destructive_cleanup_enabled": False,
        "categories": [asdict(category) for category in categories],
    }


def parse_retention(value: str) -> int | None:
    if value.lower() in {"none", "disabled", "off"}:
        return None
    days = int(value)
    if days < 0:
        raise argparse.ArgumentTypeError("retention days must be non-negative")
    return days


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run Senior Pomidor data lifecycle inspection.")
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--telemetry-retention-days", type=parse_retention, default=180)
    parser.add_argument("--photo-retention-days", type=parse_retention, default=180)
    parser.add_argument("--grafana-data-dir")
    parser.add_argument("--grafana-retention-days", type=parse_retention, default=None)
    parser.add_argument("--ai-output-dir", default="data/ai-analysis")
    parser.add_argument("--ai-retention-days", type=parse_retention, default=180)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as db:
            report = build_lifecycle_report(
                db,
                now=datetime.now(UTC),
                telemetry_retention_days=args.telemetry_retention_days,
                photo_retention_days=args.photo_retention_days,
                grafana_data_dir=Path(args.grafana_data_dir) if args.grafana_data_dir else None,
                grafana_retention_days=args.grafana_retention_days,
                ai_output_dir=Path(args.ai_output_dir) if args.ai_output_dir else None,
                ai_retention_days=args.ai_retention_days,
            )
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
