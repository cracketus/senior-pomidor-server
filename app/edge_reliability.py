from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RELIABILITY_STATUSES = ("ALERT", "WARN", "UNKNOWN", "OK")
HEALTH_AGGREGATE_SCHEMA_VERSION = "senior-pomidor.edge.health.v1"
HEALTH_AGGREGATE_STATES = {"STARTUP", "OK", "BACKLOG", "DEGRADED", "MAINTENANCE", "CRITICAL"}


@dataclass(frozen=True)
class ReliabilityFinding:
    metric: str
    status: str
    reason_code: str
    message: str


@dataclass(frozen=True)
class EdgeReliabilityEvaluation:
    status: str
    watchdog_status: str
    spool_status: str
    application_status: str
    findings: tuple[ReliabilityFinding, ...]


def _status(findings: list[ReliabilityFinding]) -> str:
    for status in RELIABILITY_STATUSES:
        if any(finding.status == status for finding in findings):
            return status
    return "OK"


def _finding(metric: str, status: str, suffix: str, message: str) -> ReliabilityFinding:
    return ReliabilityFinding(
        metric=metric,
        status=status,
        reason_code=f"{metric}_{suffix}",
        message=message,
    )


def _deduplicate(findings: list[ReliabilityFinding]) -> list[ReliabilityFinding]:
    result: list[ReliabilityFinding] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.reason_code not in seen:
            result.append(finding)
            seen.add(finding.reason_code)
    return result


def _watchdog_findings(value: Any) -> list[ReliabilityFinding]:
    metric = "edge_watchdog"
    if not isinstance(value, dict) or not value:
        return [_finding(metric, "UNKNOWN", "missing", "Edge watchdog state is unavailable")]
    if value.get("configured") is False:
        return []

    state = value.get("state")
    result = value.get("result")
    suppression = value.get("suppression")
    findings: list[ReliabilityFinding] = []
    if suppression is True or state == "suppressed":
        findings.append(_finding(metric, "ALERT", "suppressed", "Edge watchdog recovery is suppressed"))
    if state == "budget_exhausted" or result == "budget_exhausted":
        findings.append(_finding(metric, "ALERT", "budget_exhausted", "Edge watchdog recovery budget is exhausted"))
    if state == "recovery_suppressed" or result == "recovery_suppressed":
        findings.append(_finding(metric, "ALERT", "recovery_suppressed", "Edge watchdog recovery was suppressed"))

    failed_value = result if isinstance(result, str) and result.endswith("_failed") else state
    if isinstance(failed_value, str) and failed_value.endswith("_failed"):
        if failed_value.startswith("restart"):
            suffix, message = "restart_failed", "Edge watchdog restart recovery failed"
        elif failed_value.startswith("reboot"):
            suffix, message = "reboot_failed", "Edge watchdog reboot recovery failed"
        else:
            suffix, message = "recovery_failed", "Edge watchdog recovery failed"
        findings.append(_finding(metric, "ALERT", suffix, message))

    if not isinstance(state, str):
        findings.append(_finding(metric, "UNKNOWN", "missing", "Edge watchdog state is unavailable"))
    elif state == "recovering":
        if isinstance(result, str) and result.startswith("reboot"):
            findings.append(_finding(metric, "WARN", "reboot_recovery", "Edge watchdog reboot recovery is in progress"))
        elif isinstance(result, str) and result.startswith("restart"):
            findings.append(
                _finding(metric, "WARN", "restart_recovery", "Edge watchdog restart recovery is in progress")
            )
        else:
            findings.append(_finding(metric, "WARN", "recovering", "Edge watchdog recovery is in progress"))
    elif state in {"starting", "cooldown", "maintenance"}:
        messages = {
            "starting": "Edge watchdog is starting",
            "cooldown": "Edge watchdog recovery is cooling down",
            "maintenance": "Edge watchdog is in maintenance mode",
        }
        findings.append(_finding(metric, "WARN", state, messages[state]))
    elif state == "recovered" or result == "recovered":
        findings.append(_finding(metric, "WARN", "recovered", "Edge watchdog has just recovered"))
    elif state == "suppression_cleared" or result == "suppression_cleared":
        findings.append(_finding(metric, "WARN", "suppression_cleared", "Edge watchdog suppression was just cleared"))

    known_states = {
        "healthy",
        "starting",
        "cooldown",
        "maintenance",
        "recovering",
        "suppressed",
        "budget_exhausted",
        "recovery_suppressed",
        "recovered",
        "suppression_cleared",
    }
    if isinstance(state, str) and state not in known_states and not state.endswith("_failed"):
        findings.append(_finding(metric, "UNKNOWN", "unrecognized", "Edge watchdog state is unrecognized"))
    return _deduplicate(findings)


