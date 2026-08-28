"""Bounded, staging-only qualification controller.

The controller accepts no shell fragments. Every Docker operation is assembled from fixed
Compose/project/network/container values and all output is sanitized before it is returned.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - fixed Docker argv is the bounded staging boundary.
from typing import Any

PROJECT = "senior-pomidor-staging"
EDGE_CONTAINER = "senior-pomidor-edge-staging"
NETWORK = "senior-pomidor-staging-interop"
SCENARIOS = {
    "normal-delivery",
    "core-outage-spool-growth",
    "core-recovery-full-drain",
    "lost-ack-after-persistence",
    "duplicate-http-mqtt",
    "edge-restart-pending",
    "fresh-during-backlog-replay",
    "watchdog-recovering-suppressed",
    "spool-degraded-critical",
    "delayed-stale-future-out-of-order",
}
FAULT_PHASES = {
    "core-outage-spool-growth": ("stop", "api"),
    "core-recovery-full-drain": ("start", "api"),
}


class QualificationControllerError(ValueError):
    pass


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise QualificationControllerError(f"{name} is required")
    return value


def _compose(*args: str) -> list[str]:
    if any("\n" in arg or "\x00" in arg for arg in args):
        raise QualificationControllerError("invalid command argument")
    return ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml", *args]


def _run(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(  # nosec B603 - args are fixed/allowlisted and shell is never used.
        args, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    # Never return Docker output: it can contain environment-derived values or broker diagnostics.
    return {"status": "PASS" if result.returncode == 0 else "FAIL", "returncode": result.returncode}


def _edge_connection() -> dict[str, Any]:
    result = subprocess.run(  # nosec - fixed inspect argv, no shell, staging-only identity.
        ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", EDGE_CONTAINER],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        networks = json.loads(result.stdout) if result.returncode == 0 else {}
    except json.JSONDecodeError:
        networks = {}
    connected = isinstance(networks, dict) and NETWORK in networks
    return {"status": "PASS" if connected else "FAIL", "edge_connected": connected}


def preflight() -> dict[str, Any]:
    if _env("DEPLOYMENT_MODE", "staging") != "staging":
        raise QualificationControllerError("controller only permits DEPLOYMENT_MODE=staging")
    if _env("STAGING_INTEROP_NETWORK", NETWORK) != NETWORK:
        raise QualificationControllerError("interop network must be the fixed staging network")
    _env("STAGING_EDGE_CONTAINER_NAME", EDGE_CONTAINER)
    result = _run(_compose("config", "--quiet"))
    if result["status"] == "PASS":
        connection = _edge_connection()
        if connection["status"] != "PASS":
            return {"status": "FAIL", "network": NETWORK, "edge_container": EDGE_CONTAINER, "edge_connected": False}
        result["network"] = NETWORK
        result["edge_container"] = EDGE_CONTAINER
        result["edge_connected"] = True
        result["external_export"] = "disabled"
    return result


def scenario(scenario_id: str) -> dict[str, Any]:
    if scenario_id not in SCENARIOS:
        raise QualificationControllerError("unknown bounded staging scenario")
    result = preflight()
    if result["status"] == "PASS":
        fault_command = FAULT_PHASES.get(scenario_id)
        if fault_command is not None:
            fault_result = _run(_compose(*fault_command))
            if fault_result["status"] != "PASS":
                return {"status": "FAIL", "scenario_id": scenario_id, "fault_injection": "failed"}
        # Lost ACK and Edge-specific watchdog/spool faults require the approved Edge proxy procedure.
        # The controller records them as NOT_RUN until that real procedure supplies evidence.
        result.update(
            {
                "scenario_id": scenario_id,
                "fault_injection": "staging-only-named-procedure",
                "status": "NOT_RUN",
            }
        )
    return result


def soak_check() -> dict[str, Any]:
    result = preflight()
    result.update({"command": "soak-check", "required_duration_seconds": 24 * 60 * 60, "status": "NOT_RUN"})
    return result


def finalize() -> dict[str, Any]:
    result = preflight()
    result.update({"command": "finalize", "report": "edge-core-compatibility.json", "status": "NOT_RUN"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded staging qualification controller")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    scenario_parser = sub.add_parser("scenario")
    scenario_parser.add_argument("scenario_id", choices=sorted(SCENARIOS))
    sub.add_parser("soak-check")
    sub.add_parser("finalize")
    args = parser.parse_args()
    try:
        commands = {
            "preflight": preflight,
            "scenario": lambda: scenario(args.scenario_id),
            "soak-check": soak_check,
            "finalize": finalize,
        }
        result = commands[args.command]()
    except (QualificationControllerError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
