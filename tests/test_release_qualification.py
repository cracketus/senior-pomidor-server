import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from tools.release_qualification import (
    QualificationError,
    build_system_invariants_report,
    validate_identity,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs" / "schemas"
FIXTURES = ROOT / "tests" / "fixtures" / "release_qualification"

REPORTS = {
    "system-invariants": ("system-invariants-v1.schema.json", "system_invariants_v1.json"),
    "edge-core-compatibility": (
        "edge-core-compatibility-report-v1.schema.json",
        "edge_core_compatibility_report_v1.json",
    ),
    "release-validation": ("release-validation-v1.schema.json", "release_validation_v1.json"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_invariant_catalog_has_stable_ids_and_current_test_mappings() -> None:
    catalog = yaml.safe_load((ROOT / "docs" / "system-invariants-v1.yaml").read_text(encoding="utf-8"))
    invariants = catalog["invariants"]
    identifiers = [item["invariant_id"] for item in invariants]

    assert catalog["schema_version"] == "senior-pomidor.system-invariant-catalog.v1"
    assert identifiers == [f"sp-inv-{index:03d}" for index in range(1, 9)]
    assert len(identifiers) == len(set(identifiers))

    for invariant in invariants:
        references = invariant["positive_tests"] + invariant["failure_tests"]
        if invariant["implementation_state"] == "IMPLEMENTED":
            assert invariant["positive_tests"]
            assert invariant["failure_tests"]
        else:
            assert invariant["implementation_state"] == "NOT_IMPLEMENTED"
            assert references == []
        for reference in references:
            relative_path, test_name = reference.split("::", 1)
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            assert f"def {test_name}(" in source

    report = load(FIXTURES / "system_invariants_v1.json")
    report_ids = {scenario["scenario_id"] for scenario in report["scenarios"]}
    assert set(identifiers).issubset(report_ids)


@pytest.mark.parametrize(("kind", "paths"), REPORTS.items())
def test_release_report_schemas_validate_and_fixtures_round_trip(kind: str, paths: tuple[str, str]) -> None:
    schema_name, fixture_name = paths
    schema = load(SCHEMAS / schema_name)
    fixture = load(FIXTURES / fixture_name)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)
    validate_report(kind, fixture)

    assert json.loads(json.dumps(fixture, sort_keys=True)) == fixture


def test_system_invariants_generator_executes_current_fail_safe_semantics() -> None:
    report = build_system_invariants_report(
        core_sha="c" * 40,
        core_image=f"core@sha256:{'a' * 64}",
        core_digest=f"sha256:{'a' * 64}",
        edge_sha="e" * 40,
        edge_image=f"edge@sha256:{'b' * 64}",
        edge_digest=f"sha256:{'b' * 64}",
    )

    validate_report("system-invariants", report, require_pass=True)
    by_id = {scenario["scenario_id"]: scenario for scenario in report["scenarios"]}

    assert report["status"] == "PASS"
    assert by_id["freshness-boundaries"]["counts"]["unknown"] == 2
    assert by_id["sp-inv-001"]["counts"] == {
        "generated": 1,
        "persisted": 1,
        "read_back": 1,
        "duplicates": 0,
        "missing": 0,
        "unknown": 0,
    }
    assert by_id["sp-inv-002"]["counts"]["duplicates"] == 1
    assert by_id["sp-inv-004"]["status"] == "PASS"
    assert {by_id[invariant_id]["applicability"] for invariant_id in ("sp-inv-006", "sp-inv-007", "sp-inv-008")} == {
        "NOT_IMPLEMENTED"
    }


def test_compatibility_template_cannot_satisfy_rc_gate_without_real_staging_passes() -> None:
    report = load(FIXTURES / "edge_core_compatibility_report_v1.json")

    with pytest.raises(QualificationError, match="required scenario"):
        validate_report("edge-core-compatibility", report, require_pass=True)

    report["status"] = "PASS"
    for scenario in report["scenarios"]:
        scenario["status"] = "PASS"
        scenario["evidence_scope"] = "STAGING"
        scenario["counts"].update({"generated": 1, "persisted": 1, "read_back": 1})

    validate_report("edge-core-compatibility", report, require_pass=True)

    incomplete = deepcopy(report)
    incomplete["scenarios"][0]["counts"].update({"generated": 10, "persisted": 0, "read_back": 0, "missing": 10})
    with pytest.raises(QualificationError, match="missing observations"):
        validate_report("edge-core-compatibility", incomplete, require_pass=True)

    incomplete["scenarios"][0]["counts"]["missing"] = 0
    with pytest.raises(QualificationError, match="incomplete persistence/read-back counts"):
        validate_report("edge-core-compatibility", incomplete, require_pass=True)


def test_release_template_cannot_satisfy_rc_gate_until_all_exact_scope_gates_pass() -> None:
    report = load(FIXTURES / "release_validation_v1.json")

    with pytest.raises(QualificationError, match="required scenario"):
        validate_report("release-validation", report, require_pass=True)

    report["status"] = "PASS"
    report["scenarios"][0]["status"] = "PASS"
    report["scenarios"][0]["alert_outcomes"][0].update(
        {"expected": "RECOVERED", "observed": "RECOVERED", "status": "PASS"}
    )
    for gate in report["gates"]:
        gate["status"] = "PASS"
        started = datetime.fromisoformat(gate["started_at_utc"].replace("Z", "+00:00"))
        durations = {
            "software-ci": 1,
            "docker-compose-e2e": 1,
            "cross-repository-staging": 24 * 60 * 60,
            "exact-bundle-rehearsal": 1,
            "server-rollout-canary": 60 * 60,
            "production-24h-observation": 24 * 60 * 60,
        }
        gate["finished_at_utc"] = (
            (started + timedelta(seconds=durations[gate["gate_id"]])).astimezone(UTC).isoformat().replace("+00:00", "Z")
        )

    validate_report("release-validation", report, require_pass=True)

    too_short = deepcopy(report)
    canary = next(gate for gate in too_short["gates"] if gate["gate_id"] == "server-rollout-canary")
    canary["finished_at_utc"] = canary["started_at_utc"]
    with pytest.raises(QualificationError, match="3600-second duration"):
        validate_report("release-validation", too_short, require_pass=True)


def test_semantic_validator_rejects_duplicate_scenarios_impossible_counts_and_alert_mismatch() -> None:
    original = load(FIXTURES / "system_invariants_v1.json")

    duplicate = deepcopy(original)
    duplicate["scenarios"].append(deepcopy(duplicate["scenarios"][0]))
    with pytest.raises(QualificationError, match="unique"):
        validate_report("system-invariants", duplicate)

    impossible = deepcopy(original)
    impossible["scenarios"][0]["counts"].update({"generated": 1, "persisted": 2})
    with pytest.raises(QualificationError, match="persisted count exceeds"):
        validate_report("system-invariants", impossible)

    alert_mismatch = deepcopy(original)
    alert_mismatch["scenarios"][0]["alert_outcomes"] = [
        {"rule_id": "example", "expected": "FIRING", "observed": "NOT_FIRING", "status": "PASS"}
    ]
    with pytest.raises(QualificationError, match="inconsistent status"):
        validate_report("system-invariants", alert_mismatch)


def test_actuator_invariants_cannot_be_claimed_implemented_by_this_release() -> None:
    report = load(FIXTURES / "system_invariants_v1.json")
    actuator = next(scenario for scenario in report["scenarios"] if scenario["scenario_id"] == "sp-inv-006")
    actuator.update({"applicability": "IMPLEMENTED", "status": "PASS"})

    with pytest.raises(QualificationError, match="must remain NOT_IMPLEMENTED"):
        validate_report("system-invariants", report)


def test_report_images_must_be_immutable_digest_refs_matching_declared_identity() -> None:
    mutable = load(FIXTURES / "system_invariants_v1.json")
    mutable["core"]["image_ref"] = "ghcr.io/cracketus/senior-pomidor-server:latest"
    with pytest.raises(JsonSchemaValidationError):
        validate_report("system-invariants", mutable)

    mismatch = load(FIXTURES / "system_invariants_v1.json")
    mismatch["core"]["image_ref"] = f"ghcr.io/cracketus/senior-pomidor-server@sha256:{'f' * 64}"
    with pytest.raises(QualificationError, match="not pinned"):
        validate_report("system-invariants", mismatch)

    report = load(FIXTURES / "system_invariants_v1.json")
    with pytest.raises(QualificationError, match="image_ref does not match"):
        validate_identity(report, core_image=f"core@sha256:{'f' * 64}")


def test_report_validator_rejects_private_field_names_hidden_in_notes() -> None:
    report = load(FIXTURES / "system_invariants_v1.json")
    report["scenarios"][0]["notes"] = ["copied raw_payload from a private host"]

    with pytest.raises(QualificationError, match="forbidden private field"):
        validate_report("system-invariants", report)


def test_report_validator_rejects_private_filesystem_paths_hidden_in_notes() -> None:
    report = load(FIXTURES / "system_invariants_v1.json")
    report["scenarios"][0]["notes"] = ["evidence copied from C:\\private\\runtime"]

    with pytest.raises(QualificationError, match="private filesystem path"):
        validate_report("system-invariants", report)


def test_report_fixtures_do_not_contain_private_runtime_fields() -> None:
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.json"))

    for forbidden in (
        "boot_id",
        "service_name",
        "last_error_detail",
        "raw_payload",
        "ssid",
        "ip_address",
        "database_path",
    ):
        assert forbidden not in serialized.lower()


def test_rc_workflow_has_fail_closed_checks_and_exact_identity_inputs() -> None:
    path = ROOT / ".github" / "workflows" / "release-qualification.yml"
    rendered = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(rendered)
    jobs = workflow["jobs"]

    assert set(jobs) == {"system-invariants", "edge-core-e2e", "release-validation"}
    assert jobs["release-validation"]["needs"] == ["system-invariants", "edge-core-e2e"]
    assert rendered.count("--require-pass") == 2
    for identity in ("core_sha", "core_image", "core_digest", "edge_sha", "edge_image", "edge_digest"):
        assert identity in rendered
    assert "docs/release-evidence/$REPORT_ID" in rendered
    assert "GRAFANA_CLOUD_EXPORT_ENABLED=true" not in rendered
    assert "down -v" not in rendered


def test_docker_e2e_source_preserves_isolation_cleanup_and_named_consumers() -> None:
    rendered = (ROOT / "tests" / "test_docker_e2e.py").read_text(encoding="utf-8")

    for required in (
        "assert_local_docker_context",
        "assert_compose_isolation",
        '"GRAFANA_CLOUD_EXPORT_ENABLED": "false"',
        "publish_mqtt",
        "wait_for_worker_outcome",
        'client.get("/ready")',
        'client.get("/health/summary?node_id=pi-001")',
        'client.get("/api/v1/operator/edges/pi-001/reliability")',
        "assert_grafana_alert_transitions",
        "emit_bounded_failure_evidence",
        'compose("--profile", "*", "down", "--remove-orphans"',
    ):
        assert required in rendered
    assert 'down", "-v' not in rendered
