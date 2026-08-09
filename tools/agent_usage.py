from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path(".agent-usage") / "usage.jsonl"
ROLES = ("planner", "coder", "reviewer")
MODEL_TIERS = ("script", "light", "medium", "strong")
ESCALATION_REASONS = (
    "blocker_high_finding",
    "contradictory_brief",
    "high_risk_flag",
    "missing_rollback_manual_evidence",
    "none",
    "unknown_owner_consumer",
    "unknown_path",
)
PAYLOAD_FIELDS = {
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


@dataclass(frozen=True)
class UsageRecord:
    schema: str
    recorded_at_utc: str
    role: str
    file_count: int
    input_characters: int
    tool_output_bytes: int
    model_tier: str
    elapsed_seconds: float
    escalation_reasons: tuple[str, ...]


def make_usage_record(
    *,
    role: str,
    file_count: int,
    input_characters: int,
    tool_output_bytes: int,
    model_tier: str,
    elapsed_seconds: float,
    escalation_reasons: list[str] | tuple[str, ...],
    now: datetime | None = None,
) -> UsageRecord:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    if model_tier not in MODEL_TIERS:
        raise ValueError(f"Unknown model tier: {model_tier}")
    counts = (file_count, input_characters, tool_output_bytes)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in counts):
        raise ValueError("Usage counts must be integers")
    if not isinstance(elapsed_seconds, (int, float)) or isinstance(elapsed_seconds, bool):
        raise ValueError("Elapsed time must be numeric")
    if any(value < 0 for value in counts) or elapsed_seconds < 0:
        raise ValueError("Usage counts and elapsed time must be non-negative")
    reasons = tuple(dict.fromkeys(escalation_reasons)) or ("none",)
    unknown = set(reasons) - set(ESCALATION_REASONS)
    if unknown:
        raise ValueError(f"Unknown escalation reason: {sorted(unknown)[0]}")
    if "none" in reasons and len(reasons) > 1:
        raise ValueError("Escalation reason 'none' cannot be combined with other reasons")
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return UsageRecord(
        schema="senior-pomidor.agent-usage.v1",
        recorded_at_utc=timestamp,
        role=role,
        file_count=file_count,
        input_characters=input_characters,
        tool_output_bytes=tool_output_bytes,
        model_tier=model_tier,
        elapsed_seconds=elapsed_seconds,
        escalation_reasons=reasons,
    )


def validate_usage_payload(payload: dict[str, Any]) -> None:
    if set(payload) != PAYLOAD_FIELDS:
        raise ValueError("Usage payload contains missing or unknown fields")
    if payload["schema"] != "senior-pomidor.agent-usage.v1":
        raise ValueError("Unknown usage payload schema")
    if not isinstance(payload["recorded_at_utc"], str) or not payload["recorded_at_utc"].endswith("Z"):
        raise ValueError("Usage timestamp must be UTC")
    try:
        datetime.fromisoformat(payload["recorded_at_utc"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Usage timestamp is invalid") from exc
    make_usage_record(
        role=payload["role"],
        file_count=payload["file_count"],
        input_characters=payload["input_characters"],
        tool_output_bytes=payload["tool_output_bytes"],
        model_tier=payload["model_tier"],
        elapsed_seconds=payload["elapsed_seconds"],
        escalation_reasons=payload["escalation_reasons"],
    )


def record_usage(record: UsageRecord, *, output: Path = DEFAULT_OUTPUT, root: Path = ROOT) -> Path:
    root = root.resolve()
    target = output if output.is_absolute() else root / output
    target = target.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Usage output escapes repository root")
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    if os.name != "nt":
        os.chmod(target, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append one privacy-safe local agent usage record.")
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--file-count", required=True, type=int)
    parser.add_argument("--input-characters", required=True, type=int)
    parser.add_argument("--tool-output-bytes", required=True, type=int)
    parser.add_argument("--model-tier", required=True, choices=MODEL_TIERS)
    parser.add_argument("--elapsed-seconds", required=True, type=float)
    parser.add_argument("--escalation-reason", action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = make_usage_record(
            role=args.role,
            file_count=args.file_count,
            input_characters=args.input_characters,
            tool_output_bytes=args.tool_output_bytes,
            model_tier=args.model_tier,
            elapsed_seconds=args.elapsed_seconds,
            escalation_reasons=args.escalation_reason,
        )
        record_usage(record, output=args.output)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"agent-usage: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
