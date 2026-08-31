import math
from collections.abc import Callable
from typing import Any

from app.edge_reliability import EdgeReliabilityEvaluation, evaluate_edge_reliability, reliability_alerts
from app.validation import KNOWN_METRICS, ValidationError, parse_utc_z, validate_pod_key

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
HEALTH_STRING_MAX_LENGTH = 256


class _InvalidValue:
    pass


_INVALID = _InvalidValue()

WATCHDOG_STRING_FIELDS = ("state", "reason", "result", "boot_id")
WATCHDOG_BOOLEAN_FIELDS = ("suppression", "configured")
WATCHDOG_COUNTER_FIELDS = ("attempt_count", "restart_count", "reboot_count")
WATCHDOG_TIMESTAMP_FIELDS = ("last_healthy_heartbeat_at_utc",)

SPOOL_STRING_FIELDS = (
    "status",
    "disk_status",
    "last_reconciliation_reason",
    "last_delivery_result",
    "last_error_code",
    "worker_state",
)
SPOOL_COUNTER_FIELDS = (
    "pending_count",
    "backlog_count",
    "in_flight_count",
    "delivered_count",
    "dead_letter_count",
    "reconciled_count",
    "resolution_total",
    "database_size_bytes",
    "free_space_bytes",
    "delivery_attempt_count",
    "delivery_success_count",
    "duplicate_count",
    "delivery_retry_count",
    "delivery_rejected_count",
    "write_failure_count",
    "written_total",
    "success_total",
    "failure_total",
    "duplicate_total",
    "replayed_total",
    "replay_count",
    "legacy_corrupt_count",
)
SPOOL_NULLABLE_SECONDS_FIELDS = ("oldest_pending_age_seconds", "outage_duration_seconds")
SPOOL_TIMESTAMP_FIELDS = (
    "last_reconciliation_at_utc",
    "last_delivery_at_utc",
    "last_successful_delivery_at_utc",
    "last_error_at_utc",
    "worker_last_heartbeat_at_utc",
)
SPOOL_ESTIMATE_FIELDS = ("estimated_drain_seconds", "estimated_retention_days")

APPLICATION_STRING_FIELDS = (
    "systemd_service_name",
    "systemd_active_state",
    "systemd_sub_state",
)
APPLICATION_SERVICE_MANAGERS = {"none", "systemd"}
APPLICATION_BOOLEAN_FIELDS = ("process_running", "systemd_available", "systemd_service_active")
APPLICATION_INTEGER_FIELDS = (
    "process_id",
    "process_uptime_seconds",
    "process_memory_rss_bytes",
    "systemd_main_pid",
)


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


def _bounded_string(value: Any, *, nullable: bool = True) -> str | _InvalidValue | None:
    if value is None:
        return None if nullable else _INVALID
    if not isinstance(value, str) or not value or len(value) > HEALTH_STRING_MAX_LENGTH:
        return _INVALID
    return value


def _boolean(value: Any) -> bool | _InvalidValue:
    return value if isinstance(value, bool) else _INVALID


def _nonnegative_int(value: Any, *, nullable: bool = False) -> int | _InvalidValue | None:
    if value is None:
        return None if nullable else _INVALID
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return _INVALID
    return value


def _nonnegative_number(value: Any, *, nullable: bool = False) -> float | _InvalidValue | None:
    if value is None:
        return None if nullable else _INVALID
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _INVALID
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return _INVALID
    return result


def _percentage(value: Any) -> float | _InvalidValue:
    result = _nonnegative_number(value)
    if isinstance(result, _InvalidValue) or result is None or result > 100:
        return _INVALID
    return result


def _utc_timestamp(value: Any) -> str | _InvalidValue | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > HEALTH_STRING_MAX_LENGTH:
        return _INVALID
    try:
        parse_utc_z(value)
    except ValidationError:
        return _INVALID
    return value


