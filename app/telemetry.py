from typing import Any

from app.validation import KNOWN_METRICS

HEALTH_ALERT_RULES = {
    "cpu_temp_c": {"level": "warning", "op": ">=", "threshold": 75.0, "message": "CPU temperature is high"},
    "wifi_rssi_dbm": {"level": "warning", "op": "<=", "threshold": -75.0, "message": "Wi-Fi signal is weak"},
    "disk_usage_percent": {"level": "warning", "op": ">=", "threshold": 85.0, "message": "Disk usage is high"},
    "io_wait_percent": {"level": "warning", "op": ">=", "threshold": 20.0, "message": "I/O wait is high"},
    "bus_voltage_v": {"level": "warning", "op": "<=", "threshold": 3.1, "message": "Pod bus voltage is low"},
    "bus_current_ma": {"level": "warning", "op": ">=", "threshold": 500.0, "message": "Pod bus current is high"},
}


def iter_pods(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pods = payload.get("pods") or payload.get("pod_readings") or []
    if isinstance(pods, dict):
        return [dict(value, pod_key=key) if isinstance(value, dict) else {"pod_key": key} for key, value in pods.items()]
    if isinstance(pods, list):
        return [pod for pod in pods if isinstance(pod, dict)]
    return []


def pod_key(pod: dict[str, Any], index: int) -> str:
    value = pod.get("pod_key") or pod.get("pod") or pod.get("key") or pod.get("id") or f"pod_{index + 1}"
    return str(value)


def pod_enabled(pod: dict[str, Any]) -> bool:
    value = pod.get("enabled")
    return bool(value) if value is not None else True


def pod_metrics(pod: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, float]]:
    metrics = pod.get("metrics") if isinstance(pod.get("metrics"), dict) else pod
    known: dict[str, float | None] = {metric: None for metric in KNOWN_METRICS}
    unknown: dict[str, float] = {}
    for key, value in metrics.items():
        if key in {"pod_key", "pod", "key", "id", "enabled", "metrics", "errors"}:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if key in KNOWN_METRICS:
            known[key] = float(value)
        else:
            unknown[key] = float(value)
    return known, unknown


def iter_pod_errors(payload: dict[str, Any], pod: dict[str, Any], pod_key_value: str) -> list[dict[str, str | None]]:
    errors = pod.get("errors") if isinstance(pod.get("errors"), list) else []
    result: list[dict[str, str | None]] = []
    for error in errors:
        if isinstance(error, str):
            result.append({"pod_key": pod_key_value, "sensor": None, "message": error})
        elif isinstance(error, dict):
            message = error.get("message") or error.get("error")
            if message:
                result.append(
                    {
                        "pod_key": str(error.get("pod_key") or pod_key_value),
                        "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
                        "message": str(message),
                    }
                )

    root_errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    for error in root_errors:
        if not isinstance(error, dict):
            continue
        error_pod_key = str(error.get("pod_key") or error.get("pod") or "")
        if error_pod_key != pod_key_value:
            continue
        message = error.get("message") or error.get("error")
        if message:
            result.append(
                {
                    "pod_key": pod_key_value,
                    "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
                    "message": str(message),
                }
            )
    return result


def optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def normalize_system_health(payload: dict[str, Any]) -> dict[str, Any] | None:
    source = payload.get("system_health")
    if not isinstance(source, dict):
        return None

    normalized: dict[str, Any] = {}
    rpi_core = source.get("rpi_core")
    if isinstance(rpi_core, dict):
        values = {
            field: optional_float(rpi_core.get(field))
            for field in ("cpu_temp_c", "wifi_rssi_dbm", "disk_usage_percent", "io_wait_percent")
        }
        normalized["rpi_core"] = {field: value for field, value in values.items() if value is not None}

    pod_1_hardware = source.get("pod_1_hardware")
    if isinstance(pod_1_hardware, dict):
        values = {
            field: optional_float(pod_1_hardware.get(field))
            for field in ("bus_voltage_v", "bus_current_ma")
        }
        hardware = {field: value for field, value in values.items() if value is not None}
        box_climate = pod_1_hardware.get("box_climate")
        if isinstance(box_climate, dict):
            climate_values = {
                field: optional_float(box_climate.get(field))
                for field in ("air_temp_c", "air_humidity_percent")
            }
            climate = {field: value for field, value in climate_values.items() if value is not None}
            if climate:
                hardware["box_climate"] = climate
        normalized["pod_1_hardware"] = hardware

    errors = source.get("errors")
    if isinstance(errors, list):
        normalized["errors"] = [
            {
                "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
                "message": str(error["message"]),
            }
            for error in errors
            if isinstance(error, dict) and error.get("message")
        ]

    return normalized


def health_alerts(system_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not system_health:
        return []

    alerts: list[dict[str, Any]] = []
    rpi_core = system_health.get("rpi_core") if isinstance(system_health.get("rpi_core"), dict) else {}
    pod_1_hardware = (
        system_health.get("pod_1_hardware") if isinstance(system_health.get("pod_1_hardware"), dict) else {}
    )
    values = {
        "cpu_temp_c": rpi_core.get("cpu_temp_c"),
        "wifi_rssi_dbm": rpi_core.get("wifi_rssi_dbm"),
        "disk_usage_percent": rpi_core.get("disk_usage_percent"),
        "io_wait_percent": rpi_core.get("io_wait_percent"),
        "bus_voltage_v": pod_1_hardware.get("bus_voltage_v"),
        "bus_current_ma": pod_1_hardware.get("bus_current_ma"),
    }
    for metric, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        rule = HEALTH_ALERT_RULES[metric]
        threshold = float(rule["threshold"])
        triggered = value >= threshold if rule["op"] == ">=" else value <= threshold
        if triggered:
            alerts.append(
                {
                    "metric": metric,
                    "level": rule["level"],
                    "message": rule["message"],
                    "value": float(value),
                    "threshold": threshold,
                }
            )

    for error in system_health.get("errors") or []:
        if not isinstance(error, dict):
            continue
        alerts.append(
            {
                "metric": "health_probe_error",
                "level": "warning",
                "sensor": error.get("sensor"),
                "message": error.get("message") or "Health probe error",
            }
        )
    return alerts
