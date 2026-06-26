"""add vpd metrics

Revision ID: 0004_vpd_metrics
Revises: 0003_flat_pod_readings_view
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_vpd_metrics"
down_revision: str | None = "0003_flat_pod_readings_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW_NAME = "telemetry_pod_readings_flat"
VPD_COLUMNS: tuple[str, ...] = (
    "air_actual_vapor_pressure_kpa",
    "air_saturation_vapor_pressure_kpa",
    "air_vpd_kpa",
    "leaf_saturation_vapor_pressure_kpa",
    "leaf_vpd_kpa",
)

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
    COALESCE(
        pod_readings.air_actual_vapor_pressure_kpa,
        NULLIF(pod_readings.metrics_jsonb ->> 'air_actual_vapor_pressure_kpa', '')::double precision
    ) AS air_actual_vapor_pressure_kpa,
    COALESCE(
        pod_readings.air_saturation_vapor_pressure_kpa,
        NULLIF(pod_readings.metrics_jsonb ->> 'air_saturation_vapor_pressure_kpa', '')::double precision
    ) AS air_saturation_vapor_pressure_kpa,
    COALESCE(
        pod_readings.air_vpd_kpa,
        NULLIF(pod_readings.metrics_jsonb ->> 'air_vpd_kpa', '')::double precision
    ) AS air_vpd_kpa,
    pod_readings.light_lux AS light_lux,
    pod_readings.ir_ambient_temp_c AS ir_ambient_temp_c,
    pod_readings.leaf_temp_c AS leaf_temp_c,
    COALESCE(
        pod_readings.leaf_saturation_vapor_pressure_kpa,
        NULLIF(pod_readings.metrics_jsonb ->> 'leaf_saturation_vapor_pressure_kpa', '')::double precision
    ) AS leaf_saturation_vapor_pressure_kpa,
    COALESCE(
        pod_readings.leaf_vpd_kpa,
        NULLIF(pod_readings.metrics_jsonb ->> 'leaf_vpd_kpa', '')::double precision
    ) AS leaf_vpd_kpa,
    pod_readings.metrics_jsonb AS metrics_jsonb
FROM telemetry_events
JOIN pod_readings ON pod_readings.telemetry_event_id = telemetry_events.id
"""

SQLITE_CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW = f"""
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
    pod_readings.air_actual_vapor_pressure_kpa AS air_actual_vapor_pressure_kpa,
    pod_readings.air_saturation_vapor_pressure_kpa AS air_saturation_vapor_pressure_kpa,
    pod_readings.air_vpd_kpa AS air_vpd_kpa,
    pod_readings.light_lux AS light_lux,
    pod_readings.ir_ambient_temp_c AS ir_ambient_temp_c,
    pod_readings.leaf_temp_c AS leaf_temp_c,
    pod_readings.leaf_saturation_vapor_pressure_kpa AS leaf_saturation_vapor_pressure_kpa,
    pod_readings.leaf_vpd_kpa AS leaf_vpd_kpa,
    pod_readings.metrics_jsonb AS metrics_jsonb
FROM telemetry_events
JOIN pod_readings ON pod_readings.telemetry_event_id = telemetry_events.id
"""


def upgrade() -> None:
    for column_name in VPD_COLUMNS:
        op.add_column("pod_readings", sa.Column(column_name, sa.Float(), nullable=True))

    bind = op.get_bind()
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    op.execute(
        SQLITE_CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW
        if bind.dialect.name == "sqlite"
        else CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
                    GRANT SELECT ON TABLE public.telemetry_pod_readings_flat TO grafana_reader;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    op.execute(
        """
        CREATE VIEW telemetry_pod_readings_flat AS
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
    )
    for column_name in reversed(VPD_COLUMNS):
        op.drop_column("pod_readings", column_name)
