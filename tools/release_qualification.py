from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.edge_reliability import evaluate_edge_reliability
from app.models import Base, TelemetryEvent
from app.operator_edge_reliability import build_operator_edge_reliability
from app.services import persist_telemetry_result
from app.telemetry import normalize_system_health
from app.validation import ValidationError, validate_telemetry_payload

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "schemas"
CONTRACT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "contracts"

SCHEMAS = {
    "system-invariants": (
        "senior-pomidor.system-invariants.v1",
        SCHEMA_DIR / "system-invariants-v1.schema.json",
    ),
    "edge-core-compatibility": (
        "senior-pomidor.edge-core-compatibility-report.v1",
        SCHEMA_DIR / "edge-core-compatibility-report-v1.schema.json",
    ),
    "release-validation": (
        "senior-pomidor.release-validation.v1",
        SCHEMA_DIR / "release-validation-v1.schema.json",
    ),
}

SYSTEM_SCENARIOS = {
    "sp-inv-001",
    "sp-inv-002",
    "sp-inv-003",
    "sp-inv-004",
    "sp-inv-005",
    "sp-inv-006",
    "sp-inv-007",
    "sp-inv-008",
}
COMPATIBILITY_SCENARIOS = {
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
RELEASE_GATES = {
    "software-ci": "CI",
    "docker-compose-e2e": "CI",
    "cross-repository-staging": "STAGING",
    "exact-bundle-rehearsal": "REHEARSAL",
    "server-rollout-canary": "CANARY",
    "production-24h-observation": "PRODUCTION",
}
MINIMUM_GATE_DURATION_SECONDS = {
    "software-ci": 1,
    "docker-compose-e2e": 1,
    "cross-repository-staging": 24 * 60 * 60,
    "exact-bundle-rehearsal": 1,
    "server-rollout-canary": 60 * 60,
    "production-24h-observation": 24 * 60 * 60,
}
FORBIDDEN_REPORT_TERMS = {
    "boot_id",
    "service_name",
    "last_error_detail",
    "reason_detail",
    "recovery_reason",
    "raw_payload",
    "ssid",
    "ip_address",
    "database_path",
    "authorization: bearer",
    "private key",
}
PRIVATE_PATH_PATTERNS = (
    re.compile(r"[a-z]:\\\\", re.IGNORECASE),
    re.compile(r"(?:^|[\s\"'])/(?:home|srv|users|var)/(?:[^\s\"']+)", re.IGNORECASE),
    re.compile(r"\\\\[^\\\s]+\\[^\s]+"),
)


class QualificationError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"{path} must contain a JSON object")
    return value


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != UTC:
        raise QualificationError(f"timestamp must use UTC Z: {value}")
    return parsed


