import json
from pathlib import Path

from app.validation import PHOTO_SCHEMA, TELEMETRY_SCHEMA, TELEMETRY_SCHEMA_V2, validate_telemetry_payload

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "contracts"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_schemas_are_valid_json() -> None:
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = load_json(path)
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


def test_photo_contract_fixture_matches_active_schema() -> None:
    photo = load_json(FIXTURE_DIR / "photo_v1.json")

    assert photo["schema_version"] == PHOTO_SCHEMA
    assert photo["captured_at_utc"].endswith("Z")


def test_health_summary_contract_fixture_is_versioned() -> None:
    summary = load_json(FIXTURE_DIR / "health_summary_v1.json")

    assert summary["schema_version"] == "health_summary_v1"
    assert summary["status"] in {"OK", "WARN", "ALERT", "UNKNOWN"}
    assert summary["generated_at"].endswith("Z")
    assert summary["data_freshness"]["worker_max_age_seconds"] == 90
    assert summary["data_freshness"]["telemetry_max_age_seconds"] == 1200
