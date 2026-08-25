import urllib.request
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.grafana_cloud_exporter as grafana_cloud_exporter
from app.config import Settings
from app.grafana_cloud_exporter import (
    ExporterConfigError,
    ExportRow,
    ExportState,
    MetricSample,
    RemoteWriteError,
    RemoteWriteTransport,
    edge_reliability_metric_samples,
    encode_write_request,
    export_once,
    public_labels,
    row_to_metric_samples,
    run_forever,
    sanitize_label_value,
    validate_export_settings,
)
from app.models import Base
from app.services import persist_telemetry
from app.validation import TELEMETRY_SCHEMA


class RecordingTransport:
    def __init__(self) -> None:
        self.samples: list[MetricSample] = []

    def send(self, samples: list[MetricSample]) -> None:
        self.samples.extend(samples)


class FailingTransport:
    def send(self, samples: list[MetricSample]) -> None:
        raise AssertionError("transport should not be called")


class FakeCompressor:
    def compress(self, payload: bytes) -> bytes:
        return b"snappy:" + payload


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class FakeOpener:
    def __init__(self) -> None:
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return FakeResponse()


class TimeoutOpener:
    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        raise TimeoutError("connection timed out")


def sample_row(**overrides) -> ExportRow:
    values = {
        "reading_id": 1,
        "timestamp_utc": datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        "device_id": "pi-001",
        "pod_key": "pod-1",
        "enabled": True,
        "adc_raw": 511.0,
        "soil_moisture_percent": 42.5,
        "soil_temperature_c": 20.1,
        "air_temperature_c": 21.2,
        "air_humidity_percent": 58.0,
        "air_pressure_hpa": 1008.5,
        "air_actual_vapor_pressure_kpa": 1.36,
        "air_saturation_vapor_pressure_kpa": 7.38,
        "air_vpd_kpa": 6.02,
        "light_lux": 1234.0,
        "ir_ambient_temp_c": 19.8,
        "leaf_temp_c": 18.7,
        "leaf_saturation_vapor_pressure_kpa": 5.02,
        "leaf_vpd_kpa": 3.66,
        "metrics_jsonb": {"battery_mv": 5010.0, "sensor_error_message": "private"},
    }
    values.update(overrides)
    return ExportRow(**values)


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, SessionLocal()


def telemetry_payload(timestamp: str, *, enabled: bool = True, moisture: float | None = 42.5) -> dict:
    pod = {
        "enabled": enabled,
        "soil_temperature_c": 20.1,
        "air_temperature_c": 21.2,
        "air_humidity_percent": 58.0,
        "air_pressure_hpa": 1008.5,
        "air_actual_vapor_pressure_kpa": 1.36,
        "air_saturation_vapor_pressure_kpa": 7.38,
        "air_vpd_kpa": 6.02,
        "light_lux": 1234.0,
        "leaf_temp_c": 18.7,
        "leaf_saturation_vapor_pressure_kpa": 5.02,
        "leaf_vpd_kpa": 3.66,
        "battery_mv": 5010.0,
    }
    if moisture is not None:
        pod["soil_moisture_percent"] = moisture
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": timestamp,
        "pods": {"pod-1": pod},
        "system_health": {
            "rpi_core": {"cpu_temp_c": 80.0},
            "watchdog": {
                "boot_id": "private-boot-id",
                "state": "recovering",
                "result": "private-restart-result",
                "restart_count": 987654321,
            },
            "spool": {"last_error_code": "private-spool-code", "database_size_bytes": 65536},
            "application": {"systemd_service_name": "private-edge-service", "process_id": 4321},
            "errors": [{"sensor": "wifi", "message": "do not export"}],
        },
    }


def reliability_system_health() -> dict:
    return {
        "watchdog": {
            "configured": True,
            "suppression": False,
            "state": "healthy",
            "result": "not_needed",
            "attempt_count": 2,
            "restart_count": 1,
            "reboot_count": 0,
            "last_healthy_heartbeat_at_utc": "2026-06-07T12:01:30Z",
            "reason": "private watchdog reason",
            "boot_id": "private-boot-id",
        },
        "spool": {
            "status": "OK",
            "disk_status": "OK",
            "pending_count": 3,
            "backlog_count": 4,
            "in_flight_count": 1,
            "dead_letter_count": 0,
            "oldest_pending_age_seconds": 45,
            "outage_duration_seconds": 30,
            "database_size_bytes": 65536,
            "free_space_bytes": 2147483648,
            "disk_usage_percent": 27.5,
            "last_error_code": "private-spool-code",
            "worker_state": "running",
        },
        "application": {
            "process_running": True,
            "process_uptime_seconds": 3600,
            "process_id": 4321,
            "systemd_available": True,
            "systemd_service_active": True,
            "systemd_active_state": "active",
            "systemd_service_name": "private-edge-service",
        },
    }


