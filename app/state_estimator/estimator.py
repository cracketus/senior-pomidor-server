from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.state_estimator.anomalies import anomaly
from app.state_estimator.calibration import CalibrationProfile, soil_moisture_from_adc
from app.state_estimator.confidence import quality_level, sensor_confidence
from app.state_estimator.derived_metrics import (
    absolute_humidity_g_m3,
    actual_vapor_pressure_kpa,
    dew_point_c,
    leaf_air_delta_c,
    leaf_vpd_kpa,
    saturation_vapor_pressure_kpa,
    vpd_kpa,
    weighted_average,
)
from app.state_estimator.filtering import filter_value
from app.state_estimator.models import (
    EstimatorConfig,
    EstimatorContext,
    EstimatorHistory,
    EstimatorResult,
    RawObservation,
)
from app.state_estimator.sensor_health import age_seconds, overall_status, sensor_entry
from app.state_estimator.validation import JUMP_LIMITS, validate_hard_range


def _round(value: float | None, digits: int = 3) -> float | None:
    return round(value, digits) if value is not None else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fmt(value: datetime, timezone: str) -> str:
    return _utc(value).astimezone(ZoneInfo(timezone)).isoformat()


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _state_id(node_id: str, ts: str) -> str:
    return f"state_{ts}_{node_id}".replace(":", "").replace("+", "")


def _health_id(node_id: str, ts: str) -> str:
    return f"sensor_health_{ts}_{node_id}".replace(":", "").replace("+", "")


def _latest_by_type(observations: list[RawObservation]) -> dict[str, list[RawObservation]]:
    grouped: dict[str, list[RawObservation]] = {}
    for observation in sorted(observations, key=lambda item: _utc(item.ts)):
        grouped.setdefault(observation.sensor_type, []).append(observation)
    return grouped


def _select_newest(grouped: dict[str, list[RawObservation]], sensor_type: str) -> RawObservation | None:
    values = grouped.get(sensor_type) or []
    return values[-1] if values else None


def _condition_duration_seconds(history: EstimatorHistory, type_: str, now: datetime) -> int:
    active_since = history.anomaly_active_since.get(type_)
    if active_since is None:
        history.anomaly_active_since[type_] = now
        history.anomaly_normal_since.pop(type_, None)
        history.anomaly_normal_counts.pop(type_, None)
        return 0
    history.anomaly_normal_since.pop(type_, None)
    history.anomaly_normal_counts.pop(type_, None)
    return max(0, int((now - active_since).total_seconds()))


def _reset_condition(history: EstimatorHistory, type_: str) -> None:
    history.anomaly_active_since.pop(type_, None)


def _valid_filtered(
    observation: RawObservation | None,
    field: str,
    now: datetime,
    config: EstimatorConfig,
    history: EstimatorHistory,
    *,
    required: bool,
) -> tuple[float | None, dict[str, Any], dict[str, Any] | None]:
    if observation is None:
        status = "DISCONNECTED" if required else "NOT_PRESENT"
        confidence = sensor_confidence(status, required=required)
        return None, {"status": status, "confidence": confidence, "flags": ["missing"]}, None
    age = age_seconds(now, _utc(observation.ts)) or 0.0
    if not observation.read_ok:
        status = "DISCONNECTED"
        confidence = sensor_confidence(status, required=required)
        return None, {"status": status, "confidence": confidence, "age_seconds": age, "flags": ["read_failed"]}, None
    value = _numeric(observation.values.get(field))
    value, reason = validate_hard_range(field, value)
    if reason:
        status = "OUT_OF_RANGE"
        confidence = sensor_confidence(status, required=required)
        return None, {"status": status, "confidence": confidence, "age_seconds": age, "flags": [reason]}, None
    if value is None:
        status = "DISCONNECTED" if required else "NOT_PRESENT"
        confidence = sensor_confidence(status, required=required)
        return None, {"status": status, "confidence": confidence, "age_seconds": age, "flags": ["missing"]}, None
    if age > config.max_sensor_age_seconds:
        status = "STALE"
        confidence = sensor_confidence(status, required=required)
        return None, {"status": status, "confidence": confidence, "age_seconds": age, "flags": ["stale"]}, None

    status = "OK"
    flags: list[str] = []
    previous = history.previous_values.get((observation.sensor_id, field))
    if previous is not None and field in JUMP_LIMITS and abs(value - previous) > JUMP_LIMITS[field]:
        status = "JUMP"
        flags.append("jump")
    history.previous_values[(observation.sensor_id, field)] = value
    filtered, diagnostics = filter_value(history, observation.sensor_id, field, value)
    confidence = sensor_confidence(status, required=required)
    return (
        filtered,
        {"status": status, "confidence": confidence, "age_seconds": age, "flags": flags},
        diagnostics,
    )


