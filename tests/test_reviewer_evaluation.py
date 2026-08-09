import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from tools.evaluate_reviewer import (
    CASES_PATH,
    ORACLE_PATH,
    REPORT_SCHEMA_PATH,
    REVIEWER_PATH,
    evaluate_run,
    validate_corpus,
)


def _finding(
    finding_id: str,
    severity: str,
    category: str,
    location: str,
    excerpt: str,
    finding: str,
    required_change: str,
    suggested_test: str,
    *,
    evidence: str | None = None,
) -> dict[str, str]:
    return {
        "id": finding_id,
        "severity": severity,
        "category": category,
        "location": location,
        "finding": finding,
        "evidence": evidence or f"The reviewed patch contains `{excerpt}`.",
        "evidence_excerpt": excerpt,
        "impact": "The reachable behavior violates a required project invariant.",
        "required_change": required_change,
        "suggested_test": suggested_test,
    }


FINDINGS: dict[str, list[tuple[str, dict[str, str]]]] = {
    "RV-01": [
        (
            "RF-022",
            _finding(
                "RV-01-F00",
                "HIGH",
                "safety",
                "app/state_estimator/decisions.py:83",
                'for sensor in (sensor_health or {}).get("sensors", []):',
                "Missing sensor-health evidence can leave a state allowed.",
                "Require complete required-sensor health evidence before allowing a state.",
                "Test missing, incomplete and blocking sensor-health payloads and assert safe rejection.",
            ),
        ),
        (
            "RF-028",
            _finding(
                "RV-01-F02",
                "HIGH",
                "operations",
                "config/state_estimator_v1.yaml:6",
                "state_period_seconds: 600",
                "The diff changes production cadence outside the approved brief.",
                "Amend the brief with availability classification, rollback and recovery evidence.",
                "Run cadence and stale-alert boundary tests plus an isolated recovery rehearsal.",
            ),
        ),
        (
            "RF-014",
            _finding(
                "RV-01-F01",
                "MEDIUM",
                "tests",
                "app/api.py:347",
                '@router.get("/action-simulations/latest")',
                "The fixture omits contract classification and consumer evidence.",
                "Amend the brief and run all named compatibility and serialization checks.",
                "Run contract, API, storage and dashboard consumer tests with compatible fixtures.",
            ),
        ),
    ],
    "RV-03": [
        (
            "RF-015",
            _finding(
                "RV-03-F01",
                "HIGH",
                "operations",
                "deploy/scripts/restore-migration.sh:8",
                'migration_root="$(readlink -f /srv/backups/senior-pomidor/migration)"',
                "The evidence omits required data-loss migration and restore coverage.",
                "Amend the brief and obtain isolated restore, rollback and data-integrity evidence.",
                "manual: run the isolated restore and record checksums, counts, rollback and health.",
                evidence="The supplied historical evidence marks the required restore rehearsal as PASS.",
            ),
        ),
        (
            "RF-023",
            _finding(
                "RV-03-F02",
                "HIGH",
                "security",
                "docker-compose.yml:11",
                "DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://senior_pomidor:senior_pomidor@postgres:5432/senior_pomidor}",
                "Application services silently use a built-in database URL.",
                "Require an explicit database URL and reject missing configuration.",
                "Run Compose config without DATABASE_URL and assert a clear failure.",
            ),
        ),
        (
            "RF-029",
            _finding(
                "RV-03-F03",
                "HIGH",
                "operations",
                "deploy/scripts/backup.sh:65",
                "pg_dumpall --globals-only --no-role-passwords",
                "The application backup requires privileges unavailable to its database role.",
                "Remove the global dump or provide a separately owned least-privilege operation.",
                "Run backup and restore using the configured application role in isolation.",
            ),
        ),
        (
            "RF-034",
            _finding(
                "RV-03-F04",
                "HIGH",
                "security",
                "implementation_report.automated_evidence",
                "PASS: historical Compose, release and security checks",
                "The declared security risk lacks inspectable audit results.",
                "Attach scoped security-scan and dependency-audit results.",
                "Run the required security and dependency-audit checks and record results.",
            ),
        ),
    ],
    "RV-04": [
        (
            "RF-016",
            _finding(
                "RV-04-F01",
                "HIGH",
                "tests",
                "app/daily_story.py:432",
                "STORY_MAX_CHARS = 32768",
                "Representative local-model acceptance evidence is missing.",
                "Run representative local-model acceptance for the changed runtime and output bounds.",
                "manual: run bounded local-model malformed, reasoning, oversized and serialization checks.",
                evidence="The supplied report does not include representative local-model acceptance evidence.",
            ),
        ),
        (
            "RF-024",
            _finding(
                "RV-04-F02",
                "HIGH",
                "security",
                "app/daily_story.py:417",
                "if not story.endswith(STORY_END_MARKER):",
                "The validator accepts reasoning text before the required marker.",
                "Validate the complete bounded response structure and reject reasoning or prompt discussion.",
                "Test leading and embedded reasoning, prompt echoes, extra prose and valid final-only output.",
            ),
        ),
        (
            "RF-025",
            _finding(
                "RV-04-F03",
                "HIGH",
                "operations",
                "brief.risk_flags",
                '"risk_flags": []',
                "The brief omits risk flags for persisted and public story changes.",
                "Amend the classification and obtain required migration and public-consumer evidence.",
                "Run schema, persistence, public serialization and rollback checks for the changed story data.",
            ),
        ),
        (
            "RF-030",
            _finding(
                "RV-04-F04",
                "HIGH",
                "operations",
                "migrations/versions/0007_daily_story_runs.py:34",
                'sa.Column("story", sa.String(length=32768), nullable=True)',
                "An already-applied migration is edited instead of adding a forward revision.",
                "Add a forward migration that changes the existing story column safely.",
                "Test upgrade from the original revision and persistence beyond the old bound.",
            ),
        ),
        (
            "RF-031",
            _finding(
                "RV-04-F05",
                "HIGH",
                "security",
                "app/daily_story.py:391",
                '"{{ENVIRONMENT_CONTEXT_JSON}}": json.dumps(',
                "Private environment context can be echoed into public story output.",
                "Add a sanitized input projection and enforce output privacy before persistence.",
                "Test a private marker in model input and assert public output rejects or redacts it.",
            ),
        ),
    ],
    "RV-05": [
        (
            "RF-001",
            _finding(
                "RV-05-F01",
                "BLOCKER",
                "architecture",
                "app/control.py:1",
                'adapter.water(seconds=suggestion["seconds"])',
                "Control bypasses Guardrails and Executor.",
                "Route every candidate through deterministic Guardrails and the idempotent Executor.",
                "Test a blocked candidate and assert the fake adapter is not called.",
            ),
        ),
        (
            "RF-002",
            _finding(
                "RV-05-F02",
                "BLOCKER",
                "safety",
                "app/executor.py:1",
                "ACKNOWLEDGED = set()",
                "Restart loses acknowledgement state and can duplicate a command.",
                "Persist command transitions and reject uncertain restart state before adapter use.",
                "Simulate restart after send-before-ack and assert no second adapter call.",
            ),
        ),
        (
            "RF-004",
            _finding(
                "RV-05-F03",
                "BLOCKER",
                "safety",
                "app/guardrails.py:1",
                "else 0",
                "A missing timestamp is classified as fresh.",
                "Reject missing, invalid, future and stale timestamps at the Guardrails boundary.",
                "Test missing, invalid, future and stale timestamps and assert every candidate is blocked.",
            ),
        ),
        (
            "RF-018",
            _finding(
                "RV-05-F04",
                "HIGH",
                "tests",
                "implementation_report.manual_evidence",
                "NOT RUN: supervised safe-hardware and restart rehearsal",
                "Required physical and restart rehearsal evidence is missing.",
                "Obtain supervised hardware, abort, rollback and restart-recovery evidence before approval.",
                "manual: run the approved supervised safe-hardware and restart-recovery procedure.",
                evidence="The implementation report marks required evidence NOT RUN.",
            ),
        ),
        (
            "RF-035",
            _finding(
                "RV-05-F05",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: unit tests and fake-adapter CI",
                "Generic tests omit named physical failure-path simulations.",
                "Add deterministic duplicate, restart, timeout, stale and storage-failure simulations.",
                "Simulate every named physical failure path through Guardrails and Executor.",
            ),
        ),
    ],
    "RV-06": [
        (
            "RF-005",
            _finding(
                "RV-06-F01",
                "BLOCKER",
                "tests",
                "tests/fixtures/contracts/telemetry.json:1",
                '"soil_moisture": 0.42',
                "The expected fixture is rewritten to conceal contract drift.",
                "Restore the versioned fixture and add an explicit compatibility adapter or version.",
                "Replay old and current fixtures through the real ingestion and read paths.",
            ),
        ),
        (
            "RF-003",
            _finding(
                "RV-06-F02",
                "HIGH",
                "correctness",
                "app/state_estimator/decisions.py:1",
                'state["soil_moisture_ratio"] < dry_below_percent',
                "A normalized ratio is compared with a percent threshold.",
                "Use unit-bearing fields and validate one explicit conversion at the owner boundary.",
                "Test boundaries at 0, 1, 35 and 100 plus out-of-range rejection.",
            ),
        ),
        (
            "RF-006",
            _finding(
                "RV-06-F03",
                "HIGH",
                "tests",
                "tests/test_api.py:1",
                'mocker.patch("app.api.ingest_payload"',
                "The test mocks the broken HTTP ingestion path.",
                "Exercise the FastAPI endpoint through validation, persistence and readback.",
                "Run a POST with the frozen fixture and assert stored canonical data.",
            ),
        ),
        (
            "RF-019",
            _finding(
                "RV-06-F04",
                "HIGH",
                "tests",
                "implementation_report.manual_evidence",
                "NOT APPLICABLE: no physical action is in scope",
                "The contract change lacks edge compatibility and canary evidence.",
                "Add the edge compatibility flag and obtain named-consumer canary evidence.",
                "manual: replay old and new edge payloads and verify rollback through every consumer.",
                evidence="The implementation report marks edge canary evidence NOT RUN in effect.",
            ),
        ),
        (
            "RF-036",
            _finding(
                "RV-06-F05",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: schema fixture and API unit tests",
                "Generic evidence omits transport and downstream consumer replay.",
                "Add old/current HTTP, MQTT, storage and consumer replay evidence.",
                "Replay both fixture versions through every transport and named consumer.",
            ),
        ),
    ],
    "RV-07": [
        (
            "RF-008",
            _finding(
                "RV-07-F01",
                "BLOCKER",
                "operations",
                "docker-compose.rehearsal.yml:1",
                'GRAFANA_CLOUD_EXPORT_ENABLED: "true"',
                "Rehearsal enables external export.",
                "Remove external export from rehearsal and verify remote writes remain zero.",
                "Render the rehearsal config and assert the exporter and remote write are absent.",
            ),
        ),
        (
            "RF-007",
            _finding(
                "RV-07-F02",
                "HIGH",
                "operations",
                "docker-compose.yml:1",
                "${APP_IMAGE:-latest}",
                "APP_IMAGE silently falls back to latest.",
                "Restore required APP_IMAGE interpolation and a clear missing-variable failure.",
                "Run Compose config without APP_IMAGE and assert a clear failure.",
            ),
        ),
        (
            "RF-020",
            _finding(
                "RV-07-F03",
                "HIGH",
                "tests",
                "implementation_report.manual_evidence",
                "NOT RUN: isolated rehearsal and external-write inspection",
                "Required security, rehearsal, rollback and zero-export evidence is missing.",
                "Provide security checks and obtain isolated rehearsal and rollback evidence.",
                "manual: run an isolated failure-and-rollback rehearsal and verify zero external writes.",
                evidence="The implementation report marks the required rehearsal NOT RUN.",
            ),
        ),
        (
            "RF-026",
            _finding(
                "RV-07-F04",
                "HIGH",
                "security",
                "implementation_report.automated_evidence",
                "PASS: Compose config and CI",
                "Required security and dependency-audit evidence is missing.",
                "Run and record the required security and dependency-audit checks.",
                "Run nox security and dependency-audit checks and record exact results.",
            ),
        ),
        (
            "RF-037",
            _finding(
                "RV-07-F05",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: Compose config and CI",
                "Generic Compose evidence omits required negative configuration paths.",
                "Add missing-variable and rehearsal-export exclusion evidence.",
                "Render all profiles without APP_IMAGE and with rehearsal export disabled.",
            ),
        ),
    ],
    "RV-08": [
        (
            "RF-009",
            _finding(
                "RV-08-F01",
                "HIGH",
                "security",
                "tests/fixtures/ssh/private_key.txt:1",
                "BEGIN SYNTHETIC PRIVATE KEY",
                "A private-key-shaped fixture weakens the secret boundary.",
                "Replace the key shape with an unmistakably non-secret scanner-safe sentinel.",
                "Run the secret scan and verify no credential parser accepts the sentinel.",
            ),
        ),
        (
            "RF-027",
            _finding(
                "RV-08-F02",
                "HIGH",
                "tests",
                "implementation_report.manual_evidence",
                "NOT RUN: secret scanner and credential-format inspection",
                "Secret-scanner evidence is missing.",
                "Run the secret scanner and record its bounded result for the fixture.",
                "Run secret scanning against the synthetic fixture and scanner-owned detection sample.",
            ),
        ),
        (
            "RF-038",
            _finding(
                "RV-08-F03",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: fixture tests",
                "Real credential-parser rejection evidence is missing.",
                "Add a test proving the real credential parser rejects the fixture.",
                "Test the exact inert fixture through the parser without network use.",
            ),
        ),
    ],
    "RV-09": [
        (
            "RF-010",
            _finding(
                "RV-09-F01",
                "HIGH",
                "security",
                "app/daily_story.py:1",
                "public_summary = response.text",
                "Raw LLM text is published without validation.",
                "Validate a bounded schema and use only the parsed final field for publication.",
                "Test malformed JSON, extra reasoning, timeout and oversized model output.",
            ),
        ),
        (
            "RF-021",
            _finding(
                "RV-09-F02",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: daily-story unit tests",
                "The supplied tests omit required LLM negative and privacy paths.",
                "Add malformed, reasoning, timeout, unavailable, oversized and privacy tests.",
                "Run the focused model-boundary and public serialization failure-path tests.",
            ),
        ),
        (
            "RF-032",
            _finding(
                "RV-09-F03",
                "HIGH",
                "tests",
                "implementation_report.manual_evidence",
                "NOT APPLICABLE: local model acceptance is optional for this fixture",
                "Representative local-model acceptance is incorrectly declared not applicable.",
                "Run bounded representative acceptance for the changed public-output mapping.",
                "manual: exercise valid, reasoning, malformed and oversized local-model responses.",
            ),
        ),
    ],
    "RV-10": [
        (
            "RF-011",
            _finding(
                "RV-10-F01",
                "HIGH",
                "correctness",
                "tools/export.py:1",
                "Path(handle.name).unlink()",
                "An open temporary file is unlinked before close.",
                "Close the temporary file before cleanup and use platform-neutral paths.",
                "Run the focused cleanup test on Windows and Linux and verify removal.",
            ),
        ),
        (
            "RF-013",
            _finding(
                "RV-10-F02",
                "HIGH",
                "operations",
                "implementation-report.md:1",
                "| NOT RUN | isolated rollback rehearsal | Awaiting operator |",
                "Required rollback rehearsal is missing despite green CI.",
                "Require recorded isolated rollback rehearsal evidence before approval.",
                "manual: operator runs the bounded rehearsal and records abort and recovery health.",
                evidence="The implementation report marks the required rehearsal NOT RUN while automated CI passes.",
            ),
        ),
        (
            "RF-033",
            _finding(
                "RV-10-F04",
                "HIGH",
                "tests",
                "implementation_report.automated_evidence",
                "PASS: CI on Linux and documentation checks",
                "Linux-only CI omits the required Windows temporary-file regression path.",
                "Add focused Windows and Linux cleanup coverage before approval.",
                "Run export cleanup tests on Windows and Linux after success and failure.",
            ),
        ),
        (
            "RF-012",
            _finding(
                "RV-10-F03",
                "MEDIUM",
                "docs",
                "docs/OPERATIONS.md:1",
                "State freshness defaults to 30 seconds.",
                "The documented default differs from implementation.",
                "Align the authoritative runbook with the parsed configuration default.",
                "Test the documented example against the parsed default value.",
            ),
        ),
    ],
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _create_valid_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    oracle_ids = {item["id"] for item in json.loads(ORACLE_PATH.read_text(encoding="utf-8"))["findings"]}
    reviewer_hash = _hash(REVIEWER_PATH)
    manifest = {
        "schema": "senior-pomidor.reviewer-run.v1",
        "run_id": run_dir.name,
        "status": "candidate",
        "repository_revision": "6ed02f531323f07b4f69c7720043e33484b16610",
        "model_tier": "strong",
        "parameters": {"temperature": 0},
        "files": {
            "reviewer": {"path": str(REVIEWER_PATH), "sha256": reviewer_hash},
            "report_schema": {"path": str(REPORT_SCHEMA_PATH), "sha256": _hash(REPORT_SCHEMA_PATH)},
            "oracle": {"path": str(ORACLE_PATH), "sha256": _hash(ORACLE_PATH)},
            "cases": {"path": str(CASES_PATH), "sha256": _hash(CASES_PATH)},
        },
        "artifacts": [{"case_id": case["id"], **artifact} for case in cases for artifact in case["artifacts"]],
    }
    _write_json(run_dir / "manifest.json", manifest)
    mappings: list[dict[str, str]] = []
    for case in cases:
        paired = [
            (oracle_id, finding) for oracle_id, finding in FINDINGS.get(case["id"], []) if oracle_id in oracle_ids
        ]
        findings = [finding for _, finding in paired]
        _write_json(
            run_dir / "raw" / f"{case['id']}.json",
            {
                "schema": "senior-pomidor.review-report.v1",
                "title": case["title"],
                "case_id": case["id"],
                "reviewer_version": "Reviewer 1.0",
                "reviewer_hash": reviewer_hash,
                "verdict": "REQUEST CHANGES" if findings else "APPROVE",
                "rationale": "Frozen unit-test report for deterministic scorer behavior.",
                "classification": {"task_classes": [], "risk_flags": [], "sp_fail_ids": []},
                "scope_architecture": "Reviewed the complete frozen artifact set.",
                "findings": findings,
                "contract_consumer_review": "Reviewed or not applicable for this frozen case.",
                "evidence_matrix": [
                    {"check": "artifact review", "status": "PASS", "manual": False},
                    *(
                        [{"check": "isolated rollback rehearsal", "status": "NOT_RUN", "manual": True}]
                        if case["id"] in {"RV-05", "RV-06", "RV-07", "RV-08", "RV-10"}
                        else []
                    ),
                ],
                "operations_safety_security_privacy": "Assessed against the frozen context pack.",
                "documentation_assessment": "Assessed against the frozen artifact set.",
                "follow_ups": [],
                "limitations": ["Synthetic deterministic test fixture."],
            },
        )
        mappings.extend(
            {"observed_finding_id": finding["id"], "oracle_finding_id": oracle_id} for oracle_id, finding in paired
        )
    _write_json(run_dir / "mapping.json", {"schema": "senior-pomidor.reviewer-mapping.v1", "mappings": mappings})
    (run_dir / "adjudication.md").write_text("# Human adjudication\n\nOne-to-one mapping frozen.\n", encoding="utf-8")
    summary = evaluate_run(run_dir, compare_metrics=False)
    _write_json(run_dir / "metrics.json", {"schema": "senior-pomidor.reviewer-metrics.v1", **asdict(summary)})
    return run_dir


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reviewer_corpus_and_valid_run_pass(tmp_path: Path) -> None:
    cases, oracle = validate_corpus()
    summary = evaluate_run(_create_valid_run(tmp_path))

    assert len(cases) == 10
    assert len(oracle) == 19
    assert summary.blocker_recall == 1.0
    assert summary.high_recall >= 0.85
    assert summary.false_positive_rate <= 0.20
    assert summary.severity_agreement >= 0.80
    assert summary.actionable_rate >= 0.90
    assert summary.critical_ordering_passed
    assert summary.manual_evidence_detection_passed


def test_oracle_change_after_run_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    changed_oracle = tmp_path / "changed-oracle.json"
    document = _load(ORACLE_PATH)
    document["findings"][0]["summary"] = "Changed after the run"
    _write_json(changed_oracle, document)
    manifest_path = run_dir / "manifest.json"
    manifest = _load(manifest_path)
    manifest["files"]["oracle"]["path"] = str(changed_oracle)
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="oracle hash mismatch"):
        evaluate_run(run_dir, oracle_path=changed_oracle, compare_metrics=False)


