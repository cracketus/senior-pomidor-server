from __future__ import annotations

import json
from pathlib import Path

from tools.agent_maturity import downgrade_level, evaluate_gate, required_level


def test_task_and_risk_levels_accumulate() -> None:
    assert required_level(["pure_software"], []) == 1
    assert required_level(["schema_data_contract"], []) == 3
    assert required_level(["pure_software"], ["physical_action"]) == 4


def test_missing_approval_and_evidence_fail_closed() -> None:
    result = evaluate_gate(
        root=Path.cwd(),
        task_classes=["pure_software"],
        risk_flags=[],
        audit_record=None,
        brief_ref=None,
        evidence_refs=[],
        approval_refs=[],
    )
    assert result.status == "FAIL"
    assert "missing human approval reference" in result.reasons


def test_manual_high_level_evidence_stays_not_run() -> None:
    audit = json.loads(
        (Path(__file__).parents[1] / ".ai/agent-runs/2026-08-pilot-coder.json").read_text(encoding="utf-8")
    )
    result = evaluate_gate(
        root=Path.cwd(),
        task_classes=["schema_data_contract"],
        risk_flags=[],
        audit_record=audit,
        brief_ref="brief.md",
        evidence_refs=["validation.json"],
        approval_refs=["maintainer"],
    )
    assert result.status == "NOT_RUN"


def test_downgrade_covers_bypass_and_escaped_defect() -> None:
    level, reasons = downgrade_level(4, ["bypass_attempt", "escaped_defect"])
    assert level == 3
    assert reasons == ("bypass_attempt", "escaped_defect")
