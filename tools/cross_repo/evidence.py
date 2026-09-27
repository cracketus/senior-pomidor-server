"""Fail-closed software evidence gate, separate from staging qualification."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.cross_repo.runner import SCENARIOS


class EvidenceError(ValueError):
    pass


def validate_evidence(
    report: dict[str, Any],
    *,
    core_sha: str,
    edge_sha: str,
    core_image: str | None = None,
    edge_image: str | None = None,
) -> None:
    if (
        report.get("schema_version") != "senior-pomidor.cross-repo-e2e.v1"
        or report.get("status") != "PASS"
        or report.get("evidence_scope") != "CI"
        or report.get("future_action_invariants") != "NOT_IMPLEMENTED"
    ):
        raise EvidenceError("complete software PASS report required; no staging promotion")
    for owner, sha in (("core", core_sha), ("edge", edge_sha)):
        value = report.get(owner, {})
        expected_image = core_image if owner == "core" else edge_image
        if expected_image is not None and (
            not re.fullmatch(r"ghcr\.io/cracketus/[a-z0-9-]+@sha256:[0-9a-f]{64}", expected_image)
            or value.get("registry_ref") != expected_image
        ):
            raise EvidenceError("release image digest mismatch")
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or value.get("git_sha") != sha:
            raise EvidenceError("candidate identity mismatch")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("image_id", "")):
            raise EvidenceError("actual image identity missing")
    if not re.fullmatch(r"[0-9a-f]{64}", report.get("config_sha256", "")):
        raise EvidenceError("configuration identity missing")
    started = datetime.fromisoformat(report["started_at_utc"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(report["finished_at_utc"].replace("Z", "+00:00"))
    if started.tzinfo is None or finished.tzinfo is None or finished < started:
        raise EvidenceError("invalid evidence interval")
    scenarios = report.get("scenarios", [])
    names = [s["scenario_id"] for s in scenarios]
    if set(names) != set(SCENARIOS) or len(names) != len(SCENARIOS):
        raise EvidenceError("missing, extra or duplicate scenarios")
    pending_cases = {"core-outage-spool-growth", "edge-restart-pending", "fresh-during-backlog-replay"}
    for scenario in scenarios:
        counts = scenario["counts"]
        if set(counts) != {"generated", "persisted", "read_back", "duplicates", "missing", "unexpected"}:
            raise EvidenceError("counts missing")
        if any(type(v) is not int or not 0 <= v <= 256 for v in counts.values()):
            raise EvidenceError("invalid counts")
        pending = scenario["scenario_id"] in pending_cases
        if (
            scenario["status"] != "PASS"
            or scenario["pending_expected"] != pending
            or counts["generated"] == 0
            or counts["duplicates"]
            or counts["unexpected"]
            or counts["read_back"] != counts["persisted"]
            or counts["generated"] != counts["persisted"] + counts["missing"]
            or (not pending and counts["missing"])
        ):
            raise EvidenceError("incomplete scenario evidence")
    if report.get("cleanup_status") == "FAIL":
        raise EvidenceError("cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--core-sha", required=True)
    parser.add_argument("--edge-sha", required=True)
    parser.add_argument("--core-image")
    parser.add_argument("--edge-image")
    args = parser.parse_args()
    try:
        if args.report.stat().st_size > 65536:
            raise EvidenceError("report exceeds limit")
        validate_evidence(
            json.loads(args.report.read_text()),
            core_sha=args.core_sha,
            edge_sha=args.edge_sha,
            core_image=args.core_image,
            edge_image=args.edge_image,
        )
    except (OSError, ValueError, KeyError, TypeError):
        print("Cross-repository software evidence: FAIL")
        return 1
    print("Cross-repository software evidence: PASS (staging/soak/canary not implied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
