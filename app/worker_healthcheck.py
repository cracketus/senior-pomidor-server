from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from app.worker_health import worker_health_path

MAX_HEALTH_AGE_SECONDS = 90


def is_worker_healthy(now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    path = worker_health_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"].replace("Z", "+00:00"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    age_seconds = (now - updated_at).total_seconds()
    return payload.get("status") == "healthy" and 0 <= age_seconds <= MAX_HEALTH_AGE_SECONDS


def main() -> int:
    return 0 if is_worker_healthy() else 1


if __name__ == "__main__":
    sys.exit(main())
