from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def append_jsonl(directory: str, name: str, payload: dict[str, Any]) -> None:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def monthly_name(prefix: str, ts: datetime) -> str:
    return f"{prefix}_{ts:%Y-%m}.jsonl"


def daily_name(prefix: str, ts: datetime) -> str:
    return f"{prefix}_{ts:%Y-%m-%d}.jsonl"
