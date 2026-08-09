from __future__ import annotations

from tools.model_routing import route_model


def test_deterministic_and_low_risk_routes_use_bounded_tiers() -> None:
    assert route_model("classification").model_tier == "script"
    assert route_model("documentation_review").model_tier == "light"
    assert route_model("pure_software_implementation").model_tier == "medium"


def test_high_risk_findings_and_unknowns_escalate_to_strong() -> None:
    assert route_model("pure_software_review", risk_flags=("security_secrets",)).model_tier == "strong"
    assert route_model("pure_software_review", finding_severities=("HIGH",)).model_tier == "strong"
    assert route_model("pure_software_review", unknown_owner_consumer=True).model_tier == "strong"
    assert route_model("pure_software_review", contradictory_brief=True).model_tier == "strong"
    assert route_model("pure_software_review", missing_rollback_manual_evidence=True).model_tier == "strong"
    assert route_model("unregistered_operation").model_tier == "strong"


def test_subagent_policy_is_compact_json_without_inherited_context() -> None:
    policy = route_model("pure_software_review").subagent_policy

    assert policy["fork_turns"] == "none"
    assert policy["packet"] == "compact_json"
    assert policy["output"] == "structured_json"
    assert "one_agent_per_case" in policy["forbidden"]
