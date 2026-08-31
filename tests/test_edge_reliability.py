import pytest

from app.edge_reliability import evaluate_edge_reliability, reliability_alerts


def healthy_health() -> dict:
    return {
        "watchdog": {
            "state": "healthy",
            "result": "healthy",
            "suppression": False,
            "configured": True,
        },
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 0,
            "backlog_count": 0,
            "in_flight_count": 0,
            "worker_state": "running",
        },
        "application": {
            "service_manager": "systemd",
            "process_running": True,
            "systemd_available": True,
            "systemd_service_active": True,
            "systemd_active_state": "active",
        },
    }


@pytest.mark.parametrize(
    ("patch", "status", "code"),
    [
        ({"state": "starting"}, "WARN", "edge_watchdog_starting"),
        ({"state": "cooldown"}, "WARN", "edge_watchdog_cooldown"),
        ({"state": "maintenance"}, "WARN", "edge_watchdog_maintenance"),
        (
            {"state": "recovering", "result": "restart_accepted"},
            "WARN",
            "edge_watchdog_restart_recovery",
        ),
        (
            {"state": "recovering", "result": "reboot_accepted"},
            "WARN",
            "edge_watchdog_reboot_recovery",
        ),
        ({"state": "recovered"}, "WARN", "edge_watchdog_recovered"),
        ({"state": "suppression_cleared"}, "WARN", "edge_watchdog_suppression_cleared"),
        ({"state": "restart_failed"}, "ALERT", "edge_watchdog_restart_failed"),
        ({"state": "reboot_failed"}, "ALERT", "edge_watchdog_reboot_failed"),
        ({"state": "probe_failed"}, "ALERT", "edge_watchdog_recovery_failed"),
        ({"state": "budget_exhausted"}, "ALERT", "edge_watchdog_budget_exhausted"),
        ({"state": "recovery_suppressed"}, "ALERT", "edge_watchdog_recovery_suppressed"),
        ({"state": "mystery"}, "UNKNOWN", "edge_watchdog_unrecognized"),
    ],
)
def test_watchdog_state_mapping(patch, status, code) -> None:
    health = healthy_health()
    health["watchdog"].update(patch)

    result = evaluate_edge_reliability(health)

    assert result.watchdog_status == status
    assert code in [finding.reason_code for finding in result.findings]


def test_watchdog_suppression_wins_and_configured_false_is_normal() -> None:
    suppressed = healthy_health()
    suppressed["watchdog"].update({"suppression": True, "reason": "private/path"})
    disabled = healthy_health()
    disabled["watchdog"] = {"configured": False}

    suppressed_result = evaluate_edge_reliability(suppressed)
    disabled_result = evaluate_edge_reliability(disabled)

    assert suppressed_result.status == "ALERT"
    assert suppressed_result.findings[0].reason_code == "edge_watchdog_suppressed"
    assert "private/path" not in str(suppressed_result)
    assert disabled_result.watchdog_status == "OK"


@pytest.mark.parametrize(
    ("patch", "status", "code"),
    [
        ({"status": "BACKLOG"}, "WARN", "edge_spool_backlog"),
        ({"pending_count": 1}, "WARN", "edge_spool_backlog"),
        ({"disk_status": "WARNING"}, "WARN", "edge_spool_disk_warning"),
        ({"status": "DEGRADED"}, "ALERT", "edge_spool_degraded"),
        ({"status": "CRITICAL"}, "ALERT", "edge_spool_critical"),
        ({"disk_status": "DEGRADED"}, "ALERT", "edge_spool_disk_degraded"),
        ({"disk_status": "CRITICAL"}, "ALERT", "edge_spool_disk_critical"),
        ({"worker_state": "error"}, "ALERT", "edge_spool_worker_error"),
        ({"status": "MYSTERY"}, "UNKNOWN", "edge_spool_unrecognized"),
    ],
)
def test_spool_state_mapping(patch, status, code) -> None:
    health = healthy_health()
    health["spool"].update(patch)

    result = evaluate_edge_reliability(health)

    assert result.spool_status == status
    assert code in [finding.reason_code for finding in result.findings]


@pytest.mark.parametrize(
    ("patch", "status", "code"),
    [
        ({"process_running": False}, "ALERT", "edge_application_process_stopped"),
        ({"systemd_service_active": False}, "ALERT", "edge_application_service_inactive"),
        ({"systemd_available": False}, "WARN", "edge_application_systemd_unavailable"),
        (
            {"systemd_service_active": True, "systemd_active_state": "inactive"},
            "WARN",
            "edge_application_service_state_conflict",
        ),
    ],
)
def test_application_state_mapping(patch, status, code) -> None:
    health = healthy_health()
    health["application"].update(patch)

    result = evaluate_edge_reliability(health)

    assert result.application_status == status
    assert code in [finding.reason_code for finding in result.findings]


def test_missing_and_partial_blocks_are_unknown_but_not_alerts() -> None:
    missing = evaluate_edge_reliability(None)
    partial = evaluate_edge_reliability({"application": {"process_running": True}})

    assert missing.status == "UNKNOWN"
    assert [finding.reason_code for finding in missing.findings] == [
        "edge_watchdog_missing",
        "edge_spool_missing",
        "edge_application_missing",
    ]
    assert partial.application_status == "UNKNOWN"
    assert reliability_alerts(missing) == []