def enabled_settings(**overrides) -> Settings:
    values = {
        "grafana_cloud_export_enabled": True,
        "grafana_cloud_remote_write_url": "https://prometheus-prod.example/api/prom/push",
        "grafana_cloud_instance_id": "12345",
        "grafana_cloud_api_token": "secret-token",
    }
    values.update(overrides)
    return Settings(**values)


def test_row_to_metric_samples_exports_only_public_allowlisted_metrics():
    samples = row_to_metric_samples(sample_row())

    names = {sample.name for sample in samples}
    assert names == {
        "senior_pomidor_soil_moisture_percent",
        "senior_pomidor_soil_temperature_c",
        "senior_pomidor_air_temperature_c",
        "senior_pomidor_air_humidity_percent",
        "senior_pomidor_air_pressure_hpa",
        "senior_pomidor_air_vpd_kpa",
        "senior_pomidor_light_lux",
        "senior_pomidor_leaf_temp_c",
        "senior_pomidor_leaf_vpd_kpa",
    }
    encoded = encode_write_request(samples)
    assert b"adc_raw" not in encoded
    assert b"air_actual_vapor_pressure_kpa" not in encoded
    assert b"air_saturation_vapor_pressure_kpa" not in encoded
    assert b"ir_ambient_temp_c" not in encoded
    assert b"leaf_saturation_vapor_pressure_kpa" not in encoded
    assert b"battery_mv" not in encoded
    assert b"sensor_error_message" not in encoded


def test_labels_are_limited_and_sanitized():
    labels = public_labels("senior-pomidor/pi-001/telemetry", "pod 1")

    assert labels == {"device_id": "redacted", "pod_key": "pod_1"}
    assert set(labels) == {"device_id", "pod_key"}
    assert sanitize_label_value("192.168.1.10") == "redacted"
    assert sanitize_label_value("x" * 120) == "x" * 80


def test_row_to_metric_samples_uses_row_timestamp_and_labels():
    samples = row_to_metric_samples(sample_row(soil_moisture_percent=41.0, leaf_temp_c=None))
    sample_by_name = {sample.name: sample for sample in samples}

    moisture = sample_by_name["senior_pomidor_soil_moisture_percent"]
    assert moisture.labels == {"device_id": "pi-001", "pod_key": "pod-1"}
    assert moisture.value == 41.0
    assert moisture.timestamp_ms == 1_780_833_600_000
    assert "senior_pomidor_leaf_temp_c" not in sample_by_name


def test_disabled_pods_and_null_metric_fields_are_not_exported():
    assert row_to_metric_samples(sample_row(enabled=False)) == []

    samples = row_to_metric_samples(
        sample_row(
            soil_moisture_percent=None,
            soil_temperature_c=None,
            air_temperature_c=None,
            air_humidity_percent=None,
            air_pressure_hpa=None,
            air_vpd_kpa=None,
            light_lux=None,
            leaf_temp_c=None,
            leaf_vpd_kpa=None,
        )
    )
    assert samples == []


