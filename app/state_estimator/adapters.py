from __future__ import annotations

from datetime import UTC, datetime

from app.models import PodReading, TelemetryEvent
from app.state_estimator.models import RawObservation


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def observations_from_event(event: TelemetryEvent) -> list[RawObservation]:
    observations: list[RawObservation] = []
    ts = _as_utc(event.timestamp_utc)
    received_ts = _as_utc(event.received_at)
    for reading in event.readings:
        observations.extend(observations_from_reading(reading, ts, received_ts))
    observations.append(
        RawObservation(
            node_id=event.device_id,
            sensor_id="device_status",
            sensor_type="device_status",
            ts=ts,
            received_ts=received_ts,
            values={"mcu_connected": True},
            read_ok=True,
            raw=event.system_health_jsonb or {},
        )
    )
    return observations


def observations_from_reading(reading: PodReading, ts: datetime, received_ts: datetime) -> list[RawObservation]:
    observations: list[RawObservation] = []
    if reading.air_temperature_c is not None or reading.air_humidity_percent is not None:
        observations.append(
            RawObservation(
                node_id=reading.device_id,
                sensor_id=f"{reading.pod_key}.air",
                sensor_type="air_temp_rh",
                ts=ts,
                received_ts=received_ts,
                values={"air_temp_c": reading.air_temperature_c, "rh_pct": reading.air_humidity_percent},
                read_ok=reading.enabled,
                raw={
                    "legacy_air_vpd_kpa": reading.air_vpd_kpa,
                    "legacy_air_actual_vapor_pressure_kpa": reading.air_actual_vapor_pressure_kpa,
                    "legacy_air_saturation_vapor_pressure_kpa": reading.air_saturation_vapor_pressure_kpa,
                },
            )
        )
    if reading.soil_moisture_percent is not None or reading.adc_raw is not None:
        observations.append(
            RawObservation(
                node_id=reading.device_id,
                sensor_id=f"{reading.pod_key}.soil_moisture",
                sensor_type="soil_moisture",
                ts=ts,
                received_ts=received_ts,
                values={"moisture_pct": reading.soil_moisture_percent, "adc_raw": reading.adc_raw},
                read_ok=reading.enabled,
            )
        )
    if reading.soil_temperature_c is not None:
        observations.append(
            RawObservation(
                node_id=reading.device_id,
                sensor_id=f"{reading.pod_key}.soil_temp",
                sensor_type="soil_temp",
                ts=ts,
                received_ts=received_ts,
                values={"soil_temp_c": reading.soil_temperature_c},
                read_ok=reading.enabled,
            )
        )
    if reading.light_lux is not None:
        observations.append(
            RawObservation(
                node_id=reading.device_id,
                sensor_id=f"{reading.pod_key}.light_lux",
                sensor_type="light_lux",
                ts=ts,
                received_ts=received_ts,
                values={"lux": reading.light_lux},
                read_ok=reading.enabled,
            )
        )
    if reading.leaf_temp_c is not None:
        observations.append(
            RawObservation(
                node_id=reading.device_id,
                sensor_id=f"{reading.pod_key}.leaf_ir",
                sensor_type="leaf_ir",
                ts=ts,
                received_ts=received_ts,
                values={"leaf_temp_c": reading.leaf_temp_c},
                read_ok=reading.enabled,
                raw={"legacy_leaf_vpd_kpa": reading.leaf_vpd_kpa},
            )
        )
    return observations
