import json

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def test_0009_upgrades_populated_database_without_changing_history(tmp_path):
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite:///{database_path}"
    previous_url = settings.database_url
    settings.database_url = database_url
    config = Config("alembic.ini")
    raw_payload = json.dumps(
        {
            "schema_version": "senior-pomidor.edge.telemetry.v2",
            "device_id": "pi-001",
            "timestamp_utc": "2026-08-19T12:00:00Z",
            "pods": {},
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        command.upgrade(config, "0008_story_environment")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO devices (device_id, first_seen_at, last_seen_at, last_payload_at) "
                    "VALUES (:device_id, :timestamp, :timestamp, :timestamp)"
                ),
                {"device_id": "pi-001", "timestamp": "2026-08-19 12:00:00+00:00"},
            )
            connection.execute(
                text(
                    "INSERT INTO telemetry_events "
                    "(device_id, timestamp_utc, schema_version, source, raw_payload_jsonb, received_at) "
                    "VALUES (:device_id, :timestamp, :schema_version, :source, :raw_payload, :received_at)"
                ),
                {
                    "device_id": "pi-001",
                    "timestamp": "2026-08-19 12:00:00+00:00",
                    "schema_version": "senior-pomidor.edge.telemetry.v2",
                    "source": "mqtt",
                    "raw_payload": raw_payload,
                    "received_at": "2026-08-19 12:00:01+00:00",
                },
            )
        with engine.connect() as connection:
            before = connection.execute(
                text("SELECT COUNT(*), raw_payload_jsonb, timestamp_utc FROM telemetry_events")
            ).one()
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            after = connection.execute(
                text("SELECT COUNT(*), raw_payload_jsonb, timestamp_utc, record_id FROM telemetry_events")
            ).one()
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("telemetry_events")}
        indexes = {index["name"]: index for index in inspector.get_indexes("telemetry_events")}
        constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("telemetry_events")}
        engine.dispose()

        assert after[:3] == before
        assert after.record_id is None
        assert columns["record_id"]["nullable"] is True
        assert indexes["ix_telemetry_events_record_id"]["unique"] == 1
        assert "uq_telemetry_event_identity" in constraints
    finally:
        settings.database_url = previous_url
