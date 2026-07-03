from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawObservation:
    node_id: str
    sensor_id: str
    sensor_type: str
    ts: datetime
    received_ts: datetime
    values: dict[str, float | bool | str | None]
    read_ok: bool = True
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EstimatorContext:
    node_id: str
    timezone: str = "Europe/Vienna"
    growth_stage: str = "fruiting"
    mode: str = "normal"
    is_outdoor: bool = True


@dataclass
class EstimatorConfig:
    timezone: str = "Europe/Vienna"
    collection_window_seconds: int = 90
    max_sensor_age_seconds: int = 120
    max_device_age_seconds: int = 120
    minimum_for_normal_control: float = 0.65
    minimum_for_any_autonomy: float = 0.40
    high_temp_warn_c: float = 30.0
    critical_heat_c: float = 32.0
    low_temp_warn_c: float = 15.0
    critical_cold_c: float = 12.0
    high_rh_pct: float = 85.0
    saturation_rh_pct: float = 98.0
    high_vpd_kpa: float = 1.6
    low_vpd_kpa: float = 0.5
    leaf_air_delta_abs_c: float = 3.0
    minimum_valid_soil_probes: int = 1


@dataclass
class EstimatorHistory:
    samples: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    ema: dict[tuple[str, str], float] = field(default_factory=dict)
    previous_values: dict[tuple[str, str], float] = field(default_factory=dict)


@dataclass(frozen=True)
class EstimatorResult:
    state: dict[str, Any]
    sensor_health: dict[str, Any]
    anomalies: list[dict[str, Any]]
    diagnostics: dict[str, Any]
