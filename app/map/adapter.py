from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from app.map.models import Identifier, StrictModel, Unit, Version
from app.map.raw_evidence import ChannelMetric, ChannelSelector


class AdapterMapping(StrictModel):
    channel_id: Identifier
    source_id: Identifier
    storage_device_id: str = Field(min_length=1, max_length=128)
    pod_key: str = Field(min_length=1, max_length=64)
    metric_name: ChannelMetric
    error_sensors: tuple[str, ...] = Field(min_length=1, max_length=16)
    unit: Unit
    minimum: float
    maximum: float
    max_age_seconds: int = Field(ge=1, le=604800)

    def selector(self, binding: Any, profile_version: str) -> ChannelSelector:
        return ChannelSelector(
            source_id=self.source_id,
            storage_device_id=self.storage_device_id,
            channel_id=self.channel_id,
            pod_key=self.pod_key,
            metric_name=self.metric_name,
            error_sensors=self.error_sensors,
            unit=self.unit,
            minimum=self.minimum,
            maximum=self.maximum,
            max_age_seconds=self.max_age_seconds,
            effective_interval=binding.interval,
            profile_id=binding.profile_id,
            profile_version=profile_version,
        )


class AdapterConfig(StrictModel):
    schema_version: str
    adapter_version: Version
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mappings: tuple[AdapterMapping, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def unique(self) -> AdapterConfig:
        ids = [item.channel_id for item in self.mappings]
        if len(ids) != len(set(ids)):
            raise ValueError("adapter channel mappings must be unique")
        device_sources: dict[str, str] = {}
        for item in self.mappings:
            previous = device_sources.setdefault(item.storage_device_id, item.source_id)
            if previous != item.source_id:
                raise ValueError("one storage device cannot map to multiple sources")
        return self


class AdapterConfigError(ValueError):
    pass


def _digest(data: dict[str, Any]) -> str:
    body = {key: value for key, value in data.items() if key != "digest"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_adapter_config(path: str | Path) -> AdapterConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("digest") != _digest(raw):
            raise AdapterConfigError("adapter digest mismatch")
        config = AdapterConfig.model_validate(raw)
    except AdapterConfigError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise AdapterConfigError("adapter configuration is invalid") from exc
    if config.schema_version != "senior-pomidor.map.v1":
        raise AdapterConfigError("adapter schema version is unsupported")
    return config
