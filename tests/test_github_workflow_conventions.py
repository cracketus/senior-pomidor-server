from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"


def test_all_required_issue_templates_exist_and_collect_brief_and_acceptance() -> None:
    expected = {
        "feature_request.yml",
        "bug_report.yml",
        "schema_change.yml",
        "infrastructure_change.yml",
        "hardware_edge_change.yml",
    }
    assert {path.name for path in TEMPLATES.glob("*.yml")} >= expected
    for name in expected:
        content = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "id: brief" in content
        assert "Implementation Brief" in content
        assert "acceptance" in content.lower() or "acceptance criteria" in content.lower()


def test_pr_template_exposes_approval_safety_and_evidence_gates() -> None:
    content = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    for required in (
        "Approved Implementation Brief",
        "Architecture and contract impact",
        "Safety and operations",
        "PASS / FAIL / NOT RUN",
        "Implementation Report",
        "Review Report",
        "Human maintainer approved merge",
    ):
        assert required in content


def test_workflow_docs_preserve_human_approval_and_safe_evidence_boundaries() -> None:
    content = (ROOT / "docs" / "GITHUB_AGENT_WORKFLOW.md").read_text(encoding="utf-8").replace("\n", " ")
    for required in (
        "needs-planning",
        "ready-for-agent",
        "review-required",
        "ready-for-human-review",
        "human maintainer",
        "NOT RUN",
        "production writes",
        "real GPIO/actuator",
    ):
        assert required in content


def test_workflow_docs_require_github_authentication_preflight_and_ci_readback() -> None:
    content = (ROOT / "docs" / "GITHUB_AGENT_WORKFLOW.md").read_text(encoding="utf-8")
    for required in (
        "gh auth status -h github.com",
        "gh api user",
        "GH_TOKEN",
        "gh pr view <number> --json url,mergeStateStatus,statusCheckRollup",
        "successful push does not prove",
        "NOT_RUN",
    ):
        assert required in content
