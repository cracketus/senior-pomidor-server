from typing import Any

from app.validation import KNOWN_METRICS, validate_pod_key

HEALTH_ALERT_RULES: dict[str, dict[str, float | str]] = {
    "cpu_temp_c": {"level": "warning", "op": ">=", "threshold": 75.0, "message": "CPU temperature is high"},
    "wifi_rssi_dbm": {"level": "warning", "op": "<=", "threshold": -75.0, "message": "Wi-Fi signal is weak"},
    "disk_usage_percent": {"level": "warning", "op": ">=", "threshold": 85.0, "message": "Disk usage is high"},
    "io_wait_percent": {"level": "warning", "op": ">=", "threshold": 20.0, "message": "I/O wait is high"},
    "bus_voltage_v": {"level": "warning", "op": "<=", "threshold": 3.1, "message": "Pod bus voltage is low"},
    "bus_current_ma": {"level": "warning", "op": ">=", "threshold": 500.0, "message": "Pod bus current is high"},
}
NETWORK_BOOLEAN_FIELDS = (
    "wifi_connected",
    "interface_up",
    "default_gateway_reachable",
    "dns_resolution_ok",
    "internet_reachable",
    "active_profile_present",
    "preferred_profile_present",
)
NETWORK_STRING_FIELDS = (
    "ssid",
    "ip_address",
    "last_recovery_action",
    "last_recovery_result",
    "last_recovery_at_utc",
)
NETWORK_INTEGER_FIELDS = ("wifi_profile_count", "last_recovery_exit_code")
NETWORK_ALERT_MESSAGES = {
    "wifi_connected": "Wi-Fi is disconnected",
    "wifi_profile_count": "No Wi-Fi profiles are configured",
    "internet_reachable": "Internet reachability check failed",
    "dns_resolution_ok": "DNS resolution check failed",
    "default_gateway_reachable": "Default gateway reachability check failed",
    "preferred_profile_present": "Preferred Wi-Fi profile is missing",
    "last_recovery_exit_code": "Last network recovery command failed",
}


def _plant(payload: dict[str, Any]) -> dict[str, Any]:
    plant = payload.get("plant")
    return plant if isinstance(plant, dict) else {}


def iter_pods(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plant = _plant(payload)
    pods = payload.get("pods") or payload.get("pod_readings") or plant.get("readings") or plant.get("pods") or []
    if isinstance(pods, dict):
        return [
            dict(value, pod_key=key) if isinstance(value, dict) else {"pod_key": key} for key, value in pods.items()
        ]
    if isinstance(pods, list):
        return [pod for pod in pods if isinstance(pod, dict)]
    return []


def pod_key(pod: dict[str, Any], index: int) -> str:
    value = pod.get("pod_key") or pod.get("pod") or pod.get("key") or pod.get("id") or f"pod_{index + 1}"
    return validate_pod_key(value)


def pod_enabled(pod: dict[str, Any]) -> bool:
    value = pod.get("enabled")
    return bool(value) if value is not None else True


def pod_metrics(pod: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, float]]:
    metrics_value = pod.get("metrics")
    metrics: dict[str, Any] = metrics_value if isinstance(metrics_value, dict) else pod
    known: dict[str, float | None] = dict.fromkeys(KNOWN_METRICS)
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


def _normalize_pod_error(error: Any, default_pod_key: str | None = None) -> dict[str, str | None] | None:
    if isinstance(error, str):
        if default_pod_key is None:
            return None
        return {"pod_key": default_pod_key, "sensor": None, "message": error}
    if not isinstance(error, dict):
        return None
    pod_key_value = error.get("pod_key") or error.get("pod") or default_pod_key
    message = error.get("message") or error.get("error")
    if not pod_key_value or not message:
        return None
    return {
        "pod_key": str(pod_key_value),
        "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
        "message": str(message),
    }


