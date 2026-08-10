from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.agent_audit import aggregate_metrics, monthly_retrospective, validate_audit_record
from tools.agent_usage import make_usage_record

ROOT = Path(__file__).resolve().parents[1]


def records() -> list[dict]:
    names = ("2026-08-pilot-coder.json", "2026-08-pilot-reviewer.json")
    return [json.loads((ROOT / ".ai" / "agent-runs" / name).read_text(encoding="utf-8")) for name in names]


def test_pilot_records_validate_and_aggregate() -> None:
    result = aggregate_metrics(records())
    assert result["schema"] == "agent_metrics_v1"
    assert result["runs"] == 2
    assert result["report_completeness_rate"] == 1
    assert result["validation_results"]["NOT_RUN"] == 1


def test_unknown_field_and_sensitive_value_are_rejected() -> None:
    record = records()[0]
    record["raw_prompt"] = "private"
    with pytest.raises(ValueError, match="unknown fields"):
        validate_audit_record(record)
    record = records()[0]
    record["errors"] = [{"message": "secret value"}]
    with pytest.raises(ValueError, match="sensitive"):
        validate_audit_record(record)


def test_monthly_retrospective_is_deterministic() -> None:
    result = monthly_retrospective(records(), "2026-08")
    assert result == monthly_retrospective(records(), "2026-08")
    assert result["metrics"]["cycle_time_seconds_total"] == 900


def test_legacy_agent_usage_is_an_aggregate_source() -> None:
    legacy = make_usage_record(
        role="coder",
        file_count=1,
        input_characters=2,
        tool_output_bytes=3,
        model_tier="light",
        elapsed_seconds=4,
        escalation_reasons=["none"],
    )
    result = aggregate_metrics([], [legacy.__dict__])
    assert result["usage_totals"]["file_count"] == 1
