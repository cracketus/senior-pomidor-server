import pytest

from app.validation import ValidationError, validate_topic_device


def test_validate_topic_device_accepts_matching_topic():
    validate_topic_device("senior-pomidor/pi-001/telemetry", "senior-pomidor", "pi-001")


def test_validate_topic_device_rejects_mismatch():
    with pytest.raises(ValidationError):
        validate_topic_device("senior-pomidor/pi-002/telemetry", "senior-pomidor", "pi-001")