def test_independent_alerts_survive_incomplete_blocks() -> None:
    health = healthy_health()
    health["watchdog"] = {"suppression": True}
    health["spool"] = {"disk_status": "CRITICAL", "worker_state": "error"}
    health["application"] = {"process_running": False}

    result = evaluate_edge_reliability(health)
    codes = [finding.reason_code for finding in result.findings]

    assert result.status == "ALERT"
    assert "edge_watchdog_suppressed" in codes
    assert "edge_watchdog_missing" in codes
    assert "edge_spool_disk_critical" in codes
    assert "edge_spool_worker_error" in codes
    assert "edge_spool_missing" in codes
    assert "edge_application_process_stopped" in codes
    assert "edge_application_incomplete" not in codes


@pytest.mark.parametrize(
    ("state", "expected_status", "reason_code"),
    [
        ("OK", "OK", None),
        ("STARTUP", "WARN", "edge_health_aggregate_startup"),
        ("BACKLOG", "WARN", "edge_health_aggregate_backlog"),
        ("DEGRADED", "WARN", "edge_health_aggregate_degraded"),
        ("MAINTENANCE", "WARN", "edge_health_aggregate_maintenance"),
        ("CRITICAL", "ALERT", "edge_health_aggregate_critical"),
    ],
)
def test_process_only_application_and_canonical_aggregate(state, expected_status, reason_code) -> None:
    health = healthy_health()
    health["application"] = {"service_manager": "none", "process_running": True}
    health["aggregate"] = {"schema_version": "senior-pomidor.edge.health.v1", "state": state, "reasons": ["bounded"]}
    result = evaluate_edge_reliability(health)

    assert result.application_status == "OK"
    assert result.status == expected_status
    if reason_code:
        assert reason_code in [finding.reason_code for finding in result.findings]


@pytest.mark.parametrize(
    ("application", "expected_status", "reason_code"),
    [
        ({"process_running": True}, "UNKNOWN", "edge_application_incomplete"),
        ({"service_manager": "none", "process_running": True}, "OK", None),
        (
            {"service_manager": "none", "process_running": True, "systemd_available": False},
            "UNKNOWN",
            "edge_application_service_manager_conflict",
        ),
        ({"service_manager": "systemd", "process_running": True}, "UNKNOWN", "edge_application_incomplete"),
        (
            {"service_manager": ["none"], "process_running": True},
            "UNKNOWN",
            "edge_application_unrecognized",
        ),
        (
            {
                "service_manager": None,
                "process_running": True,
                "systemd_available": True,
                "systemd_service_active": True,
                "systemd_active_state": "active",
            },
            "UNKNOWN",
            "edge_application_unrecognized",
        ),
    ],
)
def test_application_service_manager_discriminator(application, expected_status, reason_code) -> None:
    result = evaluate_edge_reliability({"application": application})

    assert result.application_status == expected_status
    if reason_code:
        assert reason_code in [finding.reason_code for finding in result.findings]


@pytest.mark.parametrize("aggregate_state", ["STARTUP", "BACKLOG", "DEGRADED", "MAINTENANCE"])
def test_component_unknown_takes_precedence_over_aggregate_warning(aggregate_state: str) -> None:
    health = healthy_health()
    health["spool"] = {}
    health["aggregate"] = {
        "schema_version": "senior-pomidor.edge.health.v1",
        "state": aggregate_state,
        "reasons": [],
    }

    result = evaluate_edge_reliability(health)

    assert result.spool_status == "UNKNOWN"
    assert result.status == "UNKNOWN"
    assert "edge_spool_missing" in [finding.reason_code for finding in result.findings]
    assert f"edge_health_aggregate_{aggregate_state.lower()}" in [finding.reason_code for finding in result.findings]


def test_process_only_stopped_or_malformed_state_fails_safe() -> None:
    stopped = evaluate_edge_reliability({"application": {"process_running": False}})
    missing = evaluate_edge_reliability({"application": {}})
    malformed = evaluate_edge_reliability({"application": {"process_running": True}, "aggregate": {}})

    assert stopped.application_status == "ALERT"
    assert missing.application_status == "UNKNOWN"
    assert malformed.status == "UNKNOWN"
    assert "edge_health_aggregate_invalid" in [finding.reason_code for finding in malformed.findings]


def test_legacy_systemd_mode_requires_existing_boolean_contract() -> None:
    health = {
        "application": {
            "process_running": True,
            "systemd_service_name": "senior-pomidor.service",
            "systemd_available": True,
            "systemd_service_active": True,
            "systemd_active_state": "active",
        }
    }
    assert evaluate_edge_reliability(health).application_status == "OK"
    del health["application"]["systemd_service_active"]
    assert evaluate_edge_reliability(health).application_status == "UNKNOWN"


def test_findings_are_deterministic_deduplicated_and_use_severity_precedence() -> None:
    health = healthy_health()
    health["watchdog"].update({"state": "suppressed", "suppression": True})
    health["spool"].update({"status": "BACKLOG", "pending_count": 2, "backlog_count": 3})
    del health["application"]["systemd_service_active"]

    result = evaluate_edge_reliability(health)

    assert result.status == "ALERT"
    assert [finding.reason_code for finding in result.findings] == [
        "edge_watchdog_suppressed",
        "edge_spool_backlog",
        "edge_application_incomplete",
    ]
    assert reliability_alerts(result) == [
        {
            "metric": "edge_watchdog",
            "level": "critical",
            "reason_code": "edge_watchdog_suppressed",
            "message": "Edge watchdog recovery is suppressed",
        },
        {
            "metric": "edge_spool",
            "level": "warning",
            "reason_code": "edge_spool_backlog",
            "message": "Edge spool has an active backlog",
        },
    ]
