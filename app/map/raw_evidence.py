from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.map.models import EffectiveInterval, Identifier, ProfileIdentity, Sha256Digest, StrictModel, Unit, Version

MAX_QUERY_ROWS = 100_000
MAX_QUERY_SOURCES = 50
MAX_QUERY_WINDOW = timedelta(days=7)
MAX_HEALTH_FACTS_PER_EVENT = 256


class EvidenceMode(StrEnum):
    AS_KNOWN_CORE = "AS_KNOWN_CORE"
    RECONSTRUCTED = "RECONSTRUCTED"


class ChannelMetric(StrEnum):
    ADC_RAW = "adc_raw"
    SOIL_MOISTURE_PERCENT = "soil_moisture_percent"
    SOIL_TEMPERATURE_C = "soil_temperature_c"
    AIR_TEMPERATURE_C = "air_temperature_c"
    AIR_HUMIDITY_PERCENT = "air_humidity_percent"
    AIR_PRESSURE_HPA = "air_pressure_hpa"
    AIR_ACTUAL_VAPOR_PRESSURE_KPA = "air_actual_vapor_pressure_kpa"
    AIR_SATURATION_VAPOR_PRESSURE_KPA = "air_saturation_vapor_pressure_kpa"
    AIR_VPD_KPA = "air_vpd_kpa"
    LIGHT_LUX = "light_lux"
    IR_AMBIENT_TEMP_C = "ir_ambient_temp_c"
    LEAF_TEMP_C = "leaf_temp_c"
    LEAF_SATURATION_VAPOR_PRESSURE_KPA = "leaf_saturation_vapor_pressure_kpa"
    LEAF_VPD_KPA = "leaf_vpd_kpa"


_PERCENT_METRICS = {
    ChannelMetric.SOIL_MOISTURE_PERCENT,
    ChannelMetric.AIR_HUMIDITY_PERCENT,
}
_CELSIUS_METRICS = {
    ChannelMetric.SOIL_TEMPERATURE_C,
    ChannelMetric.AIR_TEMPERATURE_C,
    ChannelMetric.IR_AMBIENT_TEMP_C,
    ChannelMetric.LEAF_TEMP_C,
}


class EvidenceKind(StrEnum):
    SOURCE_RECEIPT = "SOURCE_RECEIPT"
    CHANNEL_VALUE = "CHANNEL_VALUE"
    CHANNEL_INVALID_VALUE = "CHANNEL_INVALID_VALUE"
    EXPLICIT_ERROR = "EXPLICIT_ERROR"
    DISABLED_CHANNEL = "DISABLED_CHANNEL"


class EvidenceValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    CLOCK_INVALID = "CLOCK_INVALID"


class EvidenceFidelity(StrEnum):
    INGEST_TIME_PROXY = "INGEST_TIME_PROXY"


class EvidenceReason(StrEnum):
    DISABLED = "DISABLED"
    EXPLICIT_ERROR = "EXPLICIT_ERROR"
    NON_FINITE = "NON_FINITE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    INVALID_TYPE = "INVALID_TYPE"
    CLOCK_INVALID = "CLOCK_INVALID"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC-aware")
    return value.astimezone(UTC)


def _reject_submicrosecond(value: Any) -> Any:
    if isinstance(value, str):
        time_part = value.split("T", 1)[-1]
        fraction = time_part.split(".", 1)
        if len(fraction) == 2:
            digits = fraction[1].rstrip("Zz")
            if "+" in digits:
                digits = digits.split("+", 1)[0]
            elif "-" in digits:
                digits = digits.split("-", 1)[0]
            if len(digits) > 6:
                raise ValueError("timestamps finer than microseconds are unsupported")
    return value


