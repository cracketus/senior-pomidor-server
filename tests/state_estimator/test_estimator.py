from datetime import UTC, datetime

from app.state_estimator.calibration import CalibrationProfile, SoilProbeCalibration
from app.state_estimator.estimator import estimate_state
from app.state_estimator.models import EstimatorContext, EstimatorHistory, RawObservation


def obs(sensor_id: str, sensor_type: str, values: dict) -> RawObservation:
    ts = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    return RawObservation(
        node_id="pi-001",
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        ts=ts,
        received_ts=ts,
        values=values,
    )


def obs_at(sensor_id: str, sensor_type: str, values: dict, minute: int) -> RawObservation:
    ts = datetime(2026, 7, 2, 10, minute, tzinfo=UTC)
    return RawObservation(
        node_id="pi-001",
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        ts=ts,
        received_ts=ts,
        values=values,
    )


def test_missing_optional_co2_keeps_state_usable() -> None:
    result = estimate_state(
        [
            obs("pod-1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod-1.soil_moisture", "soil_moisture", {"moisture_pct": 42.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    assert result.state["env"]["co2_ppm"] is None
    assert "co2_sensor_not_present" in result.state["quality"]["flags"]
    assert result.state["quality"]["level"] in {"GOOD", "DEGRADED"}
    assert {item["type"] for item in result.anomalies}.isdisjoint({"REQUIRED_SENSOR_UNAVAILABLE"})


def test_out_of_range_required_air_sensor_is_rejected_and_unsafe() -> None:
    result = estimate_state(
        [
            obs("pod-1.air", "air_temp_rh", {"air_temp_c": 90.0, "rh_pct": 60.0}),
            obs("pod-1.soil_moisture", "soil_moisture", {"moisture_pct": 42.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    assert result.state["env"]["air_temp_c"] is None
    assert result.state["quality"]["level"] == "UNSAFE_FOR_AUTONOMY"
    assert "REQUIRED_SENSOR_UNAVAILABLE" in {item["type"] for item in result.anomalies}
    assert any("out_of_range" in sensor["flags"] for sensor in result.sensor_health["sensors"])


def test_high_vpd_anomaly_uses_recomputed_canonical_vpd() -> None:
    result = estimate_state(
        [
            obs("pod-1.air", "air_temp_rh", {"air_temp_c": 31.0, "rh_pct": 35.0}),
            obs("pod-1.soil_moisture", "soil_moisture", {"moisture_pct": 42.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    anomaly_types = {item["type"] for item in result.anomalies}
    assert "HIGH_VPD" in anomaly_types
    assert result.state["env"]["vpd_kpa"] > 1.6


def test_soil_probes_use_latest_reading_per_pod_without_duplicates() -> None:
    result = estimate_state(
        [
            obs_at("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}, 0),
            obs_at("pod_1.soil_moisture", "soil_moisture", {"adc_raw": 500.0}, 0),
            obs_at("pod_2.soil_moisture", "soil_moisture", {"adc_raw": 501.0}, 0),
            obs_at("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 57.9, "adc_raw": 500.0}, 1),
            obs_at("pod_2.soil_moisture", "soil_moisture", {"moisture_pct": 57.91, "adc_raw": 501.0}, 1),
            obs_at("device_status", "device_status", {"mcu_connected": True}, 1),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    probes = result.state["soil"]["probes"]
    assert [probe["id"] for probe in probes] == ["pod_1", "pod_2"]
    assert [probe["status"] for probe in probes] == ["OK", "OK"]
    assert [probe["moisture_pct"] for probe in probes] == [57.9, 57.91]


def test_calibrated_percent_is_ok_without_adc_calibration() -> None:
    result = estimate_state(
        [
            obs("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 42.0, "adc_raw": 500.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    probe = result.state["soil"]["probes"][0]
    assert probe["status"] == "OK"
    assert probe["moisture_pct"] == 42.0


def test_adc_only_without_calibration_is_uncalibrated() -> None:
    result = estimate_state(
        [
            obs("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod_1.soil_moisture", "soil_moisture", {"adc_raw": 500.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
    )

    probe = result.state["soil"]["probes"][0]
    assert probe["status"] == "UNCALIBRATED"
    assert probe["moisture_pct"] is None


def test_adc_only_with_calibration_is_converted() -> None:
    calibration = CalibrationProfile(soil_probes={"pod_1": SoilProbeCalibration(air_adc=800.0, water_adc=300.0)})
    result = estimate_state(
        [
            obs("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod_1.soil_moisture", "soil_moisture", {"adc_raw": 550.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
        calibration=calibration,
    )

    probe = result.state["soil"]["probes"][0]
    assert probe["status"] == "OK"
    assert probe["moisture_pct"] == 50.0


def test_independent_configured_probes_do_not_infer_zone_pattern() -> None:
    calibration = CalibrationProfile(
        soil_probes={
            "pod_1": SoilProbeCalibration(position=None),
            "pod_2": SoilProbeCalibration(position=None),
        }
    )
    result = estimate_state(
        [
            obs("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 58.0}),
            obs("pod_2.soil_moisture", "soil_moisture", {"moisture_pct": 59.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
        calibration=calibration,
    )

    assert result.state["soil"]["top_bottom_gradient_pct"] is None
    assert result.state["soil"]["zone_pattern"] == "unknown"
    assert {"TOP_DRYING", "BOTTOM_DRY"}.isdisjoint({item["type"] for item in result.anomalies})


def test_configured_dry_threshold_triggers_pod_dry_anomaly() -> None:
    calibration = CalibrationProfile(soil_probes={"pod_1": SoilProbeCalibration(dry_threshold_pct=20.0)})
    result = estimate_state(
        [
            obs("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}),
            obs("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 19.0}),
            obs("device_status", "device_status", {"mcu_connected": True}),
        ],
        context=EstimatorContext(node_id="pi-001"),
        calibration=calibration,
    )

    assert "TOP_DRYING" in {item["type"] for item in result.anomalies}


def test_impossible_moisture_jump_marks_sensor_health() -> None:
    history = EstimatorHistory()
    estimate_state(
        [
            obs_at("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}, 0),
            obs_at("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 42.0}, 0),
            obs_at("device_status", "device_status", {"mcu_connected": True}, 0),
        ],
        context=EstimatorContext(node_id="pi-001"),
        history=history,
    )
    result = estimate_state(
        [
            obs_at("pod_1.air", "air_temp_rh", {"air_temp_c": 24.0, "rh_pct": 60.0}, 1),
            obs_at("pod_1.soil_moisture", "soil_moisture", {"moisture_pct": 90.0}, 1),
            obs_at("device_status", "device_status", {"mcu_connected": True}, 1),
        ],
        context=EstimatorContext(node_id="pi-001"),
        history=history,
    )

    soil_health = next(item for item in result.sensor_health["sensors"] if item["sensor_type"] == "soil_moisture")
    assert soil_health["status"] == "JUMP"
