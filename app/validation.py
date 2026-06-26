from datetime import UTC, datetime
from typing import Any

TELEMETRY_SCHEMA = "senior-pomidor.edge.telemetry.v1"
TELEMETRY_SCHEMA_V2 = "senior-pomidor.edge.telemetry.v2"
TELEMETRY_SCHEMAS = {TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2}
PHOTO_SCHEMA = "senior-pomidor.edge.photo.v1"
KNOWN_METRICS = {
    "adc_raw",
    "soil_moisture_percent",
    "soil_temperature_c",
    "air_temperature_c",
    "air_humidity_percent",
    "air_pressure_hpa",
    "air_actual_vapor_pressure_kpa",
    "air_saturation_vapor_pressure_kpa",
    "air_vpd_kpa",
    "light_lux",
    "ir_ambient_temp_c",
    "leaf_temp_c",
    "leaf_saturation_vapor_pressure_kpa",
    "leaf_vpd_kpa",
}


class ValidationError(ValueError):
    pass


def parse_utc_z(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError("timestamp must be a UTC ISO string ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError as exc:
        raise ValidationError("timestamp is not valid ISO format") from exc


def payload_schema(payload: dict[str, Any]) -> str:
    schema = payload.get("schema_version") or payload.get("schema")
    if not isinstance(schema, str):
        raise ValidationError("schema_version is required")
    return schema


def payload_timestamp(payload: dict[str, Any]) -> datetime:
    value = payload.get("timestamp_utc") or payload.get("timestamp") or payload.get("captured_at_utc")
    if not isinstance(value, str):
        raise ValidationError("timestamp_utc is required")
    return parse_utc_z(value)


def payload_device_id(payload: dict[str, Any]) -> str:
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValidationError("device_id is required")
    return device_id.strip()


def validate_optional_number(value: Any, path: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"{path} must be a number")


def validate_optional_object(value: Any, path: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object")
    return value


def validate_health_errors(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValidationError("system_health.errors must be a list")
    for index, error in enumerate(value):
        if not isinstance(error, dict):
            raise ValidationError(f"system_health.errors[{index}] must be an object")
        sensor = error.get("sensor")
        if sensor is not None and not isinstance(sensor, str):
            raise ValidationError(f"system_health.errors[{index}].sensor must be a string")
        message = error.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValidationError(f"system_health.errors[{index}].message is required")


def validate_system_health(payload: dict[str, Any]) -> None:
    system_health = payload.get("system_health")
    if system_health is None:
        return
    if not isinstance(system_health, dict):
        raise ValidationError("system_health must be an object")

    rpi_core = validate_optional_object(system_health.get("rpi_core"), "system_health.rpi_core")
    if rpi_core is not None:
        for field in ("cpu_temp_c", "wifi_rssi_dbm", "disk_usage_percent", "io_wait_percent"):
            validate_optional_number(rpi_core.get(field), f"system_health.rpi_core.{field}")

    pod_1_hardware = validate_optional_object(system_health.get("pod_1_hardware"), "system_health.pod_1_hardware")
    if pod_1_hardware is not None:
        for field in ("bus_voltage_v", "bus_current_ma"):
            validate_optional_number(pod_1_hardware.get(field), f"system_health.pod_1_hardware.{field}")
        box_climate = validate_optional_object(
            pod_1_hardware.get("box_climate"),
            "system_health.pod_1_hardware.box_climate",
        )
        if box_climate is not None:
            for field in ("air_temp_c", "air_humidity_percent"):
                validate_optional_number(box_climate.get(field), f"system_health.pod_1_hardware.box_climate.{field}")

    validate_health_errors(system_health.get("errors"))


def validate_telemetry_payload(payload: Any) -> tuple[str, datetime]:
    if not isinstance(payload, dict):
        raise ValidationError("telemetry payload must be an object")
    schema = payload_schema(payload)
    if schema not in TELEMETRY_SCHEMAS:
        raise ValidationError(f"unsupported telemetry schema: {schema}")
    device_id = payload_device_id(payload)
    timestamp = payload_timestamp(payload)
    validate_system_health(payload)
    return device_id, timestamp


def validate_topic_device(topic: str, topic_prefix: str, payload_device_id_value: str) -> None:
    parts = topic.split("/")
    expected = [topic_prefix, payload_device_id_value, "telemetry"]
    if parts != expected:
        raise ValidationError("MQTT topic must match {topic_prefix}/{device_id}/telemetry")
