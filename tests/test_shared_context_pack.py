from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(relative_path: str) -> dict[str, Any]:
    value = yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    assert value["version"] == 1
    return value


def test_shared_context_yaml_documents_have_required_machine_readable_shapes() -> None:
    topics = _load(".ai/research/scientific-topics.yaml")
    grants = _load(".ai/research/grant-sources.yaml")
    platforms = _load(".ai/content/platform-profiles.yaml")
    goals = _load(".ai/planning/project-goals.yaml")
    calendar = _load(".ai/planning/seasonal-calendar.yaml")

    assert topics["evidence_vocabulary"].keys() >= {"measured", "observed", "inferred", "speculative"}
    assert topics["topics"]
    assert grants["review_policy"]["review_before_use"] is True
    assert all(source["url"].startswith("https://") for source in grants["sources"])
    assert set(platforms["profiles"]) == {"telegram", "linkedin", "substack"}
    assert goals["planning_fields"]["required"]
    assert calendar["timezone"] == "Europe/Vienna"


def test_shared_context_links_and_privacy_boundaries_are_explicit() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    workflows = (ROOT / ".ai/workflows/README.md").read_text(encoding="utf-8")

    for relative_path in (
        ".ai/research/RESEARCH_SCOPE.md",
        ".ai/content/CLAIMS_POLICY.md",
        ".ai/planning/PRIORITY_RULES.md",
    ):
        assert relative_path in agents or relative_path.replace(".ai/", "../") in workflows
    assert "private" in agents.lower()
    assert "CURRENT_STATE.md" in workflows
