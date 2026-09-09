from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.map.models import (
    Identifier,
    ProfileIdentity,
    Sha256Digest,
    StrictModel,
    TopologyMode,
)


class CapabilityOperator(StrEnum):
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssertionKind(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


class CapabilityReason(StrEnum):
    NO_FRESH_VALID_OBSERVATION = "NO_FRESH_VALID_OBSERVATION"
    INVALID_OBSERVATION = "INVALID_OBSERVATION"
    EXPLICIT_READ_FAILURE = "EXPLICIT_READ_FAILURE"
    MISSING_UPDATE = "MISSING_UPDATE"
    MISSING_BINDING = "MISSING_BINDING"
    MISSING_CALIBRATION = "MISSING_CALIBRATION"
    CLOCK_INVALID = "CLOCK_INVALID"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    DISABLED = "DISABLED"
    UNKNOWN_HISTORY = "UNKNOWN_HISTORY"


class CapabilityFidelity(StrEnum):
    INGEST_TIME_PROXY = "INGEST_TIME_PROXY"
    GENERATION_TIME_PROXY = "GENERATION_TIME_PROXY"
    RECONSTRUCTED = "RECONSTRUCTED"
    UNKNOWN = "UNKNOWN"


class TargetCapabilityExpression(StrictModel):
    target_id: Identifier
    capability: Identifier
    operator: CapabilityOperator


class EvidenceReference(StrictModel):
    evidence_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[0-9a-f]{64}$")]
    evidence_kind: Literal[
        "SOURCE_RECEIPT", "CHANNEL_VALUE", "CHANNEL_INVALID_VALUE", "EXPLICIT_ERROR", "DISABLED_CHANNEL"
    ]
    fidelity: CapabilityFidelity


class CapabilityInterval(StrictModel):
    start: datetime
    end: datetime
    capability: CapabilityStatus
    freshness: FreshnessStatus
    reason: CapabilityReason
    assertion: AssertionKind
    fidelity: CapabilityFidelity
    evidence_refs: tuple[EvidenceReference, ...] = ()

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("interval timestamps must be UTC-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("capability interval must be non-empty")
        return self


class TargetCapabilityResult(StrictModel):
    target_id: Identifier
    capability: Identifier
    operator: CapabilityOperator
    intervals: tuple[CapabilityInterval, ...]


class CapabilityEvaluation(StrictModel):
    schema_version: Literal["senior-pomidor.map.v1"] = "senior-pomidor.map.v1"
    evaluated_at: datetime
    window_start: datetime
    window_end: datetime
    coverage_start: datetime
    coverage_end: datetime
    mode: TopologyMode
    data_cutoff: datetime
    topology_revision_id: Identifier
    topology_digest: Sha256Digest
    profile_identities: tuple[ProfileIdentity, ...]
    fidelity: CapabilityFidelity
    targets: tuple[TargetCapabilityResult, ...]
    digest: Sha256Digest

    @field_validator("evaluated_at", "window_start", "window_end", "coverage_start", "coverage_end", "data_cutoff")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("evaluation timestamps must be UTC-aware")
        return value.astimezone(UTC)


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical content cannot contain non-finite numbers")
        return format(value, ".15g")
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    return value


def canonical_capability_bytes(result: CapabilityEvaluation) -> bytes:
    payload = _canonical(result.model_dump(mode="python", exclude={"digest"}))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def compute_capability_digest(result: CapabilityEvaluation) -> str:
    return hashlib.sha256(canonical_capability_bytes(result)).hexdigest()


# Short aliases make the internal contract convenient without creating a second schema.
EvaluationRequest = TargetCapabilityExpression
CapabilityEvaluationRequest = TargetCapabilityExpression
TargetExpression = TargetCapabilityExpression
CapabilityEvaluationResult = CapabilityEvaluation
CapabilityEvaluationBatch = CapabilityEvaluation
CapabilityResultInterval = CapabilityInterval
TargetCapability = TargetCapabilityExpression
