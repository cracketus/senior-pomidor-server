from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_run_schema_defines_all_workflows_and_safe_states() -> None:
    schema = json.loads((ROOT / ".ai/schemas/scheduled_agent_run_v1.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]

    assert properties["schema"]["const"] == "scheduled_agent_run_v1"
    assert set(properties["agent_type"]["enum"]) == {
        "scientific_scout",
        "grant_scout",
        "story_miner",
        "documentation_sync",
        "weekly_planner",
    }
    assert set(properties["status"]["enum"]) == {"success", "partial", "failed", "skipped"}
    assert "idempotency_key" in schema["required"]
    assert properties["human_decision"]["required"] == ["status", "notes"]


def test_scheduled_examples_cover_each_agent_and_failure_states() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    records = document["records"]

    assert document["schema"] == "scheduled_agent_run_v1_examples"
    assert {record["agent_type"] for record in records} == {
        "scientific_scout",
        "grant_scout",
        "story_miner",
        "documentation_sync",
        "weekly_planner",
    }
    assert {record["status"] for record in records} == {"success", "partial", "failed", "skipped"}
    assert all(record["idempotency_key"] for record in records)
    assert all("password" not in str(record).lower() for record in records)


def test_policy_preserves_last_good_output_and_redaction_rules() -> None:
    policy = (ROOT / ".ai/workflows/SCHEDULED_AGENT_RUN_POLICY.md").read_text(encoding="utf-8")

    policy = policy.lower()
    for required in (
        "same idempotency key",
        "last good output remains current",
        "failed, partial, skipped",
        "raw prompts",
        "retention",
    ):
        assert required in policy
