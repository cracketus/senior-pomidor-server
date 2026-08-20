from __future__ import annotations

from pathlib import Path

from tools.docs_map import coverage_report, load_docs_map, validate_docs_map

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "docs_map"


def test_repository_map_covers_required_areas_and_existing_documents() -> None:
    data = load_docs_map(ROOT / "docs-map.yaml")
    result = validate_docs_map(data, ROOT)

    assert result["valid"] is True
    assert {entry["area"] for entry in result["entries"]} == {
        "schemas_models",
        "api_storage",
        "compose_deploy",
        "state_estimator",
        "future_control_boundaries",
        "hardware_adapters",
        "public_readme_status",
    }


def test_unknown_source_path_is_fail_closed() -> None:
    data = load_docs_map(FIXTURES / "unknown-source.yaml")
    validation = validate_docs_map(data, ROOT)
    report = coverage_report(validation, ["app/models.py", "app/not-mapped.py"])

    assert report["map_valid"] is True
    assert report["unknown_source_paths"] == ["app/not-mapped.py"]
    assert report["coverage_percent"] == 50.0


def test_missing_owner_is_invalid() -> None:
    result = validate_docs_map(load_docs_map(FIXTURES / "missing-owner.yaml"), ROOT)

    assert result["valid"] is False
    assert any("owner" in error for error in result["errors"])


def test_authority_conflict_is_invalid_and_does_not_choose_truth() -> None:
    result = validate_docs_map(load_docs_map(FIXTURES / "authority-conflict.yaml"), ROOT)

    assert result["valid"] is False
    assert any("authority conflict" in error for error in result["errors"])
    assert all(entry["conflict_behavior"] == "human_review_no_truth_selection" for entry in result["entries"])


def test_mechanical_and_semantic_mappings_are_explicit() -> None:
    result = validate_docs_map(load_docs_map(FIXTURES / "mechanical-and-semantic.yaml"), ROOT)
    entries = {entry["id"]: entry for entry in result["entries"]}

    assert result["valid"] is True
    assert entries["mechanical"]["semantic_review_required"] is False
    assert entries["mechanical"]["mechanical_fields"] == ["ports", "healthchecks"]
    assert entries["semantic"]["semantic_review_required"] is True
    assert entries["semantic"]["mechanical_fields"] == []
