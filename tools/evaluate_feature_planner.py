from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = ROOT / ".ai" / "evaluations" / "feature-planner"
CASES_PATH = SUITE_DIR / "cases.json"
RESULTS_PATH = SUITE_DIR / "results.json"
PLANNER_PATH = ROOT / ".ai" / "agents" / "feature-planner.md"

REQUIRED_HEADINGS = (
    "## Problem",
    "## Desired outcome",
    "## Current behavior and evidence",
    "## Scope",
    "## Out of scope",
    "## Architecture placement",
    "## Affected contracts and consumers",
    "## Safety/risk classification",
    "## Proposed implementation sequence",
    "## Failure modes",
    "## Backward compatibility",
    "## Testing plan",
    "## Observability",
    "## Documentation updates",
    "## Rollout and rollback",
    "## Acceptance criteria",
    "## Blocking open questions",
    "## Evidence and references",
)

CRITICAL_TERMS = {
    "FP-02": ("rehearsal", "isolat", "rollback"),
    "FP-04": ("rehearsal", "isolat", "rollback"),
    "FP-05": ("guardrails", "idempotency", "retry", "simulation"),
    "FP-08": ("compatibility", "consumers"),
}


@dataclass(frozen=True)
class EvaluationSummary:
    case_count: int
    passing_revision_cases: int
    required_passing_cases: int
    minimum_revision_score: int


def _load_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return loaded


def _require_string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a non-empty string list")
    return value


def _validate_scores(value: Any, *, label: str, criterion_count: int) -> list[int]:
    if not isinstance(value, list) or len(value) != criterion_count:
        raise ValueError(f"{label} must contain {criterion_count} scores")
    if not all(isinstance(score, int) and 0 <= score <= 2 for score in value):
        raise ValueError(f"{label} scores must be integers from 0 through 2")
    return value


def evaluate_suite() -> EvaluationSummary:
    cases_document = _load_object(CASES_PATH)
    results_document = _load_object(RESULTS_PATH)
    cases = cases_document.get("cases")
    results = results_document.get("case_results")
    rubric = _require_string_list(results_document.get("rubric"), label="rubric")

    if not isinstance(cases, list) or len(cases) != 10:
        raise ValueError("cases.json must contain exactly 10 cases")
    if not isinstance(results, list) or len(results) != len(cases):
        raise ValueError("results.json must contain one result for every case")
    if len(rubric) != 10 or len(set(rubric)) != len(rubric):
        raise ValueError("rubric must contain 10 unique criteria")

    planner_text = PLANNER_PATH.read_text(encoding="utf-8").lower()
    for term in ("stop after planning", "do not implement", "unknown", "only the completed brief"):
        if term not in planner_text:
            raise ValueError(f"Feature Planner is missing mandatory instruction: {term}")

    results_by_id: dict[str, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise ValueError("Every result must be an object with case_id")
        case_id = item["case_id"]
        if case_id in results_by_id:
            raise ValueError(f"Duplicate result: {case_id}")
        results_by_id[case_id] = item

    passing = 0
    minimum_score = len(rubric) * 2
    evidence_index = rubric.index("evidence_grounding")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Every case must be an object with id")
        case_id = case["id"]
        result = results_by_id.get(case_id)
        if result is None:
            raise ValueError(f"Missing result for {case_id}")
        for field in ("planner_available_evidence", "oracle_evidence"):
            evidence_items = _require_string_list(case.get(field), label=f"{case_id}.{field}")
            for evidence_item in evidence_items:
                if evidence_item.startswith(("commit:", "issue:")):
                    continue
                if not (ROOT / evidence_item).exists():
                    raise ValueError(f"{case_id} references missing evidence: {evidence_item}")

        brief_path_value = case.get("brief_path")
        if not isinstance(brief_path_value, str):
            raise ValueError(f"{case_id} brief_path must be a string")
        brief_path = ROOT / brief_path_value
        brief_text = brief_path.read_text(encoding="utf-8")
        missing_headings = [heading for heading in REQUIRED_HEADINGS if heading not in brief_text]
        if missing_headings:
            raise ValueError(f"{case_id} brief misses headings: {', '.join(missing_headings)}")
        for term in _require_string_list(case.get("required_terms"), label=f"{case_id}.required_terms"):
            if term.casefold() not in brief_text.casefold():
                raise ValueError(f"{case_id} brief misses required characteristic: {term}")
        brief_casefold = brief_text.casefold()
        for term in CRITICAL_TERMS.get(case_id, ()):
            if term not in brief_casefold:
                raise ValueError(f"{case_id} brief fails critical gate: {term}")
        if "unknown" not in brief_casefold and "unverified" not in brief_casefold:
            raise ValueError(f"{case_id} brief does not expose unknown or unverified facts")

        initial_scores = _validate_scores(
            result.get("initial_scores"),
            label=f"{case_id}.initial_scores",
            criterion_count=len(rubric),
        )
        revision_scores = _validate_scores(
            result.get("revision_1_scores"),
            label=f"{case_id}.revision_1_scores",
            criterion_count=len(rubric),
        )
        for field in ("false_assumptions", "missing_questions", "revision_changes"):
            _require_string_list(result.get(field), label=f"{case_id}.{field}")
        if revision_scores[evidence_index] < 1:
            raise ValueError(f"{case_id} fails the evidence-grounding gate")
        if sum(revision_scores) < sum(initial_scores):
            raise ValueError(f"{case_id} regressed after the revision cycle")

        total = sum(revision_scores)
        minimum_score = min(minimum_score, total)
        if total >= 16:
            passing += 1

    if passing < 8:
        raise ValueError(f"Only {passing} revision cases reached the required 16/20")

    return EvaluationSummary(
        case_count=len(cases),
        passing_revision_cases=passing,
        required_passing_cases=8,
        minimum_revision_score=minimum_score,
    )


def main() -> None:
    summary = evaluate_suite()
    print(
        "Feature Planner evaluation PASS: "
        f"{summary.passing_revision_cases}/{summary.case_count} revision cases >=16/20; "
        f"minimum score {summary.minimum_revision_score}/20."
    )


if __name__ == "__main__":
    main()
