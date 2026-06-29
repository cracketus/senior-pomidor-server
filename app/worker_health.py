from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings


def worker_health_path() -> Path:
    return Path(settings.worker_health_file)


def write_worker_health(status: str, **details: Any) -> None:
    path = worker_health_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **details,
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