def test_missing_blocker_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-05.json"
    report = _load(report_path)
    report["findings"] = report["findings"][1:]
    _write_json(report_path, report)
    mapping_path = run_dir / "mapping.json"
    mapping = _load(mapping_path)
    mapping["mappings"] = [item for item in mapping["mappings"] if item["oracle_finding_id"] != "RF-001"]
    _write_json(mapping_path, mapping)

    with pytest.raises(ValueError, match="BLOCKER recall"):
        evaluate_run(run_dir, compare_metrics=False)


def test_wrong_severity_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    for case_id in ("RV-03", "RV-04", "RV-08", "RV-09"):
        report_path = run_dir / "raw" / f"{case_id}.json"
        report = _load(report_path)
        for finding in report["findings"]:
            finding["severity"] = "MEDIUM"
        _write_json(report_path, report)

    with pytest.raises(ValueError, match="Severity agreement"):
        evaluate_run(run_dir, compare_metrics=False)


def test_duplicate_mapping_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    mapping_path = run_dir / "mapping.json"
    mapping = _load(mapping_path)
    mapping["mappings"].append(dict(mapping["mappings"][0]))
    _write_json(mapping_path, mapping)

    with pytest.raises(ValueError, match="Duplicate mapping"):
        evaluate_run(run_dir, compare_metrics=False)


