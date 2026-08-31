import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.operator_edge_reliability import OperatorEdgeReliabilityV1
from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2, validate_telemetry_payload

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "contracts"
EDGE_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "edge_integration"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_schemas_are_valid_json() -> None:
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"


def test_telemetry_contract_fixtures_match_runtime_validation() -> None:
    telemetry_v1 = load_json(FIXTURE_DIR / "telemetry_v1.json")
    telemetry_v2 = load_json(FIXTURE_DIR / "telemetry_v2.json")

    assert telemetry_v1["schema_version"] == TELEMETRY_SCHEMA
    assert telemetry_v2["schema_version"] == TELEMETRY_SCHEMA_V2
    assert telemetry_v2["record_id"] == "spool:pi-001:20260702T120000Z"
    assert validate_telemetry_payload(telemetry_v1)[0] == "pi-001"
    assert validate_telemetry_payload(telemetry_v2)[0] == "pi-001"


def test_telemetry_v2_schema_bounds_record_id() -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    record_id = schema["properties"]["record_id"]

    assert record_id == {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "pattern": "^[A-Za-z0-9_.:-]+$",
    }


def test_telemetry_v2_fixture_serialization_round_trip() -> None:
    telemetry_v2 = load_json(FIXTURE_DIR / "telemetry_v2.json")

    assert json.loads(json.dumps(telemetry_v2, sort_keys=True)) == telemetry_v2


def test_operator_edge_reliability_fixture_schema_and_pydantic_round_trip() -> None:
    schema = load_json(SCHEMA_DIR / "operator-edge-reliability-v1.schema.json")
    fixture = load_json(FIXTURE_DIR / "operator_edge_reliability_v1.json")

    Draft202012Validator(schema).validate(fixture)
    parsed = OperatorEdgeReliabilityV1.model_validate(fixture)

    assert parsed.model_dump(mode="json") == fixture


def test_server_and_copied_edge_reliability_fixtures_validate_and_round_trip() -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    validator = Draft202012Validator(schema)
    server_fixture = load_json(FIXTURE_DIR / "telemetry_v2.json")
    copied_edge_fixture = load_json(EDGE_FIXTURE_DIR / "telemetry_reliability.json")

    assert copied_edge_fixture["provenance"] == {
        "source_repository": "senior-pomidor-plant-v2",
        "source_revision": "e1244ae0f9e4f08e5b272839c970e13f4fb7dcc9",
        "schema_path": "schemas/edge-telemetry-v2.schema.json",
        "runtime_paths": [
            "src/telemetry_spool.py",
            "src/sensors/application_health.py",
            "src/watchdog.py",
        ],
        "note": "Synthetic private-safe copy; tests do not access the edge checkout.",
    }
    assert server_fixture["system_health"]["application"]["service_manager"] == "systemd"
    assert "service_manager" not in copied_edge_fixture["payload"]["system_health"]["application"]
    for payload in (server_fixture, copied_edge_fixture["payload"]):
        validator.validate(payload)
        assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_producer_schema_rejects_malformed_reliability_fields() -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    payload = load_json(FIXTURE_DIR / "telemetry_v2.json")
    payload["system_health"]["spool"]["disk_usage_percent"] = 101

    errors = list(Draft202012Validator(schema).iter_errors(payload))

    assert len(errors) == 1
    assert list(errors[0].absolute_path)[-2:] == ["spool", "disk_usage_percent"]


@pytest.mark.parametrize(
    "application",
    [
        {"service_manager": "none", "process_running": True, "systemd_available": False},
        {"service_manager": "systemd", "process_running": True},
    ],
)
def test_producer_schema_rejects_ambiguous_or_incomplete_application_modes(application: dict) -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    payload = load_json(FIXTURE_DIR / "telemetry_v2.json")
    payload["system_health"]["application"] = application

    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_producer_schema_accepts_explicit_process_only_and_legacy_systemd_modes() -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    validator = Draft202012Validator(schema)
    payload = load_json(FIXTURE_DIR / "telemetry_v2.json")

    payload["system_health"]["application"] = {"service_manager": "none", "process_running": True}
    validator.validate(payload)

    payload["system_health"]["application"] = {"process_running": True}
    validator.validate(payload)

    payload["system_health"]["application"] = {
        "process_running": True,
        "systemd_available": True,
        "systemd_service_active": True,
    }
    validator.validate(payload)


@pytest.mark.parametrize("aggregate", [{}, {"reasons": []}])
def test_producer_schema_requires_aggregate_identity_and_state(aggregate: dict) -> None:
    schema = load_json(SCHEMA_DIR / "telemetry-v2.schema.json")
    payload = load_json(FIXTURE_DIR / "telemetry_v2.json")
    payload["system_health"]["aggregate"] = aggregate

    required_errors = {
        error.message for error in Draft202012Validator(schema).iter_errors(payload) if error.validator == "required"
    }

    assert required_errors == {
        "'schema_version' is a required property",
        "'state' is a required property",
    }


def test_photo_contract_fixture_matches_active_schema() -> None:
    photo = load_json(FIXTURE_DIR / "photo_v1.json")

    assert photo["schema_version"] == PHOTO_SCHEMA
    assert photo["captured_at_utc"].endswith("Z")


def test_health_summary_contract_fixture_is_versioned() -> None:
    summary = load_json(FIXTURE_DIR / "health_summary_v1.json")
    schema = load_json(SCHEMA_DIR / "health-summary-v1.schema.json")

    Draft202012Validator(schema).validate(summary)
    assert summary["schema_version"] == "health_summary_v1"
    assert summary["status"] in {"OK", "WARN", "ALERT", "UNKNOWN"}
    assert summary["generated_at"].endswith("Z")
    assert summary["data_freshness"]["worker_max_age_seconds"] == 90
    assert summary["data_freshness"]["telemetry_max_age_seconds"] == 1200
    assert summary["data_freshness"]["node_id"] == "pi-001"
    assert summary["components"]["edge_reliability"]["reason_codes"] == ["edge_watchdog_restart_recovery"]
