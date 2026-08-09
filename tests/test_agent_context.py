from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.agent_context import ROOT, normalize_changed_file, select_context

FULL_SAFETY_FILES = {
    ".ai/PROJECT.md",
    ".ai/CURRENT_STATE.md",
    ".ai/ARCHITECTURE_RULES.md",
    ".ai/SAFETY_RULES.md",
    ".ai/DEVELOPMENT_RULES.md",
    ".ai/KNOWN_FAILURES.md",
    ".ai/known-failures.yaml",
    ".ai/TEST_MATRIX.md",
    ".ai/test-matrix.yaml",
}


def selected_paths(selection) -> set[str]:
    return {item.path for item in selection.files}


def test_pure_software_uses_compact_context() -> None:
    selection = select_context("coder", ["tools/agent_context.py"])

    assert selection.task_classes == ("pure_software",)
    assert selection.risk_flags == ()
    assert selection.full_context is False
    assert selected_paths(selection) == {
        ".ai/CORE_INVARIANTS.md",
        ".ai/DEVELOPMENT_RULES.md",
        ".ai/agents/coding-agent.md",
    }
    assert {item["failure_id"] for item in selection.known_failures} == {"SP-FAIL-014", "SP-FAIL-015"}


@pytest.mark.parametrize(
    ("changed_file", "risk_flag"),
    [
        ("app/control/new_policy.py", "physical_action"),
        ("migrations/versions/9999_example.py", "data_loss_migration"),
        ("app/auth.py", "security_secrets"),
        ("app/telemetry.py", "edge_server_compatibility"),
        (".github/workflows/ci.yml", "production_availability"),
        ("docs/schemas/new-contract.json", "public_contract"),
    ],
)
def test_each_high_risk_path_forces_full_context(changed_file: str, risk_flag: str) -> None:
    selection = select_context("reviewer", [changed_file])

    assert risk_flag in selection.risk_flags
    assert selection.full_context is True
    assert selected_paths(selection) >= FULL_SAFETY_FILES
    assert f"high_risk_flag:{risk_flag}" in selection.escalation_reasons


def test_unknown_path_fails_safe_to_full_context() -> None:
    selection = select_context("planner", ["future-owner/new_component.xyz"])

    assert selection.task_classes == ("pure_software",)
    assert selection.full_context is True
    assert selected_paths(selection) >= FULL_SAFETY_FILES
    assert "unknown_path_fail_safe" in selection.escalation_reasons


def test_explicit_risk_flag_can_only_add_full_context() -> None:
    selection = select_context(
        "coder",
        ["app/services.py"],
        risk_flag_overrides=["physical_action"],
    )

    assert selection.full_context is True
    assert "physical_action" in selection.risk_flags
    assert selected_paths(selection) >= FULL_SAFETY_FILES
    assert "explicit_risk_flag:physical_action" in selection.selection_reasons


def test_documentation_class_is_dropped_when_executable_class_applies() -> None:
    selection = select_context("coder", ["docs/AGENT_TASK_WORKFLOW.md"])

    assert selection.task_classes == ("pure_software",)


def test_windows_and_absolute_paths_normalize_identically() -> None:
    assert normalize_changed_file("tools\\agent_context.py") == "tools/agent_context.py"
    assert normalize_changed_file(str(ROOT / "tools" / "agent_context.py")) == "tools/agent_context.py"


def test_path_escape_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid changed file"):
        select_context("coder", ["../outside.py"])


def test_cli_json_is_deterministic_and_read_only(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "tools.agent_context",
        "--role",
        "coder",
        "--changed-files",
        "tools/agent_context.py",
        "--format",
        "json",
    ]
    before = {path: path.stat().st_mtime_ns for path in (ROOT / ".ai").glob("*.yaml")}
    first = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)  # nosec B603
    second = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)  # nosec B603

    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["schema"] == "senior-pomidor.agent-context.v1"
    assert payload["source_hashes"]
    assert payload["context_characters"] > 0
    assert payload["selection_reasons"] == ["path_rule:python_tools_tests:tools/agent_context.py"]
    assert before == {path: path.stat().st_mtime_ns for path in (ROOT / ".ai").glob("*.yaml")}
    assert not (tmp_path / ".agent-usage").exists()


def test_core_invariants_stay_under_word_limit() -> None:
    words = (ROOT / ".ai" / "CORE_INVARIANTS.md").read_text(encoding="utf-8").split()
    assert len(words) <= 1500


def test_reviewer_session_replay_reduces_context_by_at_least_35_percent() -> None:
    replay = yaml.safe_load((ROOT / ".ai/evaluations/context-router/replay-v1.yaml").read_text(encoding="utf-8"))
    case = replay["cases"][0]
    selection = select_context(case["role"], case["changed_files"])
    reduction = 1 - selection.context_characters / case["legacy_full_context_characters"]

    assert selection.full_context is False
    assert reduction >= case["minimum_reduction_fraction"]
    assert selection.context_characters < case["legacy_full_context_characters"]
    assert not any("/runs/" in item.path for item in selection.files)
    selected_text = "\n".join((ROOT / item.path).read_text(encoding="utf-8") for item in selection.files)
    assert "ALL_TOOLS" not in selected_text


def test_shared_agent_contract_changes_select_both_role_evaluations() -> None:
    selection = select_context("coder", [".ai/context-manifest.yaml"])

    assert {item["id"] for item in selection.checks} >= {
        "feature_planner_evaluation",
        "reviewer_evaluation",
    }


def test_model_routing_contract_selects_both_role_evaluations() -> None:
    selection = select_context("coder", [".ai/model-routing.yaml"])

    assert {item["id"] for item in selection.checks} >= {
        "feature_planner_evaluation",
        "reviewer_evaluation",
    }


def test_manifest_and_selected_sources_have_content_hashes() -> None:
    selection = select_context("coder", ["tools/agent_context.py"])

    assert set(selection.source_hashes) == {
        ".ai/context-manifest.yaml",
        ".ai/known-failures.yaml",
        ".ai/test-matrix.yaml",
    }
    assert all(len(value) == 64 for value in selection.source_hashes.values())
    assert all(len(item.sha256) == 64 for item in selection.files)
