from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".ai" / "tool-routing.yaml"


@dataclass(frozen=True)
class ToolRoute:
    schema: str
    operation: str
    selected_tool: str
    selected_operation: str
    connector_failed: bool
    discovery_allowed: bool
    reason: str


def _load_config(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("tool routing config must be a mapping")
    return loaded


def route_tool(operation: str, *, connector_failed: bool = False, config_path: Path = DEFAULT_CONFIG) -> ToolRoute:
    config = _load_config(config_path)
    operations = config.get("operations")
    if not isinstance(operations, dict) or not isinstance(operations.get(operation), dict):
        raise ValueError(f"unknown tool operation: {operation}")
    rule = operations[operation]
    if rule.get("discover_catalog") is not False:
        raise ValueError("known operations must explicitly disable catalog discovery")
    if connector_failed:
        if rule.get("fallback_only_after") != "connector_failure" or not isinstance(rule.get("fallback"), str):
            raise ValueError("tool fallback is not authorized after connector failure")
        selected_tool = rule["fallback"]
        selected_operation = operation
        reason = "recorded_connector_failure"
    else:
        selected_tool = rule.get("connector")
        selected_operation = rule.get("connector_operation")
        reason = "known_operation_direct_connector"
    if not isinstance(selected_tool, str) or not isinstance(selected_operation, str):
        raise ValueError("tool routing rule is incomplete")
    return ToolRoute(
        schema="senior-pomidor.tool-route.v1",
        operation=operation,
        selected_tool=selected_tool,
        selected_operation=selected_operation,
        connector_failed=connector_failed,
        discovery_allowed=False,
        reason=reason,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select a known tool directly without catalog discovery.")
    parser.add_argument("--operation", required=True)
    parser.add_argument("--connector-failed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        decision = route_tool(args.operation, connector_failed=args.connector_failed)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"tool-routing: {exc}") from exc
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
