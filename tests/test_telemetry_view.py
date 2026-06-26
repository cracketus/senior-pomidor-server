import json
from importlib import import_module

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services import persist_telemetry
from app.validation import TELEMETRY_SCHEMA

telemetry_view_migration = import_module("migrations.versions.0004_vpd_metrics")


def decode_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def test_telemetry_pod_readings_flat_view_returns_sample_ingestion_rows():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(telemetry_view_migration.SQLITE_CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW))

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = SessionLocal()
    try:
        persist_telemetry(
            db,
            {
                "schema_version": TELEMETRY_SCHEMA,
                "device_id": "pi-001",
                "timestamp_utc": "2026-06-07T12:00:00Z",
                "pods": {
                    "pod-1": {
                        "enabled": True,
                        "soil_moisture_percent": 42.5,
                        "air_actual_vapor_pressure_kpa": 1.36,
                        "air_saturation_vapor_pressure_kpa": 7.38,
                        "air_vpd_kpa": 6.02,
                        "leaf_temp_c": 21.2,
                        "leaf_saturation_vapor_pressure_kpa": 5.02,
                        "leaf_vpd_kpa": 3.66,
                        "battery_mv": 5010,
                    },
                    "pod-2": {"enabled": False, "air_humidity_percent": 58.0},
                },
            },
            source="mqtt",
        )

        rows = (
            db.execute(
                text(
                    """
                SELECT
                    timestamp_utc,
                    device_id,
                    pod_key,
                    enabled,
                    source,
                    telemetry_event_id,
                    pod_reading_id,
                    schema_version,
                    soil_moisture_percent,
                    air_humidity_percent,
                    air_actual_vapor_pressure_kpa,
                    air_saturation_vapor_pressure_kpa,
                    air_vpd_kpa,
                    leaf_temp_c,
                    leaf_saturation_vapor_pressure_kpa,
                    leaf_vpd_kpa,
                    metrics_jsonb
                FROM telemetry_pod_readings_flat
                ORDER BY pod_key
                """
                )
            )
            .mappings()
            .all()
        )
    finally:
        db.close()
        engine.dispose()

    assert len(rows) == 2
    assert rows[0]["device_id"] == "pi-001"
    assert rows[0]["pod_key"] == "pod-1"
    assert rows[0]["enabled"] in (True, 1)
    assert rows[0]["source"] == "mqtt"
    assert rows[0]["telemetry_event_id"] is not None
    assert rows[0]["pod_reading_id"] is not None
    assert rows[0]["schema_version"] == TELEMETRY_SCHEMA
    assert rows[0]["soil_moisture_percent"] == 42.5
    assert rows[0]["air_actual_vapor_pressure_kpa"] == 1.36
    assert rows[0]["air_saturation_vapor_pressure_kpa"] == 7.38
    assert rows[0]["air_vpd_kpa"] == 6.02
    assert rows[0]["leaf_temp_c"] == 21.2
    assert rows[0]["leaf_saturation_vapor_pressure_kpa"] == 5.02
    assert rows[0]["leaf_vpd_kpa"] == 3.66
    assert decode_json(rows[0]["metrics_jsonb"]) == {"battery_mv": 5010.0}

    assert rows[1]["pod_key"] == "pod-2"
    assert rows[1]["enabled"] in (False, 0)
    assert rows[1]["air_humidity_percent"] == 58.0
    assert decode_json(rows[1]["metrics_jsonb"]) == {}


def test_vpd_view_keeps_legacy_metrics_jsonb_values_visible():
    view_sql = telemetry_view_migration.CREATE_TELEMETRY_POD_READINGS_FLAT_VIEW

    assert "pod_readings.metrics_jsonb ->> 'air_vpd_kpa'" in view_sql
    assert "pod_readings.metrics_jsonb ->> 'leaf_vpd_kpa'" in view_sql
