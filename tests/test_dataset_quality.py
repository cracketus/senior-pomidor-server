import json
from copy import deepcopy
from datetime import UTC, datetime

from jsonschema import validate

from tools import dataset_quality, public_status


def persisted_row(client):
    response = client.post(
        "/api/v1/edge/telemetry",
        json={
            "schema_version": "senior-pomidor.edge.telemetry.v2",
            "record_id": "quality:1",
            "device_id": "quality-edge",
            "timestamp_utc": "2026-09-01T12:00:00Z",
            "pods": [{"pod_key": "pod-1", "soil_moisture_percent": 42.0}],
        },
    )
    assert response.status_code == 202
    row = client.get("/api/v1/devices/quality-edge/latest").json()
    row["received_at"] = "2026-09-01T12:00:01Z"
    return row


def test_quality_inspects_actual_stored_readback(client):
    report = dataset_quality.inspect_rows([persisted_row(client)])
    assert report["status"] == "PASS"
    assert report["estimated_missing_observations"] is None
    assert report["counts"]["missing_metric_values"] > 0


def test_duplicate_time_order_range_and_gap_evidence(client):
    first = persisted_row(client)
    second = deepcopy(first)
    second.update(record_id="quality:2", timestamp_utc="2026-09-01T12:10:00Z")
    second["readings"][0]["metrics"]["soil_moisture_percent"] = 101
    report = dataset_quality.inspect_rows([second, first, first], expected_interval_seconds=300)
    assert report["status"] == "FAIL"
    assert report["estimated_missing_observations"] == 1
    for code in (
        "duplicate_record_id",
        "duplicate_observation",
        "out_of_order",
        "out_of_range_metric",
        "observation_after_receive",
    ):
        assert report["counts"][code] > 0


def test_private_values_never_enter_quality_report(client):
    row = persisted_row(client)
    marker = "SYNTHETIC_PRIVATE_PATH_/home/example/raw"
    row.update(device_id=marker, raw_payload_jsonb={"private": marker})
    report = dataset_quality.inspect_rows([row])
    assert report["status"] == "FAIL"
    assert marker not in json.dumps(report)


def test_offline_cli_round_trip_and_bounded_errors(client, tmp_path, capsys):
    source = tmp_path / "snapshot.jsonl"
    source.write_text(json.dumps(persisted_row(client)) + "\n", encoding="utf-8")
    before = source.read_bytes()
    assert dataset_quality.main([str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    from pathlib import Path

    schema = json.loads(Path("docs/schemas/dataset-quality-v1.schema.json").read_text())
    validate(report, schema)
    assert source.read_bytes() == before
    source.write_text("SYNTHETIC_PRIVATE_BAD_INPUT", encoding="utf-8")
    assert dataset_quality.main([str(source)]) == 2
    output = capsys.readouterr().out
    assert "SYNTHETIC_PRIVATE" not in output
    assert str(source) not in output


def test_public_status_rejects_private_strings_even_in_allowlisted_fields(monkeypatch):
    marker = "SYNTHETIC_PRIVATE_/home/example/192.0.2.1"
    network = dict.fromkeys(public_status.PUBLIC_NETWORK_HEALTH_FIELDS, marker)
    network["new_private_field"] = marker
    event = {
        "device_id": marker,
        "received_at": "2026-09-01T12:00:00Z",
        "system_health": {"network": network, "raw_payload": marker},
        "new_private_field": marker,
    }
    projected = public_status.normalize_edge_device(event, datetime(2026, 9, 1, 12, 1, tzinfo=UTC))
    assert marker not in json.dumps(projected)
    assert all(value is None for value in projected["network_health"].values())
    assert set(projected["network_health"]) == set(public_status.PUBLIC_NETWORK_HEALTH_FIELDS)
    monkeypatch.setattr(public_status, "get_json", lambda _: {"ready": False, "database": marker, "migration": marker})
    assert marker not in json.dumps(public_status.collect_readiness("http://test"))
    assert marker not in json.dumps(
        public_status.normalize_compose_service({"Name": marker, "State": marker, "Health": marker})
    )


def test_empty_input_and_large_report_are_bounded():
    assert dataset_quality.inspect_rows([])["status"] == "FAIL"
    report = dataset_quality.inspect_rows([None] * 600)
    assert len(report["findings"]) == 500
    assert report["findings_truncated"] is True
    assert report["counts"]["invalid_row"] == 600


def test_public_device_projection_has_reviewed_exact_shape():
    output = public_status.normalize_edge_device({}, datetime(2026, 9, 1, tzinfo=UTC))
    assert set(output) == {
        "device_id",
        "status",
        "last_telemetry_received_at",
        "minutes_since_telemetry",
        "health_alert_count",
        "telemetry_buffer_file_count",
        "photo_buffer_file_count",
        "disk_free_percent",
        "network_health",
    }


def test_malformed_schema_and_huge_numeric_values_are_bounded(client):
    row = persisted_row(client)
    row["schema_version"] = []
    assert dataset_quality.inspect_rows([row])["counts"]["unsupported_schema"] == 1
    row = persisted_row(client)
    row["readings"][0]["metrics"]["air_temperature_c"] = 10**1000
    assert dataset_quality.inspect_rows([row])["counts"]["out_of_range_metric"] == 1
    assert public_status.numeric_or_none(10**1000) is None


def test_malformed_values_through_cli_do_not_leak(client, tmp_path, capsys):
    row = persisted_row(client)
    for bad_schema in ([], {}):
        row["schema_version"] = bad_schema
        source = tmp_path / "malformed.jsonl"
        source.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert dataset_quality.main([str(source)]) == 1
        assert json.loads(capsys.readouterr().out)["counts"]["unsupported_schema"] == 1
    row["schema_version"] = "senior-pomidor.edge.telemetry.v2"
    for value in (10**1000, -(10**1000)):
        row["readings"][0]["metrics"]["air_temperature_c"] = value
        source.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert dataset_quality.main([str(source)]) == 1
        assert json.loads(capsys.readouterr().out)["counts"]["out_of_range_metric"] == 1
        assert public_status.numeric_or_none(value) is None
