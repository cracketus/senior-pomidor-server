"""add flattened telemetry pod readings view

Revision ID: 0003_flat_pod_readings_view
Revises: 0002_system_health
Create Date: 2026-06-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_flat_pod_readings_view"
down_revision: str | None = "0002_system_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW_NAME = "telemetry_pod_readings_flat"

CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW = f"""
CREATE VIEW {VIEW_NAME} AS
SELECT
    telemetry_events.timestamp_utc AS timestamp_utc,
    telemetry_events.received_at AS received_at,
    telemetry_events.device_id AS device_id,
    pod_readings.pod_key AS pod_key,
    pod_readings.enabled AS enabled,
    telemetry_events.source AS source,
    telemetry_events.id AS telemetry_event_id,
    pod_readings.id AS pod_reading_id,
    telemetry_events.schema_version AS schema_version,
    pod_readings.adc_raw AS adc_raw,
    pod_readings.soil_moisture_percent AS soil_moisture_percent,
    pod_readings.soil_temperature_c AS soil_temperature_c,
    pod_readings.air_temperature_c AS air_temperature_c,
    pod_readings.air_humidity_percent AS air_humidity_percent,
    pod_readings.air_pressure_hpa AS air_pressure_hpa,
    pod_readings.light_lux AS light_lux,
    pod_readings.ir_ambient_temp_c AS ir_ambient_temp_c,
    pod_readings.leaf_temp_c AS leaf_temp_c,
    pod_readings.metrics_jsonb AS metrics_jsonb
FROM telemetry_events
JOIN pod_readings ON pod_readings.telemetry_event_id = telemetry_events.id
"""


def upgrade() -> None:
    op.execute(CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
