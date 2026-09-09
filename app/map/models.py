from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "senior-pomidor.map.v1"
MAX_ENTITIES_PER_NAMESPACE = 256
MAX_RELATIONSHIPS = 512
MAX_REVISIONS = 128

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")]
Version = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
ShortText = Annotated[str, Field(min_length=1, max_length=256)]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TopologyMode(StrEnum):
    AS_KNOWN_CORE = "AS_KNOWN_CORE"
    RECONSTRUCTED = "RECONSTRUCTED"


class ProvenanceKind(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    DOCUMENTED = "DOCUMENTED"
    MEASURED = "MEASURED"


class AssetKind(StrEnum):
    SENSOR_DEVICE = "SENSOR_DEVICE"
    SENSOR_PROBE = "SENSOR_PROBE"
    STRUCTURE = "STRUCTURE"


class SourceKind(StrEnum):
    EDGE_NODE = "EDGE_NODE"
    SIMULATOR = "SIMULATOR"


class TargetKind(StrEnum):
    PLANT = "PLANT"
    CONTAINER = "CONTAINER"


class Unit(StrEnum):
    PERCENT = "PERCENT"
    CELSIUS = "CELSIUS"
    RAW_ADC = "RAW_ADC"
    BOOLEAN = "BOOLEAN"


class RelationshipKind(StrEnum):
    CONTAINMENT = "CONTAINMENT"
    PHYSICAL_LINK = "PHYSICAL_LINK"
    DATA_FLOW = "DATA_FLOW"
    CAPABILITY_DEPENDENCY = "CAPABILITY_DEPENDENCY"


class EntityNamespace(StrEnum):
    PHYSICAL_ASSET = "PHYSICAL_ASSET"
    SOURCE = "SOURCE"
    SOURCE_CHANNEL = "SOURCE_CHANNEL"
    TARGET = "TARGET"
    DEPLOYMENT = "DEPLOYMENT"
    CAPABILITY_PROFILE = "CAPABILITY_PROFILE"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC-aware")
    return value.astimezone(UTC)


class EffectiveInterval(StrictModel):
    effective_from: datetime
    effective_to: datetime | None = None

    @field_validator("effective_from", "effective_to")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.effective_to is not None and self.effective_from >= self.effective_to:
            raise ValueError("effective interval must be non-empty")
        return self

    def contains(self, at: datetime) -> bool:
        return self.effective_from <= at and (self.effective_to is None or at < self.effective_to)

    def overlaps(self, other: EffectiveInterval) -> bool:
        return (self.effective_to is None or other.effective_from < self.effective_to) and (
            other.effective_to is None or self.effective_from < other.effective_to
        )


class Provenance(StrictModel):
    provenance_id: Identifier
    kind: ProvenanceKind
    reference: ShortText
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return _utc(value)


class NumericRange(StrictModel):
    unit: Unit
    minimum: float
    maximum: float

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def validate_finite(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError("numeric bounds must be finite")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError("numeric range minimum must be less than maximum")
        return self


class PhysicalAsset(StrictModel):
    asset_id: Identifier
    kind: AssetKind
    label: ShortText


class Source(StrictModel):
    source_id: Identifier
    kind: SourceKind
    label: ShortText


class SourceChannel(StrictModel):
    channel_id: Identifier
    source_id: Identifier
    source_local_key: Identifier
    quantity: Identifier
    value_range: NumericRange


class Target(StrictModel):
    target_id: Identifier
    kind: TargetKind
    label: ShortText


class Deployment(StrictModel):
    deployment_id: Identifier
    asset_id: Identifier
    target_id: Identifier
    interval: EffectiveInterval


class CapabilityProfile(StrictModel):
    profile_id: Identifier
    version: Version
    capability: Identifier
    input_range: NumericRange
    max_age_seconds: Annotated[int, Field(ge=1, le=604_800)]
    calibration_provenance: Provenance

    @field_validator("max_age_seconds", mode="before")
    @classmethod
    def validate_max_age_type(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("max_age_seconds must be an integer")
        return value


class EntityRef(StrictModel):
    namespace: EntityNamespace
    entity_id: Identifier


class Relationship(StrictModel):
    relationship_id: Identifier
    kind: RelationshipKind
    from_ref: EntityRef
    to_ref: EntityRef


class Binding(StrictModel):
    binding_id: Identifier
    channel_id: Identifier
    target_id: Identifier
    capability: Identifier
    profile_id: Identifier
    interval: EffectiveInterval
    provenance: Provenance


class TopologyRevision(StrictModel):
    schema_version: str
    revision_id: Identifier
    recorded_at: datetime
    interval: EffectiveInterval
    provenance: Provenance
    supersedes: Identifier | None = None
    physical_assets: Annotated[tuple[PhysicalAsset, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    sources: Annotated[tuple[Source, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    source_channels: Annotated[tuple[SourceChannel, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    targets: Annotated[tuple[Target, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    deployments: Annotated[tuple[Deployment, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    relationships: Annotated[tuple[Relationship, ...], Field(max_length=MAX_RELATIONSHIPS)]
    bindings: Annotated[tuple[Binding, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)]
    capability_profiles: Annotated[
        tuple[CapabilityProfile, ...], Field(min_length=1, max_length=MAX_ENTITIES_PER_NAMESPACE)
    ]
    digest: Sha256Digest

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        return value

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return _utc(value)


class ProfileIdentity(StrictModel):
    profile_id: Identifier
    version: Version


class ResolvedTopology(StrictModel):
    schema_version: str
    selected_at: datetime
    mode: TopologyMode
    data_cutoff: datetime
    revision_id: Identifier
    digest: Sha256Digest
    provenance: Provenance
    profile_identities: tuple[ProfileIdentity, ...]
    physical_assets: tuple[PhysicalAsset, ...]
    sources: tuple[Source, ...]
    source_channels: tuple[SourceChannel, ...]
    targets: tuple[Target, ...]
    deployments: tuple[Deployment, ...]
    relationships: tuple[Relationship, ...]
    bindings: tuple[Binding, ...]
    capability_profiles: tuple[CapabilityProfile, ...]

    @field_validator("selected_at", "data_cutoff")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ResolvedBinding(StrictModel):
    schema_version: str
    selected_at: datetime
    mode: TopologyMode
    data_cutoff: datetime
    revision_id: Identifier
    digest: Sha256Digest
    revision_provenance: Provenance
    target: Target
    binding: Binding
    source: Source
    channel: SourceChannel
    profile: CapabilityProfile

    @field_validator("selected_at", "data_cutoff")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class TopologyStatus(StrictModel):
    available: bool
    revision_id: Identifier | None = None
    digest: Sha256Digest | None = None
    error_code: Literal["TOPOLOGY_UNAVAILABLE", "TOPOLOGY_INVALID"] | None = None


class TopologyCatalog(StrictModel):
    revisions: Annotated[tuple[TopologyRevision, ...], Field(min_length=1, max_length=MAX_REVISIONS)]


def canonical_revision_bytes(revision: TopologyRevision) -> bytes:
    content = revision.model_dump(mode="python", exclude={"digest"})
    normalized = _canonical_value(content)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def compute_revision_digest(revision: TopologyRevision) -> str:
    return hashlib.sha256(canonical_revision_bytes(revision)).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        value = _utc(value)
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical content cannot contain non-finite numbers")
    return value