class ChannelSelector(StrictModel):
    source_id: Identifier
    storage_device_id: Annotated[str, Field(min_length=1, max_length=128)]
    channel_id: Identifier
    pod_key: Annotated[str, Field(min_length=1, max_length=64)]
    metric_name: ChannelMetric
    error_sensors: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...],
        Field(min_length=1, max_length=16),
    ]
    unit: Unit
    minimum: float
    maximum: float
    max_age_seconds: Annotated[int, Field(ge=1, le=604_800)]
    effective_interval: EffectiveInterval
    profile_id: Identifier
    profile_version: Version

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def validate_bounds(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError("channel bounds must be finite numbers")
        return float(value)

    @field_validator("max_age_seconds", mode="before")
    @classmethod
    def validate_max_age_type(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("max_age_seconds must be an integer")
        return value

    @model_validator(mode="after")
    def validate_range_and_unit(self) -> Self:
        if len(self.error_sensors) != len(set(self.error_sensors)):
            raise ValueError("duplicate error sensors are forbidden")
        if self.minimum >= self.maximum:
            raise ValueError("channel minimum must be less than maximum")
        if (self.metric_name in _PERCENT_METRICS) != (self.unit == Unit.PERCENT):
            raise ValueError("percent metrics must use PERCENT and only percent metrics may use it")
        if (self.metric_name in _CELSIUS_METRICS) != (self.unit == Unit.CELSIUS):
            raise ValueError("temperature metrics must use CELSIUS and only temperature metrics may use it")
        if (self.metric_name == ChannelMetric.ADC_RAW) != (self.unit == Unit.RAW_ADC):
            raise ValueError("adc_raw must use RAW_ADC and only adc_raw may use it")
        if self.unit == Unit.PERCENT and (self.minimum != 0.0 or self.maximum != 100.0):
            raise ValueError("percent channels must declare the explicit 0..100 range")
        return self


class RawEvidenceRequest(StrictModel):
    schema_version: Literal["senior-pomidor.map.v1"] = "senior-pomidor.map.v1"
    selectors: Annotated[tuple[ChannelSelector, ...], Field(max_length=256)]
    window_start: datetime
    window_end: datetime
    mode: EvidenceMode
    data_cutoff: datetime | None = None
    receipt_cutoff: datetime | None = None
    point_query_at: datetime | None = None
    allow_empty_selectors: bool = False
    topology_revision_id: Identifier
    topology_digest: Sha256Digest

    @field_validator("window_start", "window_end", "data_cutoff", "receipt_cutoff", "point_query_at", mode="before")
    @classmethod
    def reject_submicrosecond(cls, value: Any) -> Any:
        return _reject_submicrosecond(value)

    @field_validator("window_start", "window_end", "data_cutoff", "receipt_cutoff", "point_query_at")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if not self.selectors and not self.allow_empty_selectors:
            raise ValueError("at least 1 selector is required")
        if self.window_start >= self.window_end:
            raise ValueError("window must be non-empty and half-open")
        if self.window_end - self.window_start > MAX_QUERY_WINDOW:
            raise ValueError("window exceeds 7 days")
        if self.data_cutoff is not None and self.window_end > self.data_cutoff:
            point_window = (
                self.point_query_at is not None
                and self.window_start == self.point_query_at
                and self.window_end == self.point_query_at + timedelta(microseconds=1)
                and self.data_cutoff == self.point_query_at
            )
            if not point_window:
                raise ValueError("window_end must not exceed data_cutoff")
        if self.receipt_cutoff is not None and self.data_cutoff is not None and self.receipt_cutoff > self.data_cutoff:
            raise ValueError("receipt_cutoff must not exceed data_cutoff")
        if self.point_query_at is not None and not (self.window_start <= self.point_query_at <= self.window_end):
            raise ValueError("point_query_at must be inside the query window")
        selector_keys = [
            (item.source_id, item.storage_device_id, item.channel_id, item.pod_key) for item in self.selectors
        ]
        if len(selector_keys) != len(set(selector_keys)):
            raise ValueError("duplicate channel selectors are forbidden")
        if len({item.channel_id for item in self.selectors}) != len(self.selectors):
            raise ValueError("channel_id must be globally unique in a request")
        if len({item.source_id for item in self.selectors}) > MAX_QUERY_SOURCES:
            raise ValueError("request exceeds 50 distinct sources")
        device_sources: dict[str, str] = {}
        for item in self.selectors:
            previous = device_sources.setdefault(item.storage_device_id, item.source_id)
            if previous != item.source_id:
                raise ValueError("one storage device cannot map to multiple sources in one request")
        return self


class HealthFact(StrictModel):
    path: Annotated[str, Field(min_length=1, max_length=256)]
    value: str | float | int | bool | None = None
    validity: EvidenceValidity = EvidenceValidity.VALID
    warning_level: Literal["warning", "critical"] | None = None
    detail_digest: Sha256Digest | None = None

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("health fact values must be finite")
        return value


class RawEvidenceItem(StrictModel):
    observation_at: datetime
    received_at: datetime
    event_identity: Annotated[str, Field(min_length=1, max_length=256)]
    record_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    evidence_kind: EvidenceKind
    child_identity: Annotated[str, Field(min_length=1, max_length=256)]
    source_id: Identifier
    source_schema_version: Annotated[str, Field(min_length=1, max_length=128)]
    channel_id: Identifier | None = None
    pod_key: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    metric_name: ChannelMetric | None = None
    unit: Unit | None = None
    value: float | None = None
    validity: EvidenceValidity
    reason: EvidenceReason | None = None
    sensor: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    detail_digest: Sha256Digest | None = None
    health_facts: Annotated[tuple[HealthFact, ...], Field(max_length=MAX_HEALTH_FACTS_PER_EVENT)] = ()

    @field_validator("observation_at", "received_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("value", mode="before")
    @classmethod
    def validate_finite_value(cls, value: Any) -> Any:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value)
        ):
            raise ValueError("evidence values must be finite numbers")
        return None if value is None else float(value)


class RawEvidenceBatch(StrictModel):
    schema_version: Literal["senior-pomidor.map.v1"] = "senior-pomidor.map.v1"
    mode: EvidenceMode
    window_start: datetime
    window_end: datetime
    evaluation_time: datetime
    data_cutoff: datetime
    coverage_start: datetime
    coverage_end: datetime
    topology_revision_id: Identifier
    topology_digest: Sha256Digest
    profile_identities: tuple[ProfileIdentity, ...]
    fidelity: EvidenceFidelity = EvidenceFidelity.INGEST_TIME_PROXY
    row_count: Annotated[int, Field(ge=0, le=MAX_QUERY_ROWS)]
    items: tuple[RawEvidenceItem, ...]
    digest: Sha256Digest

    @field_validator("window_start", "window_end", "evaluation_time", "data_cutoff", "coverage_start", "coverage_end")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return _utc(value)


def _decimal_text(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("canonical content cannot contain non-finite numbers")
    if value == 0:
        return "0"
    decimal = Decimal(str(value))
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _canonical_json(value: Any) -> str:
    if isinstance(value, datetime):
        return json.dumps(_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), ensure_ascii=False)
    if isinstance(value, Enum):
        return _canonical_json(value.value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _decimal_text(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{json.dumps(str(key), ensure_ascii=False)}:{_canonical_json(value[key])}" for key in sorted(value)
            )
            + "}"
        )
    if isinstance(value, tuple | list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_evidence_bytes(batch: RawEvidenceBatch) -> bytes:
    content = batch.model_dump(mode="python", exclude={"digest"})
    return _canonical_json(content).encode("utf-8")


def compute_evidence_digest(batch: RawEvidenceBatch) -> str:
    return hashlib.sha256(canonical_evidence_bytes(batch)).hexdigest()


def bounded_detail_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