def iter_payload_pod_errors(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    errors: list[Any] = []
    root_errors = payload.get("errors")
    if isinstance(root_errors, list):
        errors.extend(root_errors)
    plant_errors = _plant(payload).get("errors")
    if isinstance(plant_errors, list):
        errors.extend(plant_errors)
    return [normalized for error in errors if (normalized := _normalize_pod_error(error)) is not None]


def iter_pod_errors(payload: dict[str, Any], pod: dict[str, Any], pod_key_value: str) -> list[dict[str, str | None]]:
    pod_errors_value = pod.get("errors")
    pod_errors: list[Any] = pod_errors_value if isinstance(pod_errors_value, list) else []
    result: list[dict[str, str | None]] = []
    for error in pod_errors:
        normalized = _normalize_pod_error(error, default_pod_key=pod_key_value)
        if normalized is not None:
            result.append(normalized)

    for error in iter_payload_pod_errors(payload):
        if error["pod_key"] == pod_key_value:
            result.append(error)
    return result


def iter_unmatched_pod_errors(payload: dict[str, Any], known_pod_keys: set[str]) -> list[dict[str, str | None]]:
    return [error for error in iter_payload_pod_errors(payload) if error["pod_key"] not in known_pod_keys]


def optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


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
        values = {field: optional_float(pod_1_hardware.get(field)) for field in ("bus_voltage_v", "bus_current_ma")}
        hardware: dict[str, Any] = {field: value for field, value in values.items() if value is not None}
        box_climate = pod_1_hardware.get("box_climate")
        if isinstance(box_climate, dict):
            climate_values = {
                field: optional_float(box_climate.get(field)) for field in ("air_temp_c", "air_humidity_percent")
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

    network = source.get("network")
    if isinstance(network, dict):
        normalized_network: dict[str, Any] = {}
        for field in NETWORK_BOOLEAN_FIELDS:
            value = network.get(field)
            if isinstance(value, bool):
                normalized_network[field] = value
        for field in NETWORK_STRING_FIELDS:
            value = network.get(field)
            if isinstance(value, str):
                normalized_network[field] = value
        for field in NETWORK_INTEGER_FIELDS:
            value = optional_int(network.get(field))
            if value is not None:
                normalized_network[field] = value
        if normalized_network:
            normalized["network"] = normalized_network

    return normalized


def health_alerts(system_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not system_health:
        return []

    alerts: list[dict[str, Any]] = []
    rpi_core_value = system_health.get("rpi_core")
    rpi_core: dict[str, Any] = rpi_core_value if isinstance(rpi_core_value, dict) else {}
    pod_1_hardware_value = system_health.get("pod_1_hardware")
    pod_1_hardware: dict[str, Any] = pod_1_hardware_value if isinstance(pod_1_hardware_value, dict) else {}
    network_value = system_health.get("network")
    network: dict[str, Any] = network_value if isinstance(network_value, dict) else {}
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

    for metric in ("wifi_connected", "internet_reachable", "dns_resolution_ok", "default_gateway_reachable"):
        if network.get(metric) is False:
            alerts.append({"metric": metric, "level": "warning", "message": NETWORK_ALERT_MESSAGES[metric]})

    if network.get("preferred_profile_present") is False:
        alerts.append(
            {
                "metric": "preferred_profile_present",
                "level": "warning",
                "message": NETWORK_ALERT_MESSAGES["preferred_profile_present"],
            }
        )

    wifi_profile_count = network.get("wifi_profile_count")
    if isinstance(wifi_profile_count, int) and not isinstance(wifi_profile_count, bool) and wifi_profile_count == 0:
        alerts.append(
            {
                "metric": "wifi_profile_count",
                "level": "critical",
                "message": NETWORK_ALERT_MESSAGES["wifi_profile_count"],
                "value": wifi_profile_count,
                "threshold": 1,
            }
        )

    last_recovery_exit_code = network.get("last_recovery_exit_code")
    if (
        isinstance(last_recovery_exit_code, int)
        and not isinstance(last_recovery_exit_code, bool)
        and last_recovery_exit_code != 0
    ):
        alerts.append(
            {
                "metric": "last_recovery_exit_code",
                "level": "warning",
                "message": NETWORK_ALERT_MESSAGES["last_recovery_exit_code"],
                "value": last_recovery_exit_code,
                "threshold": 0,
            }
        )
    return alerts