def test_unmapped_false_positives_over_threshold_are_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-09.json"
    report = _load(report_path)
    for index in range(10):
        extra = dict(report["findings"][0])
        extra["id"] = f"RV-09-F9{index}"
        extra["finding"] = f"Unmapped style finding {index}"
        report["findings"].append(extra)
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="False-positive rate"):
        evaluate_run(run_dir, compare_metrics=False)


def test_low_before_blocker_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-07.json"
    report = _load(report_path)
    report["findings"][1]["severity"] = "LOW"
    report["findings"].reverse()
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="Critical findings"):
        evaluate_run(run_dir, compare_metrics=False)


def test_missing_raw_report_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    (run_dir / "raw" / "RV-04.json").unlink()

    with pytest.raises(ValueError, match="Missing raw report"):
        evaluate_run(run_dir, compare_metrics=False)


def test_reviewer_version_substitution_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-05.json"
    report = _load(report_path)
    report["reviewer_hash"] = "0" * 64
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="Reviewer hash mismatch"):
        evaluate_run(run_dir, compare_metrics=False)


def test_oracle_id_in_raw_report_is_rejected(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-05.json"
    report = _load(report_path)
    report["findings"][0]["expected_id"] = "RF-001"
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="leaks an oracle identifier"):
        evaluate_run(run_dir, compare_metrics=False)


def test_non_observable_evidence_fails_actionable_gate(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    for case_id in ("RV-05", "RV-06", "RV-07", "RV-08"):
        report_path = run_dir / "raw" / f"{case_id}.json"
        report = _load(report_path)
        report["findings"][0]["evidence_excerpt"] = "not present in any reviewed artifact"
        _write_json(report_path, report)

    with pytest.raises(ValueError, match="Actionable quality"):
        evaluate_run(run_dir, compare_metrics=False)


def test_green_ci_cannot_close_missing_manual_evidence(tmp_path: Path) -> None:
    run_dir = _create_valid_run(tmp_path)
    report_path = run_dir / "raw" / "RV-10.json"
    report = _load(report_path)
    report["findings"][1]["evidence"] = "All CI checks PASS, so the rehearsal is considered complete."
    report["evidence_matrix"][-1]["status"] = "PASS"
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="manual/rehearsal"):
        evaluate_run(run_dir, compare_metrics=False)
