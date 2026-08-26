from typing import Literal

from app.validation import ValidationError, validate_device_id, validate_safe_identifier

DeploymentMode = Literal["development", "staging", "rehearsal", "production"]


def validate_environment_device(
    device_id: object,
    *,
    deployment_mode: DeploymentMode,
    staging_device_prefix: str,
) -> str:
    """Reject staging/production identity crossover before persistence."""
    normalized_device_id = validate_device_id(device_id)
    prefix = validate_safe_identifier(staging_device_prefix, "staging_device_prefix", 64)

    is_staging_device = normalized_device_id.startswith(prefix)
    if deployment_mode == "staging" and not is_staging_device:
        raise ValidationError("device is outside the staging identity boundary")
    if deployment_mode == "production" and is_staging_device:
        raise ValidationError("staging device is not accepted in production")
    return normalized_device_id
