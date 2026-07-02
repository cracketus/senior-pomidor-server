import json
from datetime import UTC, datetime, timedelta

from tools import public_status


def test_load_compose_ps_accepts_json_array_and_lines() -> None:
    array = '[{"Service":"api","State":"running","Health":"healthy"}]'
    lines = '{"Service":"api","State":"running","Health":"healthy"}\n{"Service":"worker","State":"running"}'

    assert public_status.load_compose_ps(array) == [{"Service": "api", "State": "running", "Health": "healthy"}]
    assert [service["Service"] for service in public_status.load_compose_ps(lines)] == ["api", "worker"]


def test_normalize_compose_service_sanitizes_public_fields() -> None:
    raw = {
        "Service": "api",
        "Name": "senior-pomidor-server-api-1",
        "ID": "container-id",
        "Publishers": [{"URL": "0.0.0.0", "PublishedPort": 8000}],
        "State": "running",
        "Health": "healthy",
        "ExitCode": 0,
    }

    normalized = public_status.normalize_compose_service(raw)

    assert normalized == {
        "service": "api",
        "category": "core",
        "state": "running",
        "health": "healthy",
        "exit_code": 0,
        "status": "ok",
    }
    assert "container-id" not in json.dumps(normalized)
    assert "8000" not in json.dumps(normalized)


def test_overall_status_handles_ok_degraded_stale_and_unknown() -> None:
    critical = [
        {"service": "api", "status": "ok"},
        {"service": "worker", "status": "ok"},
        {"service": "postgres", "status": "ok"},
        {"service": "mosquitto", "status": "ok"},
    ]

    assert public_status.calculate_overall_status(critical, {"status": "ok"}, [{"status": "ok"}]) == "ok"
    assert public_status.calculate_overall_status(critical, {"status": "degraded"}, [{"status": "ok"}]) == "degraded"
    assert public_status.calculate_overall_status(critical, {"status": "ok"}, [{"status": "stale"}]) == "stale"
    assert public_status.calculate_overall_status([], {"status": "degraded"}, []) == "unknown"


def test_normalize_edge_device_reports_freshness_and_buffers() -> None:
    now = datetime(2026, 6, 29, 12, 5, tzinfo=UTC)
    event = {
        "device_id": "pi-001",
        "received_at": "2026-06-29T12:00:00Z",
        "health_alerts": [{"metric": "cpu_temp_c"}],
        "system_health": {
            "rpi_core": {
                "telemetry_buffer_file_count": 2,
                "photo_buffer_file_count": 1,
                "disk_free_percent": 72.5,
            },
            "network": {
                "wifi_connected": False,
                "wifi_profile_count": 0,
                "internet_reachable": False,
                "dns_resolution_ok": True,
                "default_gateway_reachable": False,
                "last_recovery_result": "failed",
                "last_recovery_exit_code": 2,
                "ssid": "private-wifi",
                "ip_address": "192.168.1.25",
                "last_recovery_action": "wpa_cli -i wlan0 reconfigure",
            },
        },
    }

    device = public_status.normalize_edge_device(event, now)

    assert device["device_id"] == "pi-001"
    assert device["status"] == "degraded"
    assert device["minutes_since_telemetry"] == 5.0
    assert device["health_alert_count"] == 1
    assert device["telemetry_buffer_file_count"] == 2
    assert device["photo_buffer_file_count"] == 1
    assert device["disk_free_percent"] == 72.5
    assert device["network_health"] == {
        "wifi_connected": False,
        "wifi_profile_count": 0,
        "internet_reachable": False,
        "dns_resolution_ok": True,
        "last_recovery_result": "failed",
        "last_recovery_exit_code": 2,
    }
    public_json = json.dumps(device)
    assert "private-wifi" not in public_json
    assert "192.168.1.25" not in public_json
    assert "wpa_cli" not in public_json


def test_edge_status_marks_stale_after_threshold() -> None:
    assert public_status.edge_status(None, 0) == "unknown"
    assert public_status.edge_status(public_status.EDGE_STALE_AFTER_MINUTES + 0.1, 0) == "stale"
    assert public_status.edge_status(1, 1) == "degraded"
    assert public_status.edge_status(1, 0) == "ok"


def test_write_status_file_skips_unchanged_content(tmp_path) -> None:
    target = tmp_path / "status" / "status.json"
    status = {"schema_version": public_status.SCHEMA_VERSION, "generated_at_utc": "2026-06-29T12:00:00Z"}

    assert public_status.write_status_file(status, target) is True
    assert public_status.write_status_file(status, target) is False


def test_build_status_document_uses_sanitized_collectors(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        public_status,
        "docker_compose_ps",
        lambda _project_dir: [
            {"Service": "api", "State": "running", "Health": "healthy", "ID": "secret-container-id"},
            {"Service": "worker", "State": "running", "Health": "healthy"},
            {"Service": "postgres", "State": "running", "Health": "healthy"},
            {"Service": "mosquitto", "State": "running", "Health": "healthy"},
        ],
    )
    monkeypatch.setattr(public_status, "collect_readiness", lambda _api_base_url: {"status": "ok", "ready": True})
    monkeypatch.setattr(
        public_status,
        "collect_latest_devices",
        lambda _api_base_url: [
            {
                "device_id": "pi-001",
                "received_at": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "health_alerts": [],
            }
        ],
    )

    document = public_status.build_status_document(tmp_path, "http://test", now)

    assert document["schema_version"] == public_status.SCHEMA_VERSION
    assert document["overall_status"] == "ok"
    assert "secret-container-id" not in json.dumps(document)


def test_collect_readiness_preserves_unready_response_body(monkeypatch) -> None:
    monkeypatch.setattr(
        public_status,
        "get_json",
        lambda _url: {"ready": False, "database": "ok", "migration": "mismatch"},
    )

    readiness = public_status.collect_readiness("http://test")

    assert readiness == {
        "ready": False,
        "status": "degraded",
        "database": "ok",
        "migration": "mismatch",
    }
