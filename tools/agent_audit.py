"""Validate and aggregate bounded, public agent-run audit artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.agent_usage import validate_usage_payload

SCHEMA = "agent_run_v1"
STATUSES = {"planned", "completed", "blocked", "failed", "cancelled"}
ROLES = {"planner", "coder", "reviewer"}
RESULT_STATUSES = {"PASS", "FAIL", "NOT_RUN"}
FIELDS = {
    "schema",
    "run_id",
    "issue_ref",
    "pr_ref",
    "role",
    "agent_id",
    "prompt_version",
    "started_at_utc",
    "finished_at_utc",
    "input_refs",
    "output_refs",
    "status",
    "commands",
    "validation_results",
    "human_edits",
    "findings",
    "errors",
    "usage",
}
SENSITIVE = re.compile(r"(?i)(prompt|secret|token|password|private[_ -]?key|environment|payload|ssh://|https?://)")
REF_RE = re.compile(r"^(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+(?::[0-9]+)?$")


def _string(value: Any, name: str, *, max_length: int = 240) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length or "\n" in value:
        raise ValueError(f"{name} must be a bounded single-line string")
    return value


def _utc(value: Any, name: str) -> datetime:
    text = _string(value, name, max_length=40)
    if not text.endswith("Z"):
        raise ValueError(f"{name} must be UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if parsed.tzinfo != UTC:
        raise ValueError(f"{name} must be UTC")
    return parsed


def _refs(value: Any, name: str) -> None:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError(f"{name} must be a bounded list")
    for item in value:
        ref = _string(item, name, max_length=180)
        if ref.startswith("/") or ".." in Path(ref).parts or not REF_RE.fullmatch(ref):
            raise ValueError(f"{name} contains an invalid repository reference")


def _safe_list(value: Any, name: str, *, limit: int = 64) -> None:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name} must be a bounded list")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{name} entries must be objects")
        if any(not isinstance(key, str) or SENSITIVE.search(key) for key in item):
            raise ValueError(f"{name} contains a sensitive or invalid field")
        if any(isinstance(v, str) and (len(v) > 240 or SENSITIVE.search(v)) for v in item.values()):
            raise ValueError(f"{name} contains sensitive or unbounded text")


def validate_audit_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("audit record contains missing or unknown fields")
    if record["schema"] != SCHEMA:
        raise ValueError("unknown audit schema")
    run_id = _string(record["run_id"], "run_id", max_length=80)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,79}", run_id):
        raise ValueError("run_id has an invalid format")
    for field in ("issue_ref", "pr_ref"):
        value = record[field]
        if value is not None:
            _string(value, field, max_length=80)
            if not re.fullmatch(r"#?[0-9]+|[A-Z][A-Z0-9-]*-[0-9]+", value):
                raise ValueError(f"{field} has an invalid format")
    if record["role"] not in ROLES:
        raise ValueError("unknown role")
    for field in ("agent_id", "prompt_version"):
        _string(record[field], field, max_length=100)
    started = _utc(record["started_at_utc"], "started_at_utc")
    finished = _utc(record["finished_at_utc"], "finished_at_utc")
    if finished < started:
        raise ValueError("finished_at_utc precedes started_at_utc")
    _refs(record["input_refs"], "input_refs")
    _refs(record["output_refs"], "output_refs")
    if record["status"] not in STATUSES:
        raise ValueError("unknown status")
    _safe_list(record["commands"], "commands")
    _safe_list(record["validation_results"], "validation_results")
    for result in record["validation_results"]:
        if result.get("status") not in RESULT_STATUSES:
            raise ValueError("validation result has an invalid status")
    _safe_list(record["human_edits"], "human_edits")
    _safe_list(record["findings"], "findings")
    _safe_list(record["errors"], "errors")
    usage = record["usage"]
    if not isinstance(usage, dict) or set(usage) != {
        "file_count",
        "input_characters",
        "tool_output_bytes",
        "elapsed_seconds",
    }:
        raise ValueError("usage must contain only bounded aggregate metrics")
    for key, value in usage.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > 10_000_000:
            raise ValueError(f"usage.{key} is outside its bound")


def _usage(record: dict[str, Any]) -> dict[str, float]:
    usage = record.get("usage", {})
    return {
        key: float(usage.get(key, 0))
        for key in ("file_count", "input_characters", "tool_output_bytes", "elapsed_seconds")
    }


def aggregate_metrics(
    records: Iterable[dict[str, Any]], usage_records: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    items = list(records)
    for item in items:
        validate_audit_record(item)
    durations = []
    for item in items:
        finished = datetime.fromisoformat(item["finished_at_utc"][:-1] + "+00:00")
        started = datetime.fromisoformat(item["started_at_utc"][:-1] + "+00:00")
        durations.append((finished - started).total_seconds())
    revisions = sum(bool(i["human_edits"]) for i in items)
    findings = [f for i in items for f in i["findings"]]
    categories = Counter(str(f.get("category", "unspecified")) for f in findings)
    validation = [v for i in items for v in i["validation_results"]]
    usage_keys = ("file_count", "input_characters", "tool_output_bytes", "elapsed_seconds")
    legacy_usage = list(usage_records)
    for usage_record in legacy_usage:
        validate_usage_payload(usage_record)
    total_usage = (
        {key: sum(_usage(item)[key] for item in items) for key in usage_keys}
        if items
        else dict.fromkeys(usage_keys, 0.0)
    )
    for usage_record in legacy_usage:
        for key in usage_keys:
            total_usage[key] += float(usage_record[key])
    reviewer_findings = sum(1 for finding in findings if finding.get("role") == "reviewer")
    return {
        "schema": "agent_metrics_v1",
        "runs": len(items),
        "cycle_time_seconds_total": sum(durations),
        "cycle_time_seconds_average": sum(durations) / len(durations) if items else 0,
        "revision_rate": revisions / len(items) if items else 0,
        "rework_count": sum(1 for i in items if i["status"] in {"failed", "blocked"}),
        "reviewer_recall": sum(1 for f in findings if f.get("outcome") == "confirmed") / max(1, reviewer_findings),
        "reviewer_false_positive_rate": sum(1 for f in findings if f.get("outcome") == "false_positive")
        / max(1, reviewer_findings),
        "scope_expansion_count": sum(1 for i in items for e in i["human_edits"] if e.get("type") == "scope_expansion"),
        "regressions_count": sum(1 for f in findings if f.get("category") == "regression"),
        "escaped_defects_count": sum(1 for f in findings if f.get("category") == "escaped_defect"),
        "report_completeness_rate": sum(bool(i["output_refs"]) for i in items) / len(items) if items else 0,
        "finding_categories": dict(sorted(categories.items())),
        "validation_results": dict(Counter(v["status"] for v in validation)),
        "usage_totals": total_usage,
    }


def monthly_retrospective(records: Iterable[dict[str, Any]], month: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("month must be YYYY-MM")
    selected = [r for r in records if r["started_at_utc"].startswith(month)]
    return {"schema": "agent_retrospective_v1", "month": month, "metrics": aggregate_metrics(selected)}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate and aggregate sanitized agent-run records")
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument("--month")
    args = parser.parse_args()
    records = [json.loads(path.read_text(encoding="utf-8")) for path in args.records]
    result = monthly_retrospective(records, args.month) if args.month else aggregate_metrics(records)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
