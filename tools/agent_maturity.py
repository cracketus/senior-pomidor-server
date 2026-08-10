"""Machine-enforced maturity policy for agent task handoff."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.agent_audit import validate_audit_record

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(".ai/agent-maturity.yaml")
TASK_LEVELS = {
    "pure_software": 1,
    "documentation_only": 1,
    "llm_vision": 2,
    "application_logic": 2,
    "schema_data_contract": 3,
    "infrastructure_deployment": 3,
    "edge_hardware_integration": 4,
    "control_guardrails_executor": 4,
}
RISK_LEVELS = {
    "security_secrets": 1,
    "public_contract": 2,
    "edge_server_compatibility": 3,
    "production_availability": 3,
    "data_loss_migration": 3,
    "physical_action": 4,
}


@dataclass(frozen=True)
class GateResult:
    status: str
    level: int
    reasons: tuple[str, ...]
    downgrade_level: int | None = None


def required_level(task_classes: Iterable[str], risk_flags: Iterable[str], changed_files: Iterable[str] = ()) -> int:
    unknown = set(task_classes) - set(TASK_LEVELS) | set(risk_flags) - set(RISK_LEVELS)
    if unknown:
        raise ValueError(f"unknown task class or risk flag: {sorted(unknown)[0]}")
    level = max([1, *(TASK_LEVELS[x] for x in task_classes), *(RISK_LEVELS[x] for x in risk_flags)])
    if any(path.startswith("app/") for path in changed_files):
        level = max(level, 2)
    return level


def downgrade_level(level: int, events: Iterable[str]) -> tuple[int, tuple[str, ...]]:
    triggers = {
        "blocker",
        "high_finding",
        "secret_leak",
        "unintended_side_effect",
        "failed_rollback",
        "escaped_defect",
        "bypass_attempt",
    }
    found = tuple(sorted(set(events) & triggers))
    return (max(1, level - 1) if found else level, found)


def evaluate_gate(
    *,
    root: Path = ROOT,
    task_classes: Iterable[str],
    risk_flags: Iterable[str],
    audit_record: dict[str, Any] | None,
    brief_ref: str | None,
    evidence_refs: Iterable[str],
    approval_refs: Iterable[str],
    manual_evidence: bool = False,
    events: Iterable[str] = (),
    changed_files: Iterable[str] = (),
) -> GateResult:
    level = required_level(task_classes, risk_flags, changed_files)
    downgraded, triggers = downgrade_level(level, events)
    reasons: list[str] = [f"required_level={level}"]
    if triggers:
        reasons.append("downgraded:" + ",".join(triggers))
    if audit_record is None:
        reasons.append("missing audit record")
    else:
        try:
            validate_audit_record(audit_record)
        except ValueError:
            reasons.append("invalid audit record")
    if not brief_ref:
        reasons.append("missing implementation brief reference")
    if not tuple(evidence_refs):
        reasons.append("missing evidence references")
    if not tuple(approval_refs):
        reasons.append("missing human approval reference")
    policy = root / POLICY_PATH
    if not policy.is_file():
        reasons.append("missing maturity policy")
    if any(
        x in reasons
        for x in (
            "missing audit record",
            "missing implementation brief reference",
            "missing evidence references",
            "missing human approval reference",
            "missing maturity policy",
            "invalid audit record",
        )
    ):
        return GateResult("FAIL", downgraded, tuple(reasons), downgraded if triggers else None)
    if level >= 3 and not manual_evidence:
        reasons.append("manual compatibility/rehearsal evidence is NOT_RUN")
        return GateResult("NOT_RUN", downgraded, tuple(reasons), downgraded if triggers else None)
    return GateResult("PASS", downgraded, tuple(reasons), downgraded if triggers else None)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Show the required agent maturity level")
    parser.add_argument("--task-class", action="append", default=[])
    parser.add_argument("--risk-flag", action="append", default=[])
    args = parser.parse_args()
    level = required_level(args.task_class, args.risk_flag)
    print(yaml.safe_dump({"status": "NOT_RUN", "required_level": level}, sort_keys=True), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
