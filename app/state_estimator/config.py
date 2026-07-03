from __future__ import annotations

from pathlib import Path
from typing import Any

from app.state_estimator.calibration import CalibrationProfile, SoilProbeCalibration
from app.state_estimator.models import EstimatorConfig


def load_estimator_runtime(
    path: str | Path = "config/state_estimator_v1.yaml",
    *,
    timezone: str | None = None,
) -> tuple[EstimatorConfig, CalibrationProfile]:
    config = EstimatorConfig()
    calibration = CalibrationProfile()
    config_path = Path(path)
    if config_path.is_file():
        data = _parse_simple_yaml(config_path)
        config = _estimator_config_from_data(data)
        calibration = _calibration_from_data(data)
    if timezone is not None:
        config.timezone = timezone
    return config, calibration


def _estimator_config_from_data(data: dict[str, Any]) -> EstimatorConfig:
    cadence = _dict(data.get("cadence"))
    confidence = _dict(data.get("confidence"))
    anomalies = _dict(data.get("anomalies"))
    soil = _dict(data.get("soil"))
    lifecycle = _dict(anomalies.get("lifecycle"))
    return EstimatorConfig(
        timezone=str(data.get("timezone") or EstimatorConfig.timezone),
        collection_window_seconds=_int(cadence.get("collection_window_seconds"), 90),
        max_sensor_age_seconds=_int(cadence.get("max_sensor_age_seconds"), 120),
        max_device_age_seconds=_int(cadence.get("max_device_age_seconds"), 120),
        minimum_for_normal_control=_float(confidence.get("minimum_for_normal_control"), 0.65),
        minimum_for_any_autonomy=_float(confidence.get("minimum_for_any_autonomy"), 0.40),
        high_temp_warn_c=_float(anomalies.get("high_temp_warn_c"), 30.0),
        critical_heat_c=_float(anomalies.get("critical_heat_c"), 32.0),
        low_temp_warn_c=_float(anomalies.get("low_temp_warn_c"), 15.0),
        critical_cold_c=_float(anomalies.get("critical_cold_c"), 12.0),
        high_rh_pct=_float(anomalies.get("high_rh_pct"), 85.0),
        saturation_rh_pct=_float(anomalies.get("saturation_rh_pct"), 98.0),
        high_vpd_kpa=_float(anomalies.get("high_vpd_kpa"), 1.6),
        low_vpd_kpa=_float(anomalies.get("low_vpd_kpa"), 0.5),
        leaf_air_delta_abs_c=_float(anomalies.get("leaf_air_delta_abs_c"), 3.0),
        minimum_valid_soil_probes=_int(soil.get("minimum_valid_probes"), 1),
        env_warning_trigger_seconds=_int(lifecycle.get("env_warning_trigger_seconds"), 0),
        warning_clear_cycles=_int(lifecycle.get("warning_clear_cycles"), 2),
        high_clear_seconds=_int(lifecycle.get("high_clear_seconds"), 300),
    )


def _calibration_from_data(data: dict[str, Any]) -> CalibrationProfile:
    soil = _dict(data.get("soil"))
    probes = _dict(soil.get("probes"))
    calibrations: dict[str, SoilProbeCalibration] = {}
    for probe_id, raw_probe in probes.items():
        if not isinstance(raw_probe, dict):
            continue
        calibrations[str(probe_id)] = SoilProbeCalibration(
            position=str(raw_probe["position"]) if raw_probe.get("position") is not None else None,
            air_adc=_float_or_none(raw_probe.get("air_adc")),
            water_adc=_float_or_none(raw_probe.get("water_adc")),
            dry_threshold_pct=_float(raw_probe.get("dry_threshold_pct"), 20.0),
            wet_threshold_pct=_float(raw_probe.get("wet_threshold_pct"), 75.0),
        )
    return CalibrationProfile(profile_id=str(data.get("schema_version") or "default"), soil_probes=calibrations)


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if ":" not in text:
            continue
        key, raw_value = text.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"null", "~"}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return int(value)
