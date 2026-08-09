from __future__ import annotations

from tools.ai_context_docs import ROOT, expected_documents, sync_documents


def test_generated_ai_context_summaries_are_current() -> None:
    assert sync_documents(write=False) == []


def test_generated_summaries_are_deterministic() -> None:
    first = expected_documents()
    second = expected_documents()

    assert first == second
    assert all("<!-- BEGIN GENERATED SUMMARY -->" in content for content in first.values())


def test_known_failure_markdown_is_only_a_compact_index() -> None:
    markdown = (ROOT / ".ai/KNOWN_FAILURES.md").read_text(encoding="utf-8")
    canonical = (ROOT / ".ai/known-failures.yaml").read_text(encoding="utf-8")

    assert "root_causes:" not in markdown
    assert "root_causes:" in canonical
    assert "SP-FAIL-014" in markdown


def test_test_matrix_declares_yaml_as_its_own_source_of_truth() -> None:
    yaml_text = (ROOT / ".ai/test-matrix.yaml").read_text(encoding="utf-8")
    markdown = (ROOT / ".ai/TEST_MATRIX.md").read_text(encoding="utf-8")

    assert "source_of_truth: .ai/test-matrix.yaml" in yaml_text
    assert "canonical machine-readable source" in markdown


def test_context_tool_is_not_packaged_as_application_runtime() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'include = ["app*"]' in pyproject
    assert "tools*" not in pyproject