def test_export_once_skips_when_disabled_without_requiring_cloud_config():
    engine, db = make_db()
    try:
        state = ExportState.initial(datetime(2026, 6, 7, 12, 0, tzinfo=UTC), lookback_minutes=10)
        result = export_once(
            db,
            Settings(grafana_cloud_export_enabled=False),
            state,
            transport=FailingTransport(),
            now=datetime(2026, 6, 7, 12, 1, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    assert result.skipped_reason == "disabled"
    assert result.sent_samples == 0


def test_enabled_export_requires_remote_write_config():
    with pytest.raises(ExporterConfigError, match="GRAFANA_CLOUD_API_TOKEN"):
        validate_export_settings(
            Settings(
                grafana_cloud_export_enabled=True,
                grafana_cloud_remote_write_url="https://example.test/push",
                grafana_cloud_instance_id="12345",
                grafana_cloud_api_token=None,
            )
        )


def test_export_once_reads_postgres_rows_sends_metrics_and_advances_state():
    engine, db = make_db()
    transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T11:58:00Z"), source="mqtt")
        persist_telemetry(db, telemetry_payload("2026-06-07T12:00:30Z", moisture=None), source="mqtt")
        persist_telemetry(db, telemetry_payload("2026-06-07T12:01:00Z", enabled=False), source="mqtt")

        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))
        result = export_once(
            db,
            enabled_settings(),
            state,
            transport=transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    names = {sample.name for sample in transport.samples}
    assert "senior_pomidor_soil_moisture_percent" not in names
    assert "senior_pomidor_soil_temperature_c" in names
    assert "senior_pomidor_telemetry_freshness_seconds" not in names
    assert result.plant_samples == 8
    assert result.freshness_samples == 0
    assert result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert result.max_source_reading_id is not None
    assert state.since == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert state.last_reading_id == result.max_source_reading_id
    projection = repr(transport.samples)
    assert "private-boot-id" not in projection
    assert "private-spool-code" not in projection
    assert "private-edge-service" not in projection
    assert "private-restart-result" not in projection
    assert "process_id" not in projection


def test_edge_reliability_projection_has_exact_metrics_labels_and_one_hot_states():
    engine, db = make_db()
    try:
        payload = telemetry_payload("2026-06-07T12:02:00Z")
        payload["system_health"] = reliability_system_health()
        event = persist_telemetry(db, payload, source="mqtt")
        samples = edge_reliability_metric_samples(event, datetime(2026, 6, 7, 12, 3, tzinfo=UTC))
    finally:
        db.close()
        engine.dispose()

    state_names = {
        "senior_pomidor_edge_reliability_status",
        "senior_pomidor_edge_watchdog_status",
        "senior_pomidor_edge_watchdog_state",
        "senior_pomidor_edge_spool_status",
        "senior_pomidor_edge_spool_disk_status",
        "senior_pomidor_edge_application_status",
        "senior_pomidor_edge_reliability_freshness_status",
    }
    numeric_names = {
        "senior_pomidor_edge_watchdog_suppression",
        "senior_pomidor_edge_watchdog_configured",
        "senior_pomidor_edge_watchdog_attempt_count",
        "senior_pomidor_edge_watchdog_restart_count",
        "senior_pomidor_edge_watchdog_reboot_count",
        "senior_pomidor_edge_watchdog_healthy_heartbeat_age_seconds",
        "senior_pomidor_edge_spool_pending_records",
        "senior_pomidor_edge_spool_backlog_records",
        "senior_pomidor_edge_spool_in_flight_records",
        "senior_pomidor_edge_spool_dead_letter_records",
        "senior_pomidor_edge_spool_oldest_pending_age_seconds",
        "senior_pomidor_edge_spool_outage_duration_seconds",
        "senior_pomidor_edge_spool_database_size_bytes",
        "senior_pomidor_edge_spool_free_space_bytes",
        "senior_pomidor_edge_spool_disk_usage_percent",
        "senior_pomidor_edge_application_process_running",
        "senior_pomidor_edge_application_process_uptime_seconds",
        "senior_pomidor_edge_application_systemd_available",
        "senior_pomidor_edge_application_systemd_service_active",
        "senior_pomidor_edge_reliability_freshness_seconds",
    }
    assert {sample.name for sample in samples} == state_names | numeric_names
    for name in state_names:
        state_samples = [sample for sample in samples if sample.name == name]
        assert sum(sample.value for sample in state_samples) == 1.0
        assert all(
            set(sample.labels)
            == ({"device_id", "state"} if name.endswith("watchdog_state") else {"device_id", "status"})
            for sample in state_samples
        )
    assert all(set(sample.labels) == {"device_id"} for sample in samples if sample.name in numeric_names)
    values = {sample.name: sample.value for sample in samples if sample.name in numeric_names}
    assert values["senior_pomidor_edge_watchdog_healthy_heartbeat_age_seconds"] == 90.0
    assert values["senior_pomidor_edge_reliability_freshness_seconds"] == 60.0
    assert values["senior_pomidor_edge_spool_database_size_bytes"] == 65536.0

    encoded = encode_write_request(samples)
    for private_value in (
        b"private watchdog reason",
        b"private-boot-id",
        b"private-spool-code",
        b"private-edge-service",
        b"not_needed",
        b"4321",
    ):
        assert private_value not in encoded


@pytest.mark.parametrize(
    ("watchdog_update", "expected_state", "expected_status"),
    [
        ({"state": "recovering"}, "recovering", "WARN"),
        ({"state": "suppressed", "suppression": True}, "suppressed", "ALERT"),
        ({"state": "budget_exhausted"}, "budget_exhausted", "ALERT"),
        ({"state": "restart_failed", "result": "restart_failed"}, "recovery_failed", "ALERT"),
    ],
)
def test_edge_reliability_projection_maps_watchdog_states(watchdog_update, expected_state, expected_status):
    engine, db = make_db()
    try:
        payload = telemetry_payload("2026-06-07T12:02:00Z")
        payload["system_health"] = reliability_system_health()
        payload["system_health"]["watchdog"].update(watchdog_update)
        event = persist_telemetry(db, payload, source="mqtt")
        samples = edge_reliability_metric_samples(event, datetime(2026, 6, 7, 12, 3, tzinfo=UTC))
    finally:
        db.close()
        engine.dispose()

    assert (
        next(
            sample.value
            for sample in samples
            if sample.name == "senior_pomidor_edge_watchdog_state" and sample.labels["state"] == expected_state
        )
        == 1.0
    )
    assert (
        next(
            sample.value
            for sample in samples
            if sample.name == "senior_pomidor_edge_watchdog_status" and sample.labels["status"] == expected_status
        )
        == 1.0
    )


def test_edge_reliability_projection_uses_unknown_for_missing_blocks_and_stale_data():
    engine, db = make_db()
    try:
        missing_payload = telemetry_payload("2026-06-07T12:02:00Z")
        missing_payload["device_id"] = "pi-missing"
        missing_payload["system_health"] = {}
        missing_event = persist_telemetry(db, missing_payload, source="mqtt")

        stale_payload = telemetry_payload("2026-06-07T11:00:00Z")
        stale_payload["device_id"] = "pi-stale"
        stale_payload["system_health"] = reliability_system_health()
        stale_event = persist_telemetry(db, stale_payload, source="mqtt")
        now = datetime(2026, 6, 7, 12, 3, tzinfo=UTC)
        missing = edge_reliability_metric_samples(missing_event, now)
        stale = edge_reliability_metric_samples(stale_event, now)
    finally:
        db.close()
        engine.dispose()

    for metric in (
        "senior_pomidor_edge_reliability_status",
        "senior_pomidor_edge_watchdog_status",
        "senior_pomidor_edge_spool_status",
        "senior_pomidor_edge_application_status",
    ):
        assert (
            next(sample.value for sample in missing if sample.name == metric and sample.labels["status"] == "UNKNOWN")
            == 1.0
        )
        assert (
            next(sample.value for sample in stale if sample.name == metric and sample.labels["status"] == "UNKNOWN")
            == 1.0
        )
    assert not any("watchdog_attempt_count" in sample.name for sample in missing)
    assert (
        next(
            sample.value
            for sample in stale
            if sample.name == "senior_pomidor_edge_reliability_freshness_status" and sample.labels["status"] == "STALE"
        )
        == 1.0
    )


@pytest.mark.parametrize(
    ("block", "updates", "metric"),
    [
        ("spool", {"status": "DEGRADED"}, "senior_pomidor_edge_spool_status"),
        ("application", {"process_running": False}, "senior_pomidor_edge_application_status"),
    ],
)
def test_edge_reliability_projection_maps_critical_spool_and_application(block, updates, metric):
    engine, db = make_db()
    try:
        payload = telemetry_payload("2026-06-07T12:02:00Z")
        payload["system_health"] = reliability_system_health()
        payload["system_health"][block].update(updates)
        event = persist_telemetry(db, payload, source="mqtt")
        samples = edge_reliability_metric_samples(event, datetime(2026, 6, 7, 12, 3, tzinfo=UTC))
    finally:
        db.close()
        engine.dispose()

    assert (
        next(sample.value for sample in samples if sample.name == metric and sample.labels["status"] == "ALERT") == 1.0
    )


def test_export_once_marks_future_latest_reliability_event_unknown_instead_of_using_older_state():
    engine, db = make_db()
    transport = RecordingTransport()
    try:
        healthy = telemetry_payload("2026-06-07T12:00:00Z")
        healthy["system_health"] = reliability_system_health()
        persist_telemetry(db, healthy, source="mqtt")
        future = telemetry_payload("2026-06-07T12:10:00Z")
        future["system_health"] = reliability_system_health()
        future["system_health"]["watchdog"].update({"state": "suppressed", "suppression": True})
        persist_telemetry(db, future, source="mqtt")

        export_once(
            db,
            enabled_settings(),
            ExportState(since=datetime(2026, 6, 7, 11, 59, tzinfo=UTC)),
            transport=transport,
            now=datetime(2026, 6, 7, 12, 3, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    assert (
        next(
            sample.value
            for sample in transport.samples
            if sample.name == "senior_pomidor_edge_reliability_status" and sample.labels["status"] == "UNKNOWN"
        )
        == 1.0
    )
    assert not any(
        sample.name
        in {
            "senior_pomidor_edge_watchdog_suppression",
            "senior_pomidor_edge_spool_database_size_bytes",
            "senior_pomidor_edge_spool_free_space_bytes",
        }
        for sample in transport.samples
    )


def test_export_once_does_not_skip_rows_inserted_later_at_checkpoint_timestamp():
    engine, db = make_db()
    first_transport = RecordingTransport()
    second_transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T12:01:00Z", moisture=42.5), source="mqtt")
        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))

        first_result = export_once(
            db,
            enabled_settings(),
            state,
            transport=first_transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )

        late_payload = telemetry_payload("2026-06-07T12:01:00Z", moisture=35.0)
        late_payload["device_id"] = "pi-002"
        persist_telemetry(db, late_payload, source="mqtt")

        second_result = export_once(
            db,
            enabled_settings(),
            state,
            transport=second_transport,
            now=datetime(2026, 6, 7, 12, 3, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    assert first_result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert second_result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert second_result.max_source_reading_id is not None
    assert second_result.max_source_reading_id > (first_result.max_source_reading_id or 0)
    late_moisture = [
        sample
        for sample in second_transport.samples
        if sample.name == "senior_pomidor_soil_moisture_percent" and sample.labels["device_id"] == "pi-002"
    ]
    assert len(late_moisture) == 1
    assert late_moisture[0].value == 35.0


def test_export_once_sends_freshness_for_latest_enabled_pod():
    engine, db = make_db()
    transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T11:58:00Z"), source="mqtt")
        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))
        result = export_once(
            db,
            enabled_settings(),
            state,
            transport=transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    freshness = [sample for sample in transport.samples if sample.name == "senior_pomidor_telemetry_freshness_seconds"]
    assert len(freshness) == 1
    assert freshness[0].value == 240.0
    assert result.plant_samples == 0
    assert result.freshness_samples == 1


def test_export_once_republishes_latest_reliability_snapshot_without_advancing_plant_cursor():
    engine, db = make_db()
    first_transport = RecordingTransport()
    second_transport = RecordingTransport()
    try:
        old_payload = telemetry_payload("2026-06-07T12:00:00Z")
        old_payload["system_health"] = reliability_system_health()
        old_payload["system_health"]["watchdog"]["state"] = "suppressed"
        old_payload["system_health"]["watchdog"]["suppression"] = True
        persist_telemetry(db, old_payload, source="mqtt")

        latest_payload = telemetry_payload("2026-06-07T12:02:00Z")
        latest_payload["system_health"] = reliability_system_health()
        persist_telemetry(db, latest_payload, source="mqtt")

        second_device = telemetry_payload("2026-06-07T12:01:00Z")
        second_device["device_id"] = "pi-002"
        second_device["system_health"] = reliability_system_health()
        second_device["system_health"]["spool"].update({"status": "DEGRADED", "disk_status": "DEGRADED"})
        persist_telemetry(db, second_device, source="mqtt")

        state = ExportState(since=datetime(2026, 6, 7, 12, 1, 30, tzinfo=UTC))
        first = export_once(
            db,
            enabled_settings(),
            state,
            transport=first_transport,
            now=datetime(2026, 6, 7, 12, 3, tzinfo=UTC),
        )
        checkpoint = (state.since, state.last_reading_id)
        second = export_once(
            db,
            enabled_settings(),
            state,
            transport=second_transport,
            now=datetime(2026, 6, 7, 12, 4, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    for transport in (first_transport, second_transport):
        overall = [sample for sample in transport.samples if sample.name == "senior_pomidor_edge_reliability_status"]
        assert {sample.labels["device_id"] for sample in overall} == {"pi-001", "pi-002"}
        assert (
            next(
                sample.value
                for sample in transport.samples
                if sample.name == "senior_pomidor_edge_watchdog_state"
                and sample.labels == {"device_id": "pi-001", "state": "healthy"}
            )
            == 1.0
        )
        assert not any(
            sample.name == "senior_pomidor_edge_watchdog_state"
            and sample.labels == {"device_id": "pi-001", "state": "suppressed"}
            and sample.value == 1.0
            for sample in transport.samples
        )
    assert first.plant_samples > 0
    assert first.reliability_samples > 0
    assert second.plant_samples == 0
    assert second.reliability_samples == first.reliability_samples
    assert (state.since, state.last_reading_id) == checkpoint


def test_remote_write_transport_posts_snappy_protobuf_with_basic_auth():
    opener = FakeOpener()
    transport = RemoteWriteTransport(
        url="https://prometheus-prod.example/api/prom/push",
        instance_id="12345",
        api_token="secret-token",
        compressor=FakeCompressor(),
        opener=opener,
    )

    transport.send(
        [
            MetricSample(
                name="senior_pomidor_soil_moisture_percent",
                labels={"device_id": "pi-001", "pod_key": "pod-1"},
                value=42.5,
                timestamp_ms=int((datetime(2026, 6, 7, 12, 0, tzinfo=UTC) + timedelta()).timestamp() * 1000),
            )
        ]
    )

    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == "https://prometheus-prod.example/api/prom/push"
    assert request.get_method() == "POST"
    assert timeout == 10.0
    assert request.headers["Authorization"] == "Basic MTIzNDU6c2VjcmV0LXRva2Vu"
    assert request.headers["Content-encoding"] == "snappy"
    assert request.headers["Content-type"] == "application/x-protobuf"
    payload = request.data
    assert isinstance(payload, bytes)
    assert payload.startswith(b"snappy:")
    assert b"senior_pomidor_soil_moisture_percent" in payload
    assert b"device_id" in payload
    assert b"pod_key" in payload


def test_remote_write_transport_wraps_connection_timeouts():
    transport = RemoteWriteTransport(
        url="https://prometheus-prod.example/api/prom/push",
        instance_id="12345",
        api_token="secret-token",
        compressor=FakeCompressor(),
        opener=TimeoutOpener(),
    )

    with pytest.raises(RemoteWriteError, match="connection timed out"):
        transport.send(
            [
                MetricSample(
                    name="senior_pomidor_soil_moisture_percent",
                    labels={"device_id": "pi-001", "pod_key": "pod-1"},
                    value=42.5,
                    timestamp_ms=int(datetime(2026, 6, 7, 12, 0, tzinfo=UTC).timestamp() * 1000),
                )
            ]
        )


def test_run_forever_retries_after_remote_write_failure(monkeypatch):
    class StopLoopError(RuntimeError):
        pass

    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RemoteWriteError("temporary remote write outage")

    monkeypatch.setattr(grafana_cloud_exporter, "settings", enabled_settings(grafana_cloud_export_interval_seconds=0))
    monkeypatch.setattr(grafana_cloud_exporter, "build_transport", lambda export_settings: RecordingTransport())
    monkeypatch.setattr(grafana_cloud_exporter, "export_once", fail_once)
    monkeypatch.setattr(grafana_cloud_exporter.time, "sleep", lambda seconds: (_ for _ in ()).throw(StopLoopError()))

    with pytest.raises(StopLoopError):
        run_forever()

    assert attempts == 1


def test_run_forever_retries_after_unexpected_export_failure(monkeypatch):
    class StopLoopError(RuntimeError):
        pass

    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("temporary database outage")

    monkeypatch.setattr(grafana_cloud_exporter, "settings", enabled_settings(grafana_cloud_export_interval_seconds=0))
    monkeypatch.setattr(grafana_cloud_exporter, "build_transport", lambda export_settings: RecordingTransport())
    monkeypatch.setattr(grafana_cloud_exporter, "export_once", fail_once)
    monkeypatch.setattr(grafana_cloud_exporter.time, "sleep", lambda seconds: (_ for _ in ()).throw(StopLoopError()))

    with pytest.raises(StopLoopError):
        run_forever()

    assert attempts == 1
