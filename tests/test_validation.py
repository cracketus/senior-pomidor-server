import pytest

from app.validation import (
    ValidationError,
    validate_device_id,
    validate_photo_id,
    validate_pod_key,
    validate_topic_device,
)


def test_validate_topic_device_accepts_matching_topic():
    validate_topic_device("senior-pomidor/pi-001/telemetry", "senior-pomidor", "pi-001")


def test_validate_topic_device_rejects_mismatch():
    with pytest.raises(ValidationError):
        validate_topic_device("senior-pomidor/pi-002/telemetry", "senior-pomidor", "pi-001")


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (validate_device_id, "../pi-001"),
        (validate_device_id, "pi/001"),
        (validate_device_id, "pi 001"),
        (validate_device_id, "pi\x00001"),
        (validate_photo_id, ".."),
        (validate_photo_id, "photo\\1"),
        (validate_pod_key, "pod/1"),
    ],
)
def test_safe_identifier_validation_rejects_path_and_control_values(validator, value):
    with pytest.raises(ValidationError):
        validator(value)


def test_safe_identifier_validation_accepts_expected_characters():
    assert validate_device_id("pi-001.alpha") == "pi-001.alpha"
    assert validate_photo_id("20260611T174220048308Z_balcony-edge-01") == "20260611T174220048308Z_balcony-edge-01"
    assert validate_pod_key("pod_1") == "pod_1"
