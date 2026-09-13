from __future__ import annotations

import json
import os
import tempfile
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
    content = json.dumps(payload, sort_keys=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