def _positive_count(value: dict[str, Any], field: str) -> bool:
    count = value.get(field)
    return isinstance(count, int) and not isinstance(count, bool) and count > 0


def _spool_findings(value: Any) -> list[ReliabilityFinding]:
    metric = "edge_spool"
    if not isinstance(value, dict) or not value:
        return [_finding(metric, "UNKNOWN", "missing", "Edge spool state is unavailable")]
    reported = value.get("status")
    disk = value.get("disk_status")
    worker = value.get("worker_state")
    findings: list[ReliabilityFinding] = []
    if reported == "CRITICAL":
        findings.append(_finding(metric, "ALERT", "critical", "Edge spool is critical"))
    elif reported == "DEGRADED":
        findings.append(_finding(metric, "ALERT", "degraded", "Edge spool is degraded"))
    if disk == "CRITICAL":
        findings.append(_finding(metric, "ALERT", "disk_critical", "Edge spool disk is critical"))
    elif disk == "DEGRADED":
        findings.append(_finding(metric, "ALERT", "disk_degraded", "Edge spool disk is degraded"))
    if worker == "error":
        findings.append(_finding(metric, "ALERT", "worker_error", "Edge spool worker reported an error"))

    if reported == "BACKLOG" or any(
        _positive_count(value, field) for field in ("pending_count", "backlog_count", "in_flight_count")
    ):
        findings.append(_finding(metric, "WARN", "backlog", "Edge spool has an active backlog"))
    if disk == "WARNING":
        findings.append(_finding(metric, "WARN", "disk_warning", "Edge spool disk reported a warning"))

    active_counts = [value.get(field) for field in ("pending_count", "backlog_count", "in_flight_count")]
    known_status = reported in {"OK", "BACKLOG", "DEGRADED", "CRITICAL"}
    known_disk = disk in {"OK", "WARNING", "DEGRADED", "CRITICAL"}
    counts_complete = all(isinstance(count, int) and not isinstance(count, bool) for count in active_counts)
    if not isinstance(reported, str):
        findings.append(_finding(metric, "UNKNOWN", "missing", "Edge spool state is unavailable"))
    elif not known_status or not known_disk:
        findings.append(_finding(metric, "UNKNOWN", "unrecognized", "Edge spool state is incomplete or unrecognized"))
    elif not counts_complete:
        findings.append(_finding(metric, "UNKNOWN", "incomplete", "Edge spool state is incomplete or unrecognized"))
    return _deduplicate(findings)


