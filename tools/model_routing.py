from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.agent_context import RISK_FLAGS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".ai" / "model-routing.yaml"
SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW", "NOTE")


@dataclass(frozen=True)
class ModelRoute:
    schema: str
    operation: str
    model_tier: str
    escalation_reasons: tuple[str, ...]
    subagent_policy: dict[str, Any]


def _load_config(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("model routing config must be a mapping")
    return loaded


def route_model(
    operation: str,
    *,
    risk_flags: tuple[str, ...] = (),
    finding_severities: tuple[str, ...] = (),
    unknown_owner_consumer: bool = False,
    contradictory_brief: bool = False,
    missing_rollback_manual_evidence: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> ModelRoute:
    unknown_flags = set(risk_flags) - set(RISK_FLAGS)
    if unknown_flags:
        raise ValueError(f"unknown risk flag: {sorted(unknown_flags)[0]}")
    normalized_severities = tuple(value.upper() for value in finding_severities)
    unknown_severities = set(normalized_severities) - set(SEVERITIES)
    if unknown_severities:
        raise ValueError(f"unknown finding severity: {sorted(unknown_severities)[0]}")
    config = _load_config(config_path)
    operations = config.get("operations")
    escalation = config.get("strong_escalation")
    subagents = config.get("subagents")
    if not isinstance(operations, dict) or not isinstance(escalation, dict) or not isinstance(subagents, dict):
        raise ValueError("model routing config is incomplete")

    reasons: list[str] = []
    base_tier = operations.get(operation)
    if base_tier is None:
        base_tier = "strong"
        reasons.append("unknown_operation")
    strong_flags = set(escalation.get("risk_flags", ()))
    strong_severities = set(escalation.get("finding_severities", ()))
    if set(risk_flags) & strong_flags:
        reasons.append("high_risk_flag")
    if set(normalized_severities) & strong_severities:
        reasons.append("blocker_high_finding")
    if unknown_owner_consumer:
        reasons.append("unknown_owner_consumer")
    if contradictory_brief:
        reasons.append("contradictory_brief")
    if missing_rollback_manual_evidence:
        reasons.append("missing_rollback_manual_evidence")
    tier = "strong" if reasons else str(base_tier)
    if tier not in config.get("tiers", ()):
        raise ValueError(f"model routing config selects unknown tier: {tier}")
    return ModelRoute(
        schema="senior-pomidor.model-route.v1",
        operation=operation,
        model_tier=tier,
        escalation_reasons=tuple(dict.fromkeys(reasons)) or ("none",),
        subagent_policy=dict(subagents),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select a deterministic model tier without invoking a model.")
    parser.add_argument("--operation", required=True)
    parser.add_argument("--risk-flag", action="append", choices=RISK_FLAGS, default=[])
    parser.add_argument("--finding-severity", action="append", choices=SEVERITIES, default=[])
    parser.add_argument("--unknown-owner-consumer", action="store_true")
    parser.add_argument("--contradictory-brief", action="store_true")
    parser.add_argument("--missing-rollback-manual-evidence", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        decision = route_model(
            args.operation,
            risk_flags=tuple(args.risk_flag),
            finding_severities=tuple(args.finding_severity),
            unknown_owner_consumer=args.unknown_owner_consumer,
            contradictory_brief=args.contradictory_brief,
            missing_rollback_manual_evidence=args.missing_rollback_manual_evidence,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"model-routing: {exc}") from exc
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
