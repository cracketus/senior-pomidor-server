from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RELIABILITY_STATUSES = ("ALERT", "WARN", "UNKNOWN", "OK")


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

    findings: list[ReliabilityFinding] = []
    if process_running is False:
        findings.append(_finding(metric, "ALERT", "process_stopped", "Edge application process is stopped"))
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


def evaluate_edge_reliability(system_health: dict[str, Any] | None) -> EdgeReliabilityEvaluation:
    health = system_health if isinstance(system_health, dict) else {}
    watchdog_findings = _watchdog_findings(health.get("watchdog"))
    spool_findings = _spool_findings(health.get("spool"))
    application_findings = _application_findings(health.get("application"))
    findings = _deduplicate(watchdog_findings + spool_findings + application_findings)
    return EdgeReliabilityEvaluation(
        status=_status(findings),
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
