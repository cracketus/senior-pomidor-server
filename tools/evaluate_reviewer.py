from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = ROOT / ".ai" / "evaluations" / "reviewer"
CASES_PATH = SUITE_DIR / "cases" / "v2.json"
ORACLE_PATH = SUITE_DIR / "oracles" / "v6.json"
REVIEWER_PATH = ROOT / ".ai" / "agents" / "reviewer.md"
TEMPLATE_PATH = ROOT / ".ai" / "templates" / "review-report.md"
REPORT_SCHEMA_PATH = ROOT / ".ai" / "templates" / "review-report.schema.json"

SEVERITY_RANK = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NOTE": 4}
ACTION_VERBS = re.compile(
    r"\b(add|align|amend|attach|close|convert|exercise|implement|map|obtain|persist|preserve|prevent|"
    r"provide|record|reject|remove|replace|require|restore|route|run|treat|use|validate|verify|version)\b",
    re.IGNORECASE,
)
TEST_TERMS = re.compile(r"\b(assert|replay|render|run|simulate|tests?|verify)\b", re.IGNORECASE)
REQUIRED_TEMPLATE_HEADINGS = (
    "## Verdict",
    "## Independent classification",
    "## Scope and architecture assessment",
    "## Findings",
    "## Contract and consumer review",
    "## Test and evidence matrix",
    "## Operations, safety, security and privacy",
    "## Documentation assessment",
    "## Follow-ups outside this PR",
    "## Limitations and unverified evidence",
)


@dataclass(frozen=True)
class EvaluationSummary:
    case_count: int
    expected_finding_count: int
    observed_finding_count: int
    blocker_recall: float
    high_recall: float
    false_positive_rate: float
    severity_agreement: float
    actionable_rate: float
    critical_ordering_passed: bool
    manual_evidence_detection_passed: bool


def _load_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _object_list(
    document: dict[str, Any], field: str, *, source: Path, allow_empty: bool = False
) -> list[dict[str, Any]]:
    value = document.get(field)
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, dict) for item in value)
    ):
        qualifier = "an object list" if allow_empty else "a non-empty object list"
        raise ValueError(f"{source}.{field} must be {qualifier}")
    return value


def _string(item: dict[str, Any], field: str, *, label: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{field} must be a non-empty string")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_artifact_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _file_sha256(path: Path) -> str:
    return _sha256(_text_artifact_bytes(path))


def _repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"Artifact escapes repository root: {value}")
    return path


