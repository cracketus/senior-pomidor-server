from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def scheduled_run_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / ".ai/schemas/scheduled_agent_run_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


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
    validator = scheduled_run_validator()
    assert [error.message for record in records for error in validator.iter_errors(record)] == []


def test_scheduled_examples_round_trip_without_contract_drift() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))

    assert json.loads(json.dumps(document, sort_keys=True)) == document


def test_scheduled_schema_rejects_invalid_idempotency_keys() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    valid_record = document["records"][0]
    validator = scheduled_run_validator()

    for invalid_key in (
        "scientific_scout:2026-08-10T10:00Z:abc123",
        "short",
        "scientific scout:2026-08-10t10:00z:abc123",
        "scientific_scout:2026-08-10t10:00z:abc123/unsafe",
    ):
        invalid_record = deepcopy(valid_record)
        invalid_record["idempotency_key"] = invalid_key
        assert list(validator.iter_errors(invalid_record)), invalid_key


def test_scheduled_schema_rejects_trailing_line_breaks_in_identifier_fields() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    valid_record = document["records"][0]
    validator = scheduled_run_validator()

    for line_break in ("\n", "\r\n"):
        invalid_records = [deepcopy(valid_record) for _index in range(7)]
        invalid_records[0]["run_id"] += line_break
        invalid_records[1]["idempotency_key"] += line_break
        invalid_records[2]["input_refs"][0] += line_break
        invalid_records[3]["previous_run_ref"] = valid_record["run_id"] + line_break
        invalid_records[4]["external_sources"][0]["source_ref"] += line_break
        invalid_records[5]["outputs"][0]["artifact_ref"] += line_break
        invalid_records[6]["errors"] = [{"code": "temporary_failure" + line_break, "retryable": True}]

        for invalid_record in invalid_records:
            assert list(validator.iter_errors(invalid_record)), repr(line_break)


def test_scheduled_schema_rejects_unsafe_references_at_every_reference_boundary() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    valid_record = document["records"][0]
    validator = scheduled_run_validator()

    for unsafe_reference in (
        "/absolute/path",
        "C:\\private\\artifact.json",
        "unsafe\rreference",
        "unsafe\x00reference",
        "unsafe\treference",
        "raw text",
        "../escape",
        ".",
        "-option",
    ):
        invalid_records = [deepcopy(valid_record) for _index in range(4)]
        invalid_records[0]["input_refs"] = [unsafe_reference]
        invalid_records[1]["previous_run_ref"] = unsafe_reference
        invalid_records[2]["external_sources"][0]["source_ref"] = unsafe_reference
        invalid_records[3]["outputs"][0]["artifact_ref"] = unsafe_reference
        for invalid_record in invalid_records:
            assert list(validator.iter_errors(invalid_record)), unsafe_reference


def test_scheduled_schema_rejects_incomplete_success_records() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    valid_success = document["records"][0]
    validator = scheduled_run_validator()

    for field, value in (("completed_at_utc", None), ("outputs", [])):
        incomplete = deepcopy(valid_success)
        incomplete[field] = value
        assert list(validator.iter_errors(incomplete)), field


def test_scheduled_schema_rejects_outputs_for_failed_runs() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    failed_record = deepcopy(next(record for record in document["records"] if record["status"] == "failed"))
    validator = scheduled_run_validator()

    assert list(validator.iter_errors(failed_record)) == []
    for publication_state in ("candidate", "superseded", "none"):
        contradictory_record = deepcopy(failed_record)
        contradictory_record["outputs"] = [
            {
                "artifact_ref": f".ai/agent-runs/failed-{publication_state}.json",
                "publication_state": publication_state,
            }
        ]
        assert list(validator.iter_errors(contradictory_record)), publication_state


def test_scheduled_schema_enforces_documented_run_id_format_and_agent_identity() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    valid_record = document["records"][0]
    validator = scheduled_run_validator()

    for invalid_run_id in (
        "abc",
        "20260810t100000z-scientific_scout-a1",
        "20260810T100000Z-unknown_agent-a1",
        "20260810T100000Z-scientific_scout",
        "20260810T100000Z-scientific_scout-unsafe/suffix",
    ):
        invalid_record = deepcopy(valid_record)
        invalid_record["run_id"] = invalid_run_id
        assert list(validator.iter_errors(invalid_record)), invalid_run_id

    mismatched_record = deepcopy(valid_record)
    mismatched_record["run_id"] = "20260810T100000Z-grant_scout-a1"
    assert list(validator.iter_errors(mismatched_record))

    prefix = "20260810T100000Z-scientific_scout-"
    maximum_length_record = deepcopy(valid_record)
    maximum_length_record["run_id"] = prefix + "a" * (120 - len(prefix))
    assert list(validator.iter_errors(maximum_length_record)) == []

    overlong_record = deepcopy(maximum_length_record)
    overlong_record["run_id"] += "a"
    assert list(validator.iter_errors(overlong_record))


def test_scheduled_schema_rejects_accepted_publication_for_non_success_runs() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    accepted_success = document["records"][3]
    validator = scheduled_run_validator()

    assert list(validator.iter_errors(accepted_success)) == []
    for status in ("partial", "failed", "skipped"):
        contradictory_record = deepcopy(accepted_success)
        contradictory_record["status"] = status
        errors = list(validator.iter_errors(contradictory_record))
        assert errors, status


def test_scheduled_schema_rejects_accepted_publication_without_human_acceptance() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    accepted_publication = deepcopy(document["records"][3])
    accepted_publication["status"] = "success"
    accepted_publication["human_decision"] = {"status": "pending", "notes": "Awaiting review."}

    assert list(scheduled_run_validator().iter_errors(accepted_publication))


def test_scheduled_schema_rejects_accepted_decision_for_failed_run() -> None:
    document = yaml.safe_load((ROOT / ".ai/agent-runs/scheduled-agent-examples.yaml").read_text(encoding="utf-8"))
    failed_record = deepcopy(document["records"][4])
    failed_record["human_decision"] = {"status": "accepted", "notes": "Synthetic contradiction."}

    assert list(scheduled_run_validator().iter_errors(failed_record))


def test_policy_preserves_last_good_output_and_redaction_rules() -> None:
    policy = (ROOT / ".ai/workflows/SCHEDULED_AGENT_RUN_POLICY.md").read_text(encoding="utf-8")

    policy = policy.lower()
    for required in (
        "same idempotency key",
        "last good output remains current",
        "failed, partial, skipped",
        "raw prompts",
        "retention",
        "lowercase `t` and `z`",
    ):
        assert required in policy
