from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.agent_usage import make_usage_record, record_usage, validate_usage_payload


def valid_record():
    return make_usage_record(
        role="coder",
        file_count=3,
        input_characters=15000,
        tool_output_bytes=2048,
        model_tier="medium",
        elapsed_seconds=12.5,
        escalation_reasons=["none"],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )


def test_usage_record_contains_only_allowlisted_metadata(tmp_path: Path) -> None:
    target = record_usage(valid_record(), root=tmp_path)
    payload = json.loads(target.read_text(encoding="utf-8"))

    validate_usage_payload(payload)
    assert set(payload) == {
        "schema",
        "recorded_at_utc",
        "role",
        "file_count",
        "input_characters",
        "tool_output_bytes",
        "model_tier",
        "elapsed_seconds",
        "escalation_reasons",
    }
    assert not any(term in json.dumps(payload).casefold() for term in ("prompt", "content", "secret", "environment"))
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_usage_payload_rejects_unknown_sensitive_field() -> None:
    payload = valid_record().__dict__.copy()
    payload["prompt"] = "must never be persisted"

    with pytest.raises(ValueError, match="missing or unknown"):
        validate_usage_payload(payload)


@pytest.mark.parametrize("field", ["file_count", "input_characters", "tool_output_bytes", "elapsed_seconds"])
def test_usage_record_rejects_negative_metrics(field: str) -> None:
    arguments = {
        "role": "reviewer",
        "file_count": 1,
        "input_characters": 1,
        "tool_output_bytes": 1,
        "model_tier": "strong",
        "elapsed_seconds": 1.0,
        "escalation_reasons": ["high_risk_flag"],
    }
    arguments[field] = -1

    with pytest.raises(ValueError, match="non-negative"):
        make_usage_record(**arguments)


def test_usage_record_rejects_unknown_escalation_reason() -> None:
    with pytest.raises(ValueError, match="Unknown escalation reason"):
        make_usage_record(
            role="planner",
            file_count=1,
            input_characters=1,
            tool_output_bytes=1,
            model_tier="light",
            elapsed_seconds=1,
            escalation_reasons=["free-form-private-detail"],
        )


def test_usage_output_cannot_escape_repository_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository root"):
        record_usage(valid_record(), output=Path("..") / "usage.jsonl", root=tmp_path)