def _validate_scenarios(
    report: dict[str, Any],
    *,
    required: set[str],
    require_pass: bool,
    require_complete_counts: bool = False,
    check_report_status: bool = True,
) -> None:
    scenarios = report["scenarios"]
    identifiers = [scenario["scenario_id"] for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise QualificationError("scenario_id values must be unique")
    missing = sorted(required - set(identifiers))
    if missing:
        raise QualificationError(f"required scenarios missing: {', '.join(missing)}")

    implemented_statuses: list[str] = []
    for scenario in scenarios:
        started = _parse_utc(scenario["started_at_utc"])
        finished = _parse_utc(scenario["finished_at_utc"])
        if finished < started:
            raise QualificationError(f"scenario {scenario['scenario_id']} finishes before it starts")

        counts = scenario["counts"]
        if counts["persisted"] > counts["generated"]:
            raise QualificationError(f"scenario {scenario['scenario_id']} persisted count exceeds generated")
        if counts["read_back"] > counts["persisted"]:
            raise QualificationError(f"scenario {scenario['scenario_id']} read_back count exceeds persisted")
        if counts["duplicates"] > counts["generated"]:
            raise QualificationError(f"scenario {scenario['scenario_id']} duplicate count exceeds generated")

        for outcome in scenario["alert_outcomes"]:
            matches = outcome["expected"] == outcome["observed"]
            consistent = (
                (outcome["status"] == "PASS" and matches and outcome["observed"] != "NOT_RUN")
                or (outcome["status"] == "FAIL" and not matches)
                or (outcome["status"] == "NOT_RUN" and outcome["observed"] == "NOT_RUN")
            )
            if not consistent:
                raise QualificationError(
                    f"scenario {scenario['scenario_id']} alert {outcome['rule_id']} has inconsistent status"
                )
            if require_pass and scenario["applicability"] == "IMPLEMENTED" and outcome["status"] != "PASS":
                raise QualificationError(
                    f"required scenario {scenario['scenario_id']} alert {outcome['rule_id']} is {outcome['status']}"
                )

        if scenario["applicability"] == "NOT_IMPLEMENTED":
            if scenario["status"] != "NOT_RUN":
                raise QualificationError(f"scenario {scenario['scenario_id']} is not implemented but is not NOT_RUN")
            continue
        implemented_statuses.append(scenario["status"])
        if require_pass and scenario["status"] != "PASS":
            raise QualificationError(f"required scenario {scenario['scenario_id']} is {scenario['status']}")
        if require_pass and require_complete_counts:
            if counts["generated"] == 0:
                raise QualificationError(f"required scenario {scenario['scenario_id']} generated no observations")
            if counts["missing"] != 0:
                raise QualificationError(f"required scenario {scenario['scenario_id']} has missing observations")
            if counts["persisted"] != counts["generated"] or counts["read_back"] != counts["generated"]:
                raise QualificationError(
                    f"required scenario {scenario['scenario_id']} has incomplete persistence/read-back counts"
                )

    expected_status = "PASS"
    if "FAIL" in implemented_statuses:
        expected_status = "FAIL"
    elif "NOT_RUN" in implemented_statuses:
        expected_status = "NOT_RUN"
    if check_report_status and report["status"] != expected_status:
        raise QualificationError(f"report status {report['status']} does not match scenario status {expected_status}")


def validate_report(kind: str, report: dict[str, Any], *, require_pass: bool = False) -> None:
    if kind not in SCHEMAS:
        raise QualificationError(f"unknown report kind: {kind}")
    schema_version, schema_path = SCHEMAS[kind]
    schema = _load_json(schema_path)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
    if report["schema_version"] != schema_version:
        raise QualificationError(f"unexpected schema_version for {kind}")
    serialized = json.dumps(report, sort_keys=True).lower()
    forbidden = sorted(term for term in FORBIDDEN_REPORT_TERMS if term in serialized)
    if forbidden:
        raise QualificationError(f"report contains forbidden private field terms: {', '.join(forbidden)}")
    if any(pattern.search(serialized) for pattern in PRIVATE_PATH_PATTERNS):
        raise QualificationError("report contains a forbidden private filesystem path")

    required = SYSTEM_SCENARIOS if kind == "system-invariants" else set()
    if kind == "edge-core-compatibility":
        required = COMPATIBILITY_SCENARIOS
    _validate_scenarios(
        report,
        required=required,
        require_pass=require_pass,
        require_complete_counts=kind == "edge-core-compatibility",
        check_report_status=kind != "release-validation",
    )

    for owner in ("core", "edge"):
        revision = report[owner]
        if not revision["image_ref"].endswith(f"@{revision['image_digest']}"):
            raise QualificationError(f"{owner}.image_ref is not pinned to its declared immutable digest")

    if kind == "system-invariants":
        future_invariants = {
            scenario["scenario_id"]: scenario
            for scenario in report["scenarios"]
            if scenario["scenario_id"] in {"sp-inv-006", "sp-inv-007", "sp-inv-008"}
        }
        if any(scenario["applicability"] != "NOT_IMPLEMENTED" for scenario in future_invariants.values()):
            raise QualificationError("future action invariants must remain NOT_IMPLEMENTED until the subsystem exists")
    elif kind == "edge-core-compatibility" and require_pass:
        for scenario in report["scenarios"]:
            if scenario["evidence_scope"] not in {"STAGING", "REHEARSAL"}:
                raise QualificationError(
                    f"compatibility scenario {scenario['scenario_id']} lacks real staging evidence"
                )
    elif kind == "release-validation":
        gates = report["gates"]
        gate_ids = [gate["gate_id"] for gate in gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise QualificationError("gate_id values must be unique")
        missing_gates = sorted(set(RELEASE_GATES) - set(gate_ids))
        if missing_gates:
            raise QualificationError(f"required release gates missing: {', '.join(missing_gates)}")
        for gate in gates:
            started = _parse_utc(gate["started_at_utc"])
            finished = _parse_utc(gate["finished_at_utc"])
            if finished < started:
                raise QualificationError(f"gate {gate['gate_id']} finishes before it starts")
            expected_scope = RELEASE_GATES.get(gate["gate_id"])
            if require_pass and gate["status"] != "PASS":
                raise QualificationError(f"required gate {gate['gate_id']} is {gate['status']}")
            if require_pass and expected_scope is not None and gate["evidence_scope"] != expected_scope:
                raise QualificationError(f"gate {gate['gate_id']} must use {expected_scope} evidence")
            minimum_seconds = MINIMUM_GATE_DURATION_SECONDS.get(gate["gate_id"])
            if require_pass and minimum_seconds is not None and (finished - started).total_seconds() < minimum_seconds:
                raise QualificationError(
                    f"gate {gate['gate_id']} is shorter than its required {minimum_seconds}-second duration"
                )
        statuses = [gate["status"] for gate in gates]
        statuses.extend(
            scenario["status"] for scenario in report["scenarios"] if scenario["applicability"] == "IMPLEMENTED"
        )
        expected = "FAIL" if "FAIL" in statuses else "NOT_RUN" if "NOT_RUN" in statuses else "PASS"
        if report["status"] != expected:
            raise QualificationError(f"report status {report['status']} does not match gate status {expected}")


def validate_identity(
    report: dict[str, Any],
    *,
    core_sha: str | None = None,
    core_image: str | None = None,
    core_digest: str | None = None,
    edge_sha: str | None = None,
    edge_image: str | None = None,
    edge_digest: str | None = None,
) -> None:
    expected = (
        ("core", "git_sha", core_sha),
        ("core", "image_ref", core_image),
        ("core", "image_digest", core_digest),
        ("edge", "git_sha", edge_sha),
        ("edge", "image_ref", edge_image),
        ("edge", "image_digest", edge_digest),
    )
    for owner, field, value in expected:
        if value is not None and report[owner][field] != value:
            raise QualificationError(f"{owner}.{field} does not match the requested immutable candidate")


def _revision(git_sha: str, image_ref: str, image_digest: str) -> dict[str, str]:
    return {"git_sha": git_sha, "image_ref": image_ref, "image_digest": image_digest}


def _counts(
    *, generated: int, persisted: int = 0, read_back: int = 0, duplicates: int = 0, missing: int = 0, unknown: int = 0
) -> dict[str, int]:
    return {
        "generated": generated,
        "persisted": persisted,
        "read_back": read_back,
        "duplicates": duplicates,
        "missing": missing,
        "unknown": unknown,
    }


def _scenario(
    scenario_id: str,
    started: str,
    *,
    counts: dict[str, int],
    status: str = "PASS",
    applicability: str = "IMPLEMENTED",
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "applicability": applicability,
        "evidence_scope": "CI",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": status,
        "counts": counts,
        "alert_outcomes": [],
        "notes": notes or [],
    }


def _healthy_system_health() -> dict[str, Any]:
    return {
        "watchdog": {"state": "healthy", "result": "healthy", "suppression": False, "configured": True},
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 0,
            "backlog_count": 0,
            "worker_state": "running",
        },
        "application": {
            "process_running": True,
            "systemd_available": True,
            "systemd_service_active": True,
            "systemd_active_state": "active",
        },
    }


def _event(observed_at: datetime | str, health: dict[str, Any]) -> TelemetryEvent:
    return TelemetryEvent(
        id=1,
        record_id="qualification:synthetic:1",
        device_id="qualification-edge",
        timestamp_utc=observed_at,
        schema_version="senior-pomidor.edge.telemetry.v2",
        source="synthetic",
        raw_payload_jsonb={"private": "excluded"},
        system_health_jsonb=health,
        received_at=datetime.now(UTC),
    )


def _persistence_invariant_scenarios(started: str) -> list[dict[str, Any]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    payload = _load_json(CONTRACT_FIXTURE_DIR / "telemetry_v2.json")
    expected_observed = payload["timestamp_utc"]
    try:
        with session_local() as db:
            accepted = persist_telemetry_result(db, payload, source="qualification")
            duplicate = persist_telemetry_result(db, payload, source="qualification-replay")
            stored_count = db.scalar(select(func.count()).select_from(TelemetryEvent))
            stored = db.scalar(select(TelemetryEvent).where(TelemetryEvent.record_id == payload["record_id"]))
            if (
                accepted.outcome != "accepted"
                or duplicate.outcome != "duplicate"
                or stored_count != 1
                or stored is None
            ):
                raise QualificationError("durability or duplicate persistence invariant failed")
            stored_timestamp = stored.timestamp_utc
            if stored_timestamp.tzinfo is None:
                stored_timestamp = stored_timestamp.replace(tzinfo=UTC)
            stored_observed = stored_timestamp.isoformat().replace("+00:00", "Z")
            if stored_observed != expected_observed:
                raise QualificationError("physical observation timestamp was rewritten")

            earlier = deepcopy(payload)
            earlier["record_id"] = f"{payload['record_id']}:earlier"
            earlier["timestamp_utc"] = "2026-07-01T12:00:00Z"
            persist_telemetry_result(db, earlier, source="qualification-delayed-replay")
            ordered = list(
                db.scalars(
                    select(TelemetryEvent)
                    .where(TelemetryEvent.device_id == payload["device_id"])
                    .order_by(TelemetryEvent.timestamp_utc.asc())
                )
            )
            if [event.record_id for event in ordered] != [earlier["record_id"], payload["record_id"]]:
                raise QualificationError("out-of-order replay did not preserve observation ordering")
    finally:
        engine.dispose()

    return [
        _scenario("sp-inv-001", started, counts=_counts(generated=1, persisted=1, read_back=1)),
        _scenario(
            "sp-inv-002",
            started,
            counts=_counts(generated=2, persisted=1, read_back=1, duplicates=1),
        ),
        _scenario("sp-inv-003", started, counts=_counts(generated=2, persisted=2, read_back=2)),
    ]


def build_system_invariants_report(
    *, core_sha: str, core_image: str, core_digest: str, edge_sha: str, edge_image: str, edge_digest: str
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    scenarios = _persistence_invariant_scenarios(started)
    for version in ("v1", "v2"):
        fixture = _load_json(CONTRACT_FIXTURE_DIR / f"telemetry_{version}.json")
        validate_telemetry_payload(fixture)
        if json.loads(json.dumps(fixture, sort_keys=True)) != fixture:
            raise QualificationError(f"telemetry {version} did not round-trip")
    malformed = deepcopy(_load_json(CONTRACT_FIXTURE_DIR / "telemetry_v2.json"))
    malformed["timestamp_utc"] = "invalid"
    try:
        validate_telemetry_payload(malformed)
    except ValidationError:
        pass
    else:
        raise QualificationError("invalid telemetry did not fail explicitly")
    scenarios.append(_scenario("sp-inv-005", started, counts=_counts(generated=3)))

    now = datetime.now(UTC).replace(microsecond=0)
    health = _healthy_system_health()
    freshness = [
        build_operator_edge_reliability(_event(now, health), now=now).freshness.status,
        build_operator_edge_reliability(_event(now - timedelta(seconds=1200), health), now=now).freshness.status,
        build_operator_edge_reliability(
            _event(now - timedelta(seconds=1200, microseconds=1), health), now=now
        ).freshness.status,
        build_operator_edge_reliability(_event(now + timedelta(microseconds=1), health), now=now).freshness.status,
        build_operator_edge_reliability(_event("invalid", health), now=now).freshness.status,
    ]
    if freshness != ["FRESH", "FRESH", "STALE", "UNKNOWN", "UNKNOWN"]:
        raise QualificationError(f"unexpected freshness boundary results: {freshness}")
    scenarios.append(_scenario("freshness-boundaries", started, counts=_counts(generated=5, unknown=2)))

    evaluations = [evaluate_edge_reliability(None), evaluate_edge_reliability({"watchdog": {"state": "mystery"}})]
    if any(result.status == "OK" for result in evaluations):
        raise QualificationError("missing or unknown reliability became OK")
    stale = build_operator_edge_reliability(_event(now - timedelta(seconds=1201), health), now=now)
    if stale.status != "UNKNOWN":
        raise QualificationError("stale reliability did not fail safe")
    scenarios.append(_scenario("sp-inv-004", started, counts=_counts(generated=8, missing=1, unknown=5)))

    private_health = deepcopy(health)
    private_health["watchdog"].update({"reason": "private-reason", "boot_id": "private-boot"})
    private_health["spool"].update({"last_error_detail": "private-detail", "database_path": "/private"})
    private_health["application"].update({"systemd_service_name": "private-service", "process_id": 42})
    payload = {"system_health": private_health}
    normalized = normalize_system_health(payload)
    serialized = build_operator_edge_reliability(_event(now, normalized or {}), now=now).model_dump_json()
    forbidden = ("private-reason", "private-boot", "private-detail", "/private", "private-service", "process_id")
    if any(value in serialized for value in forbidden):
        raise QualificationError("private reliability field crossed the operator allowlist")
    scenarios.append(_scenario("privacy-allowlist", started, counts=_counts(generated=1)))

    for invariant_id in ("sp-inv-006", "sp-inv-007", "sp-inv-008"):
        scenarios.append(
            _scenario(
                invariant_id,
                started,
                counts=_counts(generated=0),
                status="NOT_RUN",
                applicability="NOT_IMPLEMENTED",
                notes=["Future action/control invariant remains NOT_IMPLEMENTED; no physical path was exercised."],
            )
        )
    report = {
        "schema_version": "senior-pomidor.system-invariants.v1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "core": _revision(core_sha, core_image, core_digest),
        "edge": _revision(edge_sha, edge_image, edge_digest),
        "scenarios": scenarios,
    }
    validate_report("system-invariants", report, require_pass=True)
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and validate bounded Senior Pomidor release evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one report and its semantic gates")
    validate.add_argument("--kind", choices=sorted(SCHEMAS), required=True)
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--require-pass", action="store_true")
    validate.add_argument("--core-sha")
    validate.add_argument("--core-image")
    validate.add_argument("--core-digest")
    validate.add_argument("--edge-sha")
    validate.add_argument("--edge-image")
    validate.add_argument("--edge-digest")

    generate = subparsers.add_parser("system-invariants", help="run applicable deterministic invariants")
    generate.add_argument("--core-sha", required=True)
    generate.add_argument("--core-image", required=True)
    generate.add_argument("--core-digest", required=True)
    generate.add_argument("--edge-sha", required=True)
    generate.add_argument("--edge-image", required=True)
    generate.add_argument("--edge-digest", required=True)
    generate.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            report = _load_json(args.report)
            validate_report(args.kind, report, require_pass=args.require_pass)
            validate_identity(
                report,
                core_sha=args.core_sha,
                core_image=args.core_image,
                core_digest=args.core_digest,
                edge_sha=args.edge_sha,
                edge_image=args.edge_image,
                edge_digest=args.edge_digest,
            )
        else:
            report = build_system_invariants_report(
                core_sha=args.core_sha,
                core_image=args.core_image,
                core_digest=args.core_digest,
                edge_sha=args.edge_sha,
                edge_image=args.edge_image,
                edge_digest=args.edge_digest,
            )
            _write_report(args.output, report)
    except (QualificationError, JsonSchemaValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "PASS", "command": args.command}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
