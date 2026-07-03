from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SoilProbeCalibration:
    position: str | None = None
    air_adc: float | None = None
    water_adc: float | None = None
    dry_threshold_pct: float = 20.0
    wet_threshold_pct: float = 75.0


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str = "default"
    soil_probes: dict[str, SoilProbeCalibration] = field(default_factory=dict)


def soil_moisture_from_adc(adc_raw: float, calibration: SoilProbeCalibration) -> tuple[float | None, float | None]:
    if calibration.air_adc is None or calibration.water_adc is None or calibration.air_adc == calibration.water_adc:
        return None, None
    unclamped = 100.0 * (calibration.air_adc - adc_raw) / (calibration.air_adc - calibration.water_adc)
    return min(100.0, max(0.0, unclamped)), unclamped