def _git_diff(revision: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{7,40}", revision):
        raise ValueError(f"Invalid historical revision: {revision}")
    process = subprocess.run(  # nosec B603 B607
        ["git", "show", "--format=", "--binary", revision],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if process.returncode:
        raise ValueError(f"Historical revision is unavailable: {revision}")
    return process.stdout


def _artifact_bytes(artifact: dict[str, Any], *, label: str) -> bytes:
    kind = _string(artifact, "kind", label=label)
    if kind == "patch":
        path = _repo_path(_string(artifact, "path", label=label))
        if not path.is_file():
            raise ValueError(f"Missing patch artifact: {path.relative_to(ROOT)}")
        return _text_artifact_bytes(path)
    if kind == "git_diff":
        return _git_diff(_string(artifact, "revision", label=label))
    raise ValueError(f"{label}.kind must be patch or git_diff")


def _validate_role_contract() -> None:
    reviewer_text = REVIEWER_PATH.read_text(encoding="utf-8").casefold()
    for term in (
        "separate session/context",
        "do not edit code",
        "passing ci",
        "guardrails",
        "executor",
        "sp-fail-*",
        "request changes",
        "blocked",
    ):
        if term not in reviewer_text:
            raise ValueError(f"Reviewer instructions are missing mandatory term: {term}")

    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    missing = [heading for heading in REQUIRED_TEMPLATE_HEADINGS if heading not in template_text]
    if missing:
        raise ValueError(f"Review Report template misses headings: {', '.join(missing)}")
    for field in (
        "id:",
        "severity:",
        "category:",
        "location:",
        "finding:",
        "evidence:",
        "evidence_excerpt:",
        "impact:",
        "required_change:",
        "suggested_test:",
    ):
        if field not in template_text:
            raise ValueError(f"Review Report template misses finding field: {field}")
    report_schema = _load_object(REPORT_SCHEMA_PATH)
    if report_schema.get("$id") != "senior-pomidor.review-report.v1":
        raise ValueError("Review Report JSON schema has the wrong identity")


def validate_corpus(
    cases_path: Path = CASES_PATH, oracle_path: Path = ORACLE_PATH
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _validate_role_contract()
    cases = _object_list(_load_object(cases_path), "cases", source=cases_path)
    oracle = _object_list(_load_object(oracle_path), "findings", source=oracle_path)
    if len(cases) != 10:
        raise ValueError("Reviewer corpus must contain exactly 10 cases")
    kinds = [case.get("kind") for case in cases]
    if kinds.count("historical") != 4 or kinds.count("seeded") != 6:
        raise ValueError("Reviewer corpus must contain four historical and six seeded cases")

    case_ids: set[str] = set()
    for case in cases:
        case_id = _string(case, "id", label="case")
        if case_id in case_ids:
            raise ValueError(f"Duplicate case: {case_id}")
        case_ids.add(case_id)
        artifacts = _object_list(case, "artifacts", source=cases_path)
        for index, artifact in enumerate(artifacts):
            data = _artifact_bytes(artifact, label=f"{case_id}.artifacts[{index}]")
            expected_hash = _string(artifact, "sha256", label=f"{case_id}.artifacts[{index}]")
            if _sha256(data) != expected_hash:
                raise ValueError(f"Artifact hash mismatch for {case_id} artifact {index}")

    finding_ids: set[str] = set()
    for finding in oracle:
        finding_id = _string(finding, "id", label="oracle finding")
        case_id = _string(finding, "case_id", label=finding_id)
        severity = _string(finding, "severity", label=finding_id)
        _string(finding, "category", label=finding_id)
        _string(finding, "summary", label=finding_id)
        if finding_id in finding_ids:
            raise ValueError(f"Duplicate oracle finding: {finding_id}")
        if case_id not in case_ids or severity not in SEVERITY_RANK:
            raise ValueError(f"{finding_id} has an unknown case or severity")
        finding_ids.add(finding_id)
    return cases, oracle


def _manifest_file(manifest: dict[str, Any], key: str, expected_path: Path) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not isinstance(files.get(key), dict):
        raise ValueError(f"manifest.files.{key} is required")
    entry = files[key]
    recorded_path = Path(_string(entry, "path", label=f"manifest.files.{key}"))
    manifest_path = recorded_path.resolve() if recorded_path.is_absolute() else _repo_path(str(recorded_path))
    if manifest_path != expected_path.resolve():
        raise ValueError(f"manifest.files.{key}.path does not identify the evaluated file")
    if _string(entry, "sha256", label=f"manifest.files.{key}") != _file_sha256(expected_path):
        raise ValueError(f"{key} hash mismatch; run is invalid")


def _artifact_texts(case: dict[str, Any]) -> list[str]:
    artifact_texts = [
        _artifact_bytes(artifact, label=f"{case['id']}.artifact").decode("utf-8", errors="replace")
        for artifact in case["artifacts"]
    ]
    artifact_texts.append(
        json.dumps(
            {"brief": case.get("brief"), "implementation_report": case.get("implementation_report")},
            ensure_ascii=False,
        )
    )
    return artifact_texts


def _observable_texts(artifact_texts: list[str]) -> list[str]:
    normalized = [
        "\n".join(line[1:] if line.startswith(("+", "-", " ")) else line for line in text.splitlines())
        for text in artifact_texts
    ]
    return [*artifact_texts, *normalized]


def _location_exists(location: str, artifact_texts: list[str]) -> bool:
    if location.startswith("implementation_report"):
        return any('"implementation_report"' in text for text in artifact_texts)
    if location.startswith("brief"):
        return any('"brief"' in text for text in artifact_texts)
    location_path = location.removeprefix("patch:").split(":", maxsplit=1)[0]
    candidates = (f"a/{location_path}", f"b/{location_path}", location_path)
    return any(candidate in text for candidate in candidates for text in artifact_texts)


def _is_actionable(finding: dict[str, Any], artifact_texts: list[str]) -> bool:
    location = str(finding["location"])
    excerpt = str(finding["evidence_excerpt"])
    required_change = str(finding["required_change"])
    suggested_test = str(finding["suggested_test"])
    observable_texts = _observable_texts(artifact_texts)
    normalized_excerpt = " ".join(excerpt.split())
    return (
        _location_exists(location, artifact_texts)
        and len(excerpt.strip()) >= 8
        and any(normalized_excerpt in " ".join(text.split()) for text in observable_texts)
        and len(required_change.split()) >= 5
        and ACTION_VERBS.search(required_change) is not None
        and (
            suggested_test.casefold().startswith("manual:")
            or (len(suggested_test.split()) >= 4 and TEST_TERMS.search(suggested_test) is not None)
        )
    )


def _metrics_payload(summary: EvaluationSummary) -> dict[str, Any]:
    return {"schema": "senior-pomidor.reviewer-metrics.v1", **asdict(summary)}


def evaluate_run(
    run_dir: Path,
    *,
    cases_path: Path = CASES_PATH,
    oracle_path: Path = ORACLE_PATH,
    compare_metrics: bool = True,
) -> EvaluationSummary:
    cases, oracle = validate_corpus(cases_path, oracle_path)
    manifest_path = run_dir / "manifest.json"
    manifest = _load_object(manifest_path)
    if manifest.get("status") not in {"candidate", "final"}:
        raise ValueError("Only candidate or final runs may be scored")
    for field in ("run_id", "repository_revision", "model_tier", "parameters"):
        if field not in manifest:
            raise ValueError(f"manifest.{field} is required")
    if manifest["run_id"] != run_dir.name:
        raise ValueError("manifest.run_id must match the run directory")
    if manifest["model_tier"] not in {"light", "medium", "strong"}:
        raise ValueError("manifest.model_tier must be light, medium or strong")
    if not isinstance(manifest["parameters"], dict):
        raise ValueError("manifest.parameters must be an object")
    _git_diff(_string(manifest, "repository_revision", label="manifest"))
    _manifest_file(manifest, "reviewer", REVIEWER_PATH)
    _manifest_file(manifest, "report_schema", REPORT_SCHEMA_PATH)
    _manifest_file(manifest, "oracle", oracle_path)
    _manifest_file(manifest, "cases", cases_path)
    reviewer_hash = manifest["files"]["reviewer"]["sha256"]

    manifest_artifacts = manifest.get("artifacts")
    expected_artifacts = [{"case_id": case["id"], **artifact} for case in cases for artifact in case["artifacts"]]
    if manifest_artifacts != expected_artifacts:
        raise ValueError("Manifest artifact inventory does not match frozen cases")

    reports: dict[str, dict[str, Any]] = {}
    observed_by_id: dict[str, dict[str, Any]] = {}
    actionable_count = 0
    ordering_passed = True
    for case in cases:
        case_id = case["id"]
        report_path = run_dir / "raw" / f"{case_id}.json"
        if not report_path.is_file():
            raise ValueError(f"Missing raw report: {report_path.name}")
        report = _load_object(report_path)
        if report.get("schema") != "senior-pomidor.review-report.v1":
            raise ValueError(f"Raw report {report_path.name} has the wrong schema")
        if report.get("case_id") != case_id:
            raise ValueError(f"Raw report {report_path.name} has the wrong case_id")
        if report.get("reviewer_hash") != reviewer_hash:
            raise ValueError(f"Reviewer hash mismatch in {report_path.name}")
        for field in (
            "title",
            "reviewer_version",
            "rationale",
            "scope_architecture",
            "contract_consumer_review",
            "operations_safety_security_privacy",
            "documentation_assessment",
        ):
            _string(report, field, label=report_path.name)
        if report.get("verdict") not in {"APPROVE", "APPROVE WITH FOLLOW-UPS", "REQUEST CHANGES", "BLOCKED"}:
            raise ValueError(f"Raw report {report_path.name} has an invalid verdict")
        classification = report.get("classification")
        if not isinstance(classification, dict):
            raise ValueError(f"Raw report {report_path.name} has no classification")
        for field in ("task_classes", "risk_flags", "sp_fail_ids"):
            if not isinstance(classification.get(field), list) or not all(
                isinstance(item, str) for item in classification[field]
            ):
                raise ValueError(f"Raw report {report_path.name} has an invalid classification.{field}")
        for field in ("follow_ups", "limitations"):
            if not isinstance(report.get(field), list) or not all(isinstance(item, str) for item in report[field]):
                raise ValueError(f"Raw report {report_path.name} has an invalid {field} list")
        evidence_matrix = _object_list(report, "evidence_matrix", source=report_path)
        for evidence_index, evidence_item in enumerate(evidence_matrix):
            _string(evidence_item, "check", label=f"{case_id}.evidence_matrix[{evidence_index}]")
            if evidence_item.get("status") not in {"PASS", "FAIL", "NOT_RUN"}:
                raise ValueError(f"{case_id}.evidence_matrix[{evidence_index}] has an invalid status")
            if not isinstance(evidence_item.get("manual"), bool):
                raise ValueError(f"{case_id}.evidence_matrix[{evidence_index}].manual must be boolean")
        findings = _object_list(report, "findings", source=report_path, allow_empty=True)
        artifact_texts = _artifact_texts(case)
        ranks: list[int] = []
        for index, finding in enumerate(findings):
            if "expected_id" in finding or "oracle_finding_id" in finding:
                raise ValueError(f"Raw finding {case_id}[{index}] leaks an oracle identifier")
            finding_id = _string(finding, "id", label=f"{case_id}[{index}]")
            if finding_id in observed_by_id:
                raise ValueError(f"Duplicate observed finding ID: {finding_id}")
            for field in (
                "severity",
                "category",
                "location",
                "finding",
                "evidence",
                "evidence_excerpt",
                "impact",
                "required_change",
                "suggested_test",
            ):
                _string(finding, field, label=finding_id)
            severity = finding["severity"]
            if severity not in SEVERITY_RANK:
                raise ValueError(f"{finding_id} has an unknown severity")
            ranks.append(SEVERITY_RANK[severity])
            observed_by_id[finding_id] = {"case_id": case_id, **finding}
            actionable_count += int(_is_actionable(finding, artifact_texts))
        ordering_passed &= ranks == sorted(ranks)
        reports[case_id] = report

    mapping_doc = _load_object(run_dir / "mapping.json")
    mappings = _object_list(mapping_doc, "mappings", source=run_dir / "mapping.json", allow_empty=True)
    oracle_by_id = {item["id"]: item for item in oracle}
    mapped_observed: set[str] = set()
    mapped_oracle: set[str] = set()
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, mapping in enumerate(mappings):
        observed_id = _string(mapping, "observed_finding_id", label=f"mapping[{index}]")
        oracle_id = _string(mapping, "oracle_finding_id", label=f"mapping[{index}]")
        if observed_id in mapped_observed or oracle_id in mapped_oracle:
            raise ValueError("Duplicate mapping or hidden one-to-many mapping")
        if observed_id not in observed_by_id or oracle_id not in oracle_by_id:
            raise ValueError("Mapping references an unknown observed or oracle finding")
        observed = observed_by_id[observed_id]
        expected = oracle_by_id[oracle_id]
        if observed["case_id"] != expected["case_id"]:
            raise ValueError("Mapping crosses case boundaries")
        mapped_observed.add(observed_id)
        mapped_oracle.add(oracle_id)
        matched.append((expected, observed))

    def recall(severity: str) -> float:
        relevant = {item["id"] for item in oracle if item["severity"] == severity}
        return len(relevant & mapped_oracle) / len(relevant) if relevant else 1.0

    observed_count = len(observed_by_id)
    severity_agreement = (
        sum(expected["severity"] == observed["severity"] for expected, observed in matched) / len(matched)
        if matched
        else 0.0
    )
    manual_expected = {item["id"] for item in oracle if item.get("requires_manual_verification") is True}
    manual_passed = bool(manual_expected) and all(
        any(
            expected["id"] == required_id
            and observed["severity"] in {"BLOCKER", "HIGH"}
            and any(
                item.get("manual") is True and item.get("status") == "NOT_RUN"
                for item in reports[observed["case_id"]]["evidence_matrix"]
            )
            for expected, observed in matched
        )
        for required_id in manual_expected
    )
    summary = EvaluationSummary(
        case_count=len(cases),
        expected_finding_count=len(oracle),
        observed_finding_count=observed_count,
        blocker_recall=recall("BLOCKER"),
        high_recall=recall("HIGH"),
        false_positive_rate=(observed_count - len(mapped_observed)) / observed_count if observed_count else 0.0,
        severity_agreement=severity_agreement,
        actionable_rate=actionable_count / observed_count if observed_count else 0.0,
        critical_ordering_passed=ordering_passed,
        manual_evidence_detection_passed=manual_passed,
    )

    if summary.blocker_recall != 1.0:
        raise ValueError("BLOCKER recall must be 100%")
    if summary.high_recall < 0.85:
        raise ValueError("HIGH recall must be at least 85%")
    if summary.false_positive_rate > 0.20:
        raise ValueError("False-positive rate must be at most 20%")
    if summary.severity_agreement < 0.80:
        raise ValueError("Severity agreement must be at least 80%")
    if summary.actionable_rate < 0.90:
        raise ValueError("Actionable quality must be at least 90%")
    if not summary.critical_ordering_passed:
        raise ValueError("Critical findings must precede lower-severity findings")
    if not summary.manual_evidence_detection_passed:
        raise ValueError("Missing manual/rehearsal evidence was not detected")
    if not (run_dir / "adjudication.md").is_file():
        raise ValueError("Run is missing adjudication.md")

    if compare_metrics:
        recorded = _load_object(run_dir / "metrics.json")
        if recorded != _metrics_payload(summary):
            raise ValueError("Recorded metrics do not match deterministic scoring")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or score the oracle-blind Reviewer evaluation suite.")
    parser.add_argument("--run", type=Path, help="Run directory containing manifest/raw/mapping/metrics/adjudication")
    args = parser.parse_args()
    if args.run is None:
        cases, oracle = validate_corpus()
        print(
            f"Reviewer corpus PASS: {len(cases)} immutable cases and {len(oracle)} oracle findings; "
            "no final oracle-blind run is published."
        )
        return
    summary = evaluate_run(args.run)
    print(
        "Reviewer run PASS: "
        f"BLOCKER {summary.blocker_recall:.0%}; HIGH {summary.high_recall:.0%}; "
        f"false positives {summary.false_positive_rate:.0%}; severity {summary.severity_agreement:.0%}; "
        f"actionable {summary.actionable_rate:.0%}."
    )


if __name__ == "__main__":
    main()
