from datetime import UTC, datetime
from typing import Any

TELEMETRY_SCHEMA = "senior-pomidor.edge.telemetry.v1"
PHOTO_SCHEMA = "senior-pomidor.edge.photo.v1"
KNOWN_METRICS = {
    "adc_raw",
    "soil_moisture_percent",
    "soil_temperature_c",
    "air_temperature_c",
    "air_humidity_percent",
    "air_pressure_hpa",
    "light_lux",
    "ir_ambient_temp_c",
    "leaf_temp_c",
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


def validate_telemetry_payload(payload: Any) -> tuple[str, datetime]:
    if not isinstance(payload, dict):
        raise ValidationError("telemetry payload must be an object")
    schema = payload_schema(payload)
    if schema != TELEMETRY_SCHEMA:
        raise ValidationError(f"unsupported telemetry schema: {schema}")
    device_id = payload_device_id(payload)
    timestamp = payload_timestamp(payload)
    return device_id, timestamp


def validate_topic_device(topic: str, topic_prefix: str, payload_device_id_value: str) -> None:
    parts = topic.split("/")
    expected = [topic_prefix, payload_device_id_value, "telemetry"]
    if parts != expected:
        raise ValidationError("MQTT topic must match {topic_prefix}/{device_id}/telemetry")