def estimate_state(
    observations: list[RawObservation],
    device_telemetry: dict[str, Any] | None = None,
    vision_summary: dict[str, Any] | None = None,
    context: EstimatorContext | None = None,
    calibration: CalibrationProfile | None = None,
    history: EstimatorHistory | None = None,
    config: EstimatorConfig | None = None,
) -> EstimatorResult:
    started = time.perf_counter()
    if not observations and context is None:
        raise ValueError("observations or context are required")
    config = config or EstimatorConfig()
    history = history or EstimatorHistory()
    calibration = calibration or CalibrationProfile()
    node_id = context.node_id if context else observations[0].node_id
    timezone = (context.timezone if context else None) or config.timezone
    context = context or EstimatorContext(node_id=node_id, timezone=timezone)
    now = max((_utc(observation.ts) for observation in observations), default=datetime.now(UTC))
    generated = datetime.now(UTC)
    grouped = _latest_by_type(observations)
    ts_text = _fmt(now, timezone)
    state_id = _state_id(node_id, ts_text)
    health_id = _health_id(node_id, ts_text)

    air = _select_newest(grouped, "air_temp_rh")
    air_temp_c, air_temp_health, air_temp_diag = _valid_filtered(air, "air_temp_c", now, config, history, required=True)
    rh_pct, rh_health, rh_diag = _valid_filtered(air, "rh_pct", now, config, history, required=True)
    light = _select_newest(grouped, "light_lux")
    lux, lux_health, lux_diag = _valid_filtered(light, "lux", now, config, history, required=False)
    leaf = _select_newest(grouped, "leaf_ir")
    leaf_temp_c, leaf_health, leaf_diag = _valid_filtered(leaf, "leaf_temp_c", now, config, history, required=False)
    soil_temp_obs = _select_newest(grouped, "soil_temp")
    soil_temp_c, soil_temp_health, soil_temp_diag = _valid_filtered(
        soil_temp_obs, "soil_temp_c", now, config, history, required=False
    )

    soil_probes: list[dict[str, Any]] = []
    soil_confidences: list[float] = []
    filter_diagnostics: dict[str, Any] = {}
    latest_soil_observations: dict[str, RawObservation] = {}
    for obs in grouped.get("soil_moisture", []):
        latest_soil_observations[obs.sensor_id.split(".")[0]] = obs
    probe_ids = sorted({*calibration.soil_probes.keys(), *latest_soil_observations.keys()})
    for probe_id in probe_ids:
        soil_obs = latest_soil_observations.get(probe_id)
        probe_calibration = calibration.soil_probes.get(probe_id)
        position = probe_calibration.position if probe_calibration else None
        dry_threshold = probe_calibration.dry_threshold_pct if probe_calibration else 20.0
        moisture_pct, health, diag = _valid_filtered(soil_obs, "moisture_pct", now, config, history, required=True)
        adc_raw = _numeric(soil_obs.values.get("adc_raw")) if soil_obs is not None else None
        if soil_obs is not None and moisture_pct is None and adc_raw is not None:
            if probe_calibration is not None:
                calibrated, _unclamped = soil_moisture_from_adc(adc_raw, probe_calibration)
                if calibrated is not None:
                    moisture_pct = calibrated
                    health = {"status": "OK", "confidence": 1.0, "age_seconds": 0.0, "flags": ["adc_calibrated"]}
            if moisture_pct is None:
                health = {"status": "UNCALIBRATED", "confidence": 0.3, "flags": ["uncalibrated"]}
        soil_probes.append(
            {
                "id": probe_id,
                "position": position,
                "moisture_pct": _round(moisture_pct),
                "dry_threshold_pct": dry_threshold,
                "confidence": round(float(health["confidence"]), 3),
                "status": health["status"],
            }
        )
        soil_confidences.append(float(health["confidence"]))
        if soil_obs is not None and diag:
            filter_diagnostics[f"{soil_obs.sensor_id}.moisture_pct"] = diag

    if air_temp_diag and air is not None:
        filter_diagnostics[f"{air.sensor_id}.air_temp_c"] = air_temp_diag
    if rh_diag and air is not None:
        filter_diagnostics[f"{air.sensor_id}.rh_pct"] = rh_diag
    if lux_diag and light is not None:
        filter_diagnostics[f"{light.sensor_id}.lux"] = lux_diag
    if leaf_diag and leaf is not None:
        filter_diagnostics[f"{leaf.sensor_id}.leaf_temp_c"] = leaf_diag
    if soil_temp_diag and soil_temp_obs is not None:
        filter_diagnostics[f"{soil_temp_obs.sensor_id}.soil_temp_c"] = soil_temp_diag

    es = ea = air_vpd = dew_point = abs_humidity = None
    leaf_es = leaf_vpd = leaf_delta = None
    if air_temp_c is not None and rh_pct is not None:
        es = saturation_vapor_pressure_kpa(air_temp_c)
        ea = actual_vapor_pressure_kpa(air_temp_c, rh_pct)
        air_vpd = vpd_kpa(air_temp_c, rh_pct)
        dew_point = dew_point_c(air_temp_c, rh_pct)
        abs_humidity = absolute_humidity_g_m3(air_temp_c, rh_pct)
    if leaf_temp_c is not None and air_temp_c is not None:
        leaf_delta = leaf_air_delta_c(leaf_temp_c, air_temp_c)
        leaf_es = saturation_vapor_pressure_kpa(leaf_temp_c)
        if rh_pct is not None:
            leaf_vpd = leaf_vpd_kpa(leaf_temp_c, air_temp_c, rh_pct)

    avg_moisture = weighted_average(
        [
            (float(probe["moisture_pct"]), float(probe["confidence"]))
            for probe in soil_probes
            if probe["moisture_pct"] is not None
        ]
    )
    top = next((probe for probe in soil_probes if probe["position"] == "top"), None)
    bottom = next((probe for probe in soil_probes if probe["position"] == "bottom"), None)
    gradient = None
    if top and bottom and top["moisture_pct"] is not None and bottom["moisture_pct"] is not None:
        gradient = float(top["moisture_pct"]) - float(bottom["moisture_pct"])
    zone_pattern = "unknown"
    valid_probe_values = [float(probe["moisture_pct"]) for probe in soil_probes if probe["moisture_pct"] is not None]
    if len(valid_probe_values) >= 2 and (top or bottom):
        if max(valid_probe_values) - min(valid_probe_values) < 10:
            zone_pattern = "uniform"
        elif top and bottom and top["moisture_pct"] is not None and bottom["moisture_pct"] is not None:
            if float(bottom["moisture_pct"]) < float(bottom["dry_threshold_pct"]):
                zone_pattern = "bottom_dry"
            elif float(top["moisture_pct"]) < float(top["dry_threshold_pct"]):
                zone_pattern = "top_dry"
            elif abs(float(top["moisture_pct"]) - float(bottom["moisture_pct"])) >= 20:
                zone_pattern = "two_zone"

    device_obs = _select_newest(grouped, "device_status")
    device_age = age_seconds(now, _utc(device_obs.ts) if device_obs else None)
    device_confidence = 1.0 if device_obs is not None and (device_age or 0) <= config.max_device_age_seconds else 0.0
    devices = {
        "light": "UNKNOWN",
        "circulation_fan": "UNKNOWN",
        "exhaust_fan": "UNKNOWN",
        "humidifier": "UNKNOWN",
        "heater_mat": "UNKNOWN",
        "water_pump": "UNKNOWN",
        "co2_solenoid": "UNKNOWN",
        "mcu_connected": bool(device_confidence),
        "last_reset_ts": None,
    }
    if device_telemetry:
        devices.update(device_telemetry)

    env_confidence = min(float(air_temp_health["confidence"]), float(rh_health["confidence"]))
    soil_confidence = max(soil_confidences) if soil_confidences else 0.0
    plant_confidence = float(leaf_health["confidence"]) if leaf_temp_c is not None else 0.7
    budget_confidence = 0.9
    state_confidence = (
        0.35 * env_confidence
        + 0.30 * soil_confidence
        + 0.20 * device_confidence
        + 0.10 * plant_confidence
        + 0.05 * budget_confidence
    )
    valid_soil_probe_count = sum(1 for probe in soil_probes if probe["moisture_pct"] is not None)
    if air_temp_c is None or rh_pct is None or valid_soil_probe_count < config.minimum_valid_soil_probes:
        state_confidence = min(state_confidence, config.minimum_for_any_autonomy - 0.01)
    quality_flags = []
    if lux is None:
        quality_flags.append("light_sensor_not_present")
    quality_flags.append("co2_sensor_not_present")
    if leaf_temp_c is None:
        quality_flags.append("leaf_ir_not_present")

    state: dict[str, Any] = {
        "schema_version": "state_v1",
        "state_id": state_id,
        "node_id": node_id,
        "ts": ts_text,
        "window_start_ts": _fmt(now - timedelta(seconds=config.collection_window_seconds), timezone),
        "window_end_ts": ts_text,
        "generated_ts": _fmt(generated, timezone),
        "context": {
            "timezone": timezone,
            "growth_stage": context.growth_stage,
            "mode": context.mode,
            "is_day": 6 <= _utc(now).astimezone(ZoneInfo(timezone)).hour < 21,
            "is_outdoor": context.is_outdoor,
        },
        "env": {
            "air_temp_c": _round(air_temp_c),
            "rh_pct": _round(rh_pct),
            "co2_ppm": None,
            "lux": _round(lux),
            "ppfd_umol_m2_s": None,
            "air_saturation_vapor_pressure_kpa": _round(es),
            "air_actual_vapor_pressure_kpa": _round(ea),
            "vpd_kpa": _round(air_vpd),
            "dew_point_c": _round(dew_point),
            "absolute_humidity_g_m3": _round(abs_humidity),
        },
        "plant": {
            "leaf_temp_c": _round(leaf_temp_c),
            "leaf_air_delta_c": _round(leaf_delta),
            "leaf_saturation_vapor_pressure_kpa": _round(leaf_es),
            "leaf_vpd_kpa": _round(leaf_vpd),
            "vision": vision_summary,
        },
        "soil": {
            "temp_c": _round(soil_temp_c),
            "probes": soil_probes,
            "avg_moisture_pct": _round(avg_moisture),
            "top_bottom_gradient_pct": _round(gradient),
            "zone_pattern": zone_pattern,
            "drying_rate_pct_per_hour": None,
        },
        "devices": devices,
        "budgets": {
            "water_ml_used_today": None,
            "water_ml_budget_today": None,
            "co2_seconds_used_today": None,
            "co2_seconds_budget_today": None,
        },
        "quality": {
            "level": quality_level(state_confidence),
            "state_confidence": round(state_confidence, 3),
            "env_confidence": round(env_confidence, 3),
            "soil_confidence": round(soil_confidence, 3),
            "plant_confidence": round(plant_confidence, 3),
            "device_confidence": round(device_confidence, 3),
            "budget_confidence": round(budget_confidence, 3),
            "flags": quality_flags,
        },
        "refs": {"sensor_health_id": health_id, "anomaly_ids": []},
    }

    entries = [
        sensor_entry(
            sensor_id=air.sensor_id if air else "air_temp_rh",
            sensor_type="air_temp_rh",
            status="OK" if air_temp_health["status"] == rh_health["status"] == "OK" else "WARN",
            confidence=min(float(air_temp_health["confidence"]), float(rh_health["confidence"])),
            last_seen_ts=_fmt(air.ts, timezone) if air else None,
            age_seconds=air_temp_health.get("age_seconds") or rh_health.get("age_seconds"),
            flags=[*air_temp_health.get("flags", []), *rh_health.get("flags", [])],
        ),
        sensor_entry(
            sensor_id=soil_temp_obs.sensor_id if soil_temp_obs else "soil_temp",
            sensor_type="soil_temp",
            status=str(soil_temp_health["status"]),
            confidence=float(soil_temp_health["confidence"]),
            last_seen_ts=_fmt(soil_temp_obs.ts, timezone) if soil_temp_obs else None,
            age_seconds=soil_temp_health.get("age_seconds"),
            flags=soil_temp_health.get("flags", []),
        ),
        sensor_entry(
            sensor_id=leaf.sensor_id if leaf else "leaf_ir",
            sensor_type="leaf_ir",
            status=str(leaf_health["status"]),
            confidence=float(leaf_health["confidence"]),
            last_seen_ts=_fmt(leaf.ts, timezone) if leaf else None,
            age_seconds=leaf_health.get("age_seconds"),
            flags=leaf_health.get("flags", []),
        ),
        sensor_entry(
            sensor_id=light.sensor_id if light else "light_lux",
            sensor_type="light_lux",
            status=str(lux_health["status"]),
            confidence=float(lux_health["confidence"]),
            last_seen_ts=_fmt(light.ts, timezone) if light else None,
            age_seconds=lux_health.get("age_seconds"),
            flags=lux_health.get("flags", []),
        ),
        sensor_entry(
            sensor_id="co2_01",
            sensor_type="co2",
            status="NOT_PRESENT",
            confidence=0.0,
            last_seen_ts=None,
            age_seconds=None,
            flags=["optional_sensor_missing"],
            reason="CO2 sensor is not installed on this node",
        ),
    ]
    for probe in soil_probes:
        entries.append(
            sensor_entry(
                sensor_id=f"{probe['id']}.soil_moisture",
                sensor_type="soil_moisture",
                status=str(probe["status"]),
                confidence=float(probe["confidence"]),
                last_seen_ts=ts_text,
                age_seconds=0.0,
                flags=[],
            )
        )
    if not soil_probes:
        entries.append(
            sensor_entry(
                sensor_id="soil_moisture",
                sensor_type="soil_moisture",
                status="DISCONNECTED",
                confidence=0.0,
                last_seen_ts=None,
                age_seconds=None,
                flags=["missing"],
            )
        )

    sensor_health = {
        "schema_version": "sensor_health_v1",
        "health_id": health_id,
        "ts": ts_text,
        "node_id": node_id,
        "overall_status": overall_status(entries),
        "sensors": entries,
    }

    anomalies: list[dict[str, Any]] = []

    emitted_types: set[str] = set()
    active_condition_types: set[str] = set()

    def emit(type_: str, severity: str, signals: dict[str, Any], confidence: float, responses: list[str]) -> None:
        emitted_types.add(type_)
        anomalies.append(
            anomaly(
                node_id=node_id,
                ts=ts_text,
                state_id=state_id,
                type_=type_,
                severity=severity,
                signals=signals,
                confidence=confidence,
                required_response=responses,
            )
        )

    def emit_env_warning(
        type_: str,
        signals: dict[str, Any],
        confidence: float,
        responses: list[str],
    ) -> None:
        active_condition_types.add(type_)
        duration_seconds = _condition_duration_seconds(history, type_, now)
        if duration_seconds >= config.env_warning_trigger_seconds:
            emit(type_, "WARN", {**signals, "condition_duration_seconds": duration_seconds}, confidence, responses)

    if air_temp_c is None or rh_pct is None or valid_soil_probe_count < config.minimum_valid_soil_probes:
        emit(
            "REQUIRED_SENSOR_UNAVAILABLE",
            "HIGH",
            {
                "env.air_temp_c": air_temp_c,
                "env.rh_pct": rh_pct,
                "soil.valid_probe_count": valid_soil_probe_count,
            },
            1.0,
            ["increase_sampling", "notify_if_persistent"],
        )
    if air_temp_c is not None:
        if air_temp_c > config.critical_heat_c:
            emit(
                "CRITICAL_HEAT",
                "CRITICAL",
                {"env.air_temp_c": _round(air_temp_c)},
                env_confidence,
                ["notify", "increase_sampling", "guardrails_safe_mode"],
            )
        elif air_temp_c > config.high_temp_warn_c:
            emit_env_warning(
                "HIGH_TEMP",
                {"env.air_temp_c": _round(air_temp_c)},
                env_confidence,
                ["increase_sampling", "log"],
            )
        if air_temp_c < config.critical_cold_c:
            emit(
                "CRITICAL_COLD",
                "HIGH",
                {"env.air_temp_c": _round(air_temp_c)},
                env_confidence,
                ["notify", "safe_mode"],
            )
        elif air_temp_c < config.low_temp_warn_c:
            emit_env_warning(
                "LOW_TEMP",
                {"env.air_temp_c": _round(air_temp_c)},
                env_confidence,
                ["notify_if_persistent"],
            )
    if rh_pct is not None:
        if rh_pct >= config.saturation_rh_pct:
            emit(
                "SATURATION_RH",
                "HIGH",
                {"env.rh_pct": _round(rh_pct)},
                env_confidence,
                ["notify", "camera_snapshot"],
            )
        elif rh_pct > config.high_rh_pct:
            emit_env_warning(
                "HIGH_RH",
                {"env.rh_pct": _round(rh_pct)},
                env_confidence,
                ["increase_sampling", "condensation_watch"],
            )
    if air_vpd is not None:
        if air_vpd > config.high_vpd_kpa:
            emit_env_warning(
                "HIGH_VPD",
                {"env.vpd_kpa": _round(air_vpd), "env.air_temp_c": _round(air_temp_c), "env.rh_pct": _round(rh_pct)},
                env_confidence,
                ["increase_sampling", "capture_image"],
            )
        elif air_vpd < config.low_vpd_kpa:
            emit_env_warning(
                "LOW_VPD",
                {"env.vpd_kpa": _round(air_vpd)},
                env_confidence,
                ["condensation_watch"],
            )
    if leaf_delta is not None and abs(leaf_delta) > config.leaf_air_delta_abs_c:
        emit(
            "LEAF_STRESS",
            "WARN",
            {"plant.leaf_air_delta_c": _round(leaf_delta)},
            plant_confidence,
            ["camera_snapshot", "increase_sampling"],
        )
    if soil_temp_c is not None:
        if soil_temp_c < 15:
            emit(
                "SOIL_TEMP_LOW",
                "WARN",
                {"soil.temp_c": _round(soil_temp_c)},
                float(soil_temp_health["confidence"]),
                ["log", "notify_if_persistent"],
            )
        elif soil_temp_c > 28:
            emit(
                "SOIL_TEMP_HIGH",
                "WARN",
                {"soil.temp_c": _round(soil_temp_c)},
                float(soil_temp_health["confidence"]),
                ["log", "notify_if_persistent"],
            )
    for probe in soil_probes:
        moisture = probe["moisture_pct"]
        if moisture is not None and float(moisture) < float(probe["dry_threshold_pct"]):
            type_ = "BOTTOM_DRY" if probe["position"] == "bottom" else "TOP_DRYING"
            severity = "HIGH" if type_ == "BOTTOM_DRY" else "WARN"
            emit(
                type_,
                severity,
                {f"soil.{probe['id']}.moisture_pct": moisture},
                float(probe["confidence"]),
                ["mark_water_stress_risk"],
            )
    if not devices["mcu_connected"]:
        emit(
            "DEVICE_DISCONNECTED",
            "HIGH",
            {"devices.mcu_connected": False},
            1.0,
            ["block_actuator_autonomy"],
        )
    if state_confidence < config.minimum_for_any_autonomy:
        emit(
            "LOW_STATE_CONFIDENCE",
            "HIGH",
            {"quality.state_confidence": round(state_confidence, 3)},
            1.0,
            ["block_risky_autonomy"],
        )
    for type_ in {"HIGH_TEMP", "LOW_TEMP", "HIGH_RH", "HIGH_VPD", "LOW_VPD"} - active_condition_types:
        _reset_condition(history, type_)
    state["refs"]["anomaly_ids"] = [item["anomaly_id"] for item in anomalies]

    diagnostics = {
        "schema_version": "estimator_diagnostics_v1",
        "diagnostic_id": f"diag_{ts_text}_{node_id}".replace(":", "").replace("+", ""),
        "ts": ts_text,
        "node_id": node_id,
        "state_id": state_id,
        "estimator_version": "0.1.0",
        "config_version": "state_estimator_config_v1",
        "calibration_profile_id": calibration.profile_id,
        "input_count": len(observations),
        "invalid_input_count": sum(1 for entry in entries if entry["status"] in {"OUT_OF_RANGE", "DISCONNECTED"}),
        "processing_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "filters": filter_diagnostics,
    }
    return EstimatorResult(state=state, sensor_health=sensor_health, anomalies=anomalies, diagnostics=diagnostics)
