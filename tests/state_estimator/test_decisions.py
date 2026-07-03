from datetime import UTC, datetime, timedelta

from app.state_estimator.decisions import build_action_simulation, build_guardrails, format_ts

NOW = datetime(2026, 7, 2, 8, 0, tzinfo=UTC)


def state(**overrides):
    payload = {
        "schema_version": "state_v1",
        "state_id": "state-1",
        "node_id": "pi-001",
        "ts": format_ts(NOW),
        "quality": {"level": "GOOD"},
        "env": {"air_temp_c": 24.0, "vpd_kpa": 1.0},
    }
    payload.update(overrides)
    return payload


def health(status: str = "OK", optional_status: str = "NOT_PRESENT"):
    return {
        "schema_version": "sensor_health_v1",
        "node_id": "pi-001",
        "sensors": [
            {"sensor_type": "air_temp_rh", "sensor_id": "air", "status": status},
            {"sensor_type": "soil_moisture", "sensor_id": "pod-1.soil_moisture", "status": "OK"},
            {"sensor_type": "co2", "sensor_id": "co2_01", "status": optional_status},
        ],
    }


def anomaly(type_: str, severity: str = "HIGH"):
    return {"schema_version": "anomaly_v1", "type": type_, "severity": severity, "status": "ACTIVE"}


def test_guardrails_block_on_missing_stale_unsafe_and_required_sensor_failure() -> None:
    missing = build_guardrails(node_id="pi-001", state=None, sensor_health=None, active_anomalies=[], now=NOW)
    assert missing["allowed"] is False
    assert "missing_state" in missing["blocking_reasons"]

    stale = build_guardrails(
        node_id="pi-001",
        state=state(ts=format_ts(NOW - timedelta(minutes=21))),
        sensor_health=health(),
        active_anomalies=[],
        now=NOW,
    )
    assert "stale_state" in stale["blocking_reasons"]

    unsafe = build_guardrails(
        node_id="pi-001",
        state=state(quality={"level": "UNSAFE_FOR_AUTONOMY"}),
        sensor_health=health(status="STALE"),
        active_anomalies=[anomaly("DEVICE_DISCONNECTED")],
        now=NOW,
    )
    assert unsafe["allowed"] is False
    assert "unsafe_for_autonomy" in unsafe["blocking_reasons"]
    assert "active_anomaly_device_disconnected" in unsafe["blocking_reasons"]
    assert "required_sensor_air_temp_rh_stale" in unsafe["blocking_reasons"]


def test_guardrails_caution_on_degraded_state_warning_anomaly_and_optional_missing() -> None:
    guardrails = build_guardrails(
        node_id="pi-001",
        state=state(quality={"level": "DEGRADED"}),
        sensor_health=health(),
        active_anomalies=[anomaly("HIGH_VPD", severity="WARN")],
        now=NOW,
    )

    assert guardrails["allowed"] is True
    assert guardrails["level"] == "CAUTION"
    assert "state_quality_degraded" in guardrails["caution_reasons"]
    assert "warning_anomaly_high_vpd" in guardrails["caution_reasons"]
    assert "optional_sensor_co2_not_present" in guardrails["caution_reasons"]


def test_action_simulation_allows_only_read_only_decisions_and_never_waters() -> None:
    guardrails = build_guardrails(
        node_id="pi-001",
        state=state(),
        sensor_health=health(optional_status="OK"),
        active_anomalies=[],
        now=NOW,
    )
    simulations = [
        build_action_simulation(node_id="pi-001", guardrails=guardrails, state=state(), active_anomalies=[], now=NOW),
        build_action_simulation(
            node_id="pi-001",
            guardrails=guardrails,
            state=state(),
            active_anomalies=[anomaly("CRITICAL_HEAT", "CRITICAL")],
            now=NOW,
        ),
        build_action_simulation(
            node_id="pi-001",
            guardrails=guardrails,
            state=state(),
            active_anomalies=[anomaly("HIGH_VPD", "WARN")],
            now=NOW,
        ),
    ]
    blocked_guardrails = build_guardrails(
        node_id="pi-001",
        state=state(),
        sensor_health=health(status="DISCONNECTED"),
        active_anomalies=[],
        now=NOW,
    )
    simulations.append(
        build_action_simulation(
            node_id="pi-001",
            guardrails=blocked_guardrails,
            state=state(),
            active_anomalies=[],
            now=NOW,
        )
    )

    assert {item["decision"] for item in simulations} == {
        "NO_ACTION",
        "WOULD_NOTIFY",
        "WOULD_INCREASE_SAMPLING",
        "BLOCKED_BY_GUARDRAIL",
    }
    for simulation in simulations:
        assert simulation["decision"] != "WOULD_WATER"
        assert simulation["actuation"] == {"physical_actuation": False, "watering_proposed": False}