def _application_findings(value: Any) -> list[ReliabilityFinding]:
    metric = "edge_application"
    if not isinstance(value, dict) or not value:
        return [_finding(metric, "UNKNOWN", "missing", "Edge application state is unavailable")]
    process_running = value.get("process_running")
    systemd_available = value.get("systemd_available")
    service_active = value.get("systemd_service_active")
    active_state = value.get("systemd_active_state")
    service_manager = value.get("service_manager")
    has_service_manager = "service_manager" in value
    systemd_fields = (
        "systemd_available",
        "systemd_service_name",
        "systemd_active_state",
        "systemd_sub_state",
        "systemd_service_active",
        "systemd_main_pid",
    )
    has_systemd_evidence = any(field in value for field in systemd_fields)

    findings: list[ReliabilityFinding] = []
    if process_running is False:
        findings.append(_finding(metric, "ALERT", "process_stopped", "Edge application process is stopped"))
    if service_manager == "none":
        if has_systemd_evidence:
            findings.append(
                _finding(
                    metric,
                    "UNKNOWN",
                    "service_manager_conflict",
                    "Edge application service manager state is contradictory",
                )
            )
        elif not isinstance(process_running, bool):
            findings.append(_finding(metric, "UNKNOWN", "incomplete", "Edge application process state is incomplete"))
        return _deduplicate(findings)
    if has_service_manager and service_manager not in ("none", "systemd"):
        findings.append(_finding(metric, "UNKNOWN", "unrecognized", "Edge application service manager is unrecognized"))
        return _deduplicate(findings)
    if not has_service_manager and not has_systemd_evidence:
        if not isinstance(process_running, bool):
            findings.append(_finding(metric, "UNKNOWN", "incomplete", "Edge application process state is incomplete"))
        elif process_running is True:
            findings.append(_finding(metric, "UNKNOWN", "incomplete", "Edge application state is incomplete"))
        return _deduplicate(findings)
    if service_active is False:
        findings.append(_finding(metric, "ALERT", "service_inactive", "Edge application systemd service is inactive"))
    if systemd_available is False:
        findings.append(
            _finding(metric, "WARN", "systemd_unavailable", "Edge application systemd state is unavailable")
        )

    contradictory = (
        (service_active is True and isinstance(active_state, str) and active_state != "active")
        or (service_active is False and active_state == "active")
        or (systemd_available is False and service_active is True)
    )
    if contradictory:
        findings.append(
            _finding(metric, "WARN", "service_state_conflict", "Edge application service state is contradictory")
        )

    complete = all(isinstance(item, bool) for item in (process_running, systemd_available, service_active))
    if not complete:
        findings.append(_finding(metric, "UNKNOWN", "incomplete", "Edge application state is incomplete"))
    elif not findings and active_state is not None and active_state != "active":
        findings.append(_finding(metric, "UNKNOWN", "unrecognized", "Edge application state is unrecognized"))
    return _deduplicate(findings)


def _aggregate_findings(value: Any) -> list[ReliabilityFinding]:
    metric = "edge_health_aggregate"
    if not isinstance(value, dict):
        return []
    if value.get("schema_version") != HEALTH_AGGREGATE_SCHEMA_VERSION:
        return [_finding(metric, "UNKNOWN", "invalid", "Edge health aggregate is invalid")]
    state = value.get("state")
    if state not in HEALTH_AGGREGATE_STATES:
        return [_finding(metric, "UNKNOWN", "invalid", "Edge health aggregate is invalid")]
    if state == "OK":
        return []
    status = "ALERT" if state == "CRITICAL" else "WARN"
    messages = {
        "STARTUP": "Edge health aggregate reports startup",
        "BACKLOG": "Edge health aggregate reports backlog",
        "DEGRADED": "Edge health aggregate reports degradation",
        "MAINTENANCE": "Edge health aggregate reports maintenance",
        "CRITICAL": "Edge health aggregate reports a critical state",
    }
    return [_finding(metric, status, state.lower(), messages[state])]


def _overall_status(
    component_findings: list[ReliabilityFinding],
    aggregate_findings: list[ReliabilityFinding],
) -> str:
    if any(finding.status == "ALERT" for finding in component_findings):
        return "ALERT"
    if any(finding.status == "UNKNOWN" for finding in component_findings):
        return "UNKNOWN"
    return _status(component_findings + aggregate_findings)


def evaluate_edge_reliability(system_health: dict[str, Any] | None) -> EdgeReliabilityEvaluation:
    health = system_health if isinstance(system_health, dict) else {}
    watchdog_findings = _watchdog_findings(health.get("watchdog"))
    spool_findings = _spool_findings(health.get("spool"))
    application_findings = _application_findings(health.get("application"))
    aggregate_findings = _aggregate_findings(health.get("aggregate"))
    component_findings = _deduplicate(watchdog_findings + spool_findings + application_findings)
    findings = _deduplicate(component_findings + aggregate_findings)
    return EdgeReliabilityEvaluation(
        status=_overall_status(component_findings, aggregate_findings),
        watchdog_status=_status(watchdog_findings),
        spool_status=_status(spool_findings),
        application_status=_status(application_findings),
        findings=tuple(findings),
    )


def reliability_alerts(evaluation: EdgeReliabilityEvaluation) -> list[dict[str, str]]:
    levels = {"WARN": "warning", "ALERT": "critical"}
    return [
        {
            "metric": finding.metric,
            "level": levels[finding.status],
            "reason_code": finding.reason_code,
            "message": finding.message,
        }
        for finding in evaluation.findings
        if finding.status in levels
    ]
