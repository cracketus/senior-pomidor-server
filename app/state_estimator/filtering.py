from __future__ import annotations

from statistics import median

from app.state_estimator.models import EstimatorHistory

ALPHA: dict[str, float] = {
    "air_temp_c": 0.30,
    "rh_pct": 0.35,
    "co2_ppm": 0.40,
    "moisture_pct": 0.20,
    "soil_temp_c": 0.20,
    "leaf_temp_c": 0.40,
    "lux": 0.50,
    "ppfd_umol_m2_s": 0.50,
}


def filter_value(
    history: EstimatorHistory,
    sensor_id: str,
    field: str,
    value: float,
) -> tuple[float, dict[str, float | str | list[str]]]:
    key = (sensor_id, field)
    samples = [*history.samples.get(key, []), value][-3:]
    history.samples[key] = samples
    median_value = float(median(samples))
    alpha = ALPHA.get(field, 0.35)
    previous = history.ema.get(key, median_value)
    filtered = alpha * median_value + (1.0 - alpha) * previous
    history.ema[key] = filtered
    return filtered, {
        "raw_value": value,
        "median_value": median_value,
        "filtered_value": filtered,
        "filter": "median3_ema",
        "alpha": alpha,
        "flags": [],
    }
