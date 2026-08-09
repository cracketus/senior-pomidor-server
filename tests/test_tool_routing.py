from __future__ import annotations

import pytest

from tools.tool_routing import route_tool


def test_known_github_lookup_routes_directly_without_discovery() -> None:
    route = route_tool("github_issue_lookup")

    assert route.selected_tool == "github"
    assert route.selected_operation == "issue_lookup"
    assert route.discovery_allowed is False
    assert route.connector_failed is False


def test_cli_fallback_requires_recorded_connector_failure() -> None:
    route = route_tool("github_issue_lookup", connector_failed=True)

    assert route.selected_tool == "gh"
    assert route.reason == "recorded_connector_failure"


def test_unknown_tool_operation_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown tool operation"):
        route_tool("discover_everything")