def _copy_fields(
    source: dict[str, Any],
    target: dict[str, Any],
    fields: tuple[str, ...],
    normalizer: Callable[[Any], Any],
) -> None:
    for field in fields:
        if field not in source:
            continue
        value = normalizer(source[field])
        if not isinstance(value, _InvalidValue):
            target[field] = value


def _normalize_watchdog(source: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    _copy_fields(source, result, WATCHDOG_STRING_FIELDS, _bounded_string)
    _copy_fields(source, result, WATCHDOG_BOOLEAN_FIELDS, _boolean)
    _copy_fields(source, result, WATCHDOG_COUNTER_FIELDS, _nonnegative_int)
    _copy_fields(source, result, WATCHDOG_TIMESTAMP_FIELDS, _utc_timestamp)
    return result


def _normalize_spool(source: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    _copy_fields(source, result, SPOOL_STRING_FIELDS, _bounded_string)
    _copy_fields(source, result, SPOOL_COUNTER_FIELDS, _nonnegative_int)
    _copy_fields(source, result, SPOOL_NULLABLE_SECONDS_FIELDS, lambda value: _nonnegative_int(value, nullable=True))
    _copy_fields(source, result, SPOOL_TIMESTAMP_FIELDS, _utc_timestamp)
    _copy_fields(source, result, SPOOL_ESTIMATE_FIELDS, lambda value: _nonnegative_number(value, nullable=True))
    if "disk_usage_percent" in source:
        value = _percentage(source["disk_usage_percent"])
        if not isinstance(value, _InvalidValue):
            result["disk_usage_percent"] = value
    return result


def _normalize_application(source: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "service_manager" in source:
        service_manager = source["service_manager"]
        result["service_manager"] = (
            service_manager
            if isinstance(service_manager, str) and service_manager in APPLICATION_SERVICE_MANAGERS
            else None
        )
    _copy_fields(source, result, APPLICATION_STRING_FIELDS, _bounded_string)
    _copy_fields(source, result, APPLICATION_BOOLEAN_FIELDS, _boolean)
    _copy_fields(source, result, APPLICATION_INTEGER_FIELDS, _nonnegative_int)
    if "process_cpu_percent" in source:
        value = _nonnegative_number(source["process_cpu_percent"])
        if not isinstance(value, _InvalidValue):
            result["process_cpu_percent"] = value
    return result


def _normalize_health_aggregate(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    result: dict[str, Any] = {}
    schema_version = source.get("schema_version")
    if isinstance(schema_version, str) and len(schema_version) <= HEALTH_STRING_MAX_LENGTH:
        result["schema_version"] = schema_version
    state = source.get("state")
    if isinstance(state, str) and len(state) <= HEALTH_STRING_MAX_LENGTH:
        result["state"] = state
    reasons = source.get("reasons")
    if isinstance(reasons, list):
        bounded: list[str] = []
        for reason in reasons[:32]:
            if isinstance(reason, str) and 0 < len(reason) <= HEALTH_STRING_MAX_LENGTH and reason not in bounded:
                bounded.append(reason)
        result["reasons"] = bounded
    return result


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

    reliability_normalizers = {
        "watchdog": _normalize_watchdog,
        "spool": _normalize_spool,
        "application": _normalize_application,
    }
    for block_name, normalizer in reliability_normalizers.items():
        block = source.get(block_name)
        if isinstance(block, dict):
            normalized[block_name] = normalizer(block)

    if "aggregate" in source:
        normalized["aggregate"] = _normalize_health_aggregate(source["aggregate"])

    return normalized


def health_alerts(
    system_health: dict[str, Any] | None,
    *,
    edge_reliability: EdgeReliabilityEvaluation | None = None,
) -> list[dict[str, Any]]:
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
    evaluation = edge_reliability or evaluate_edge_reliability(system_health)
    alerts.extend(reliability_alerts(evaluation))
    return alerts
