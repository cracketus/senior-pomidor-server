from __future__ import annotations

HARD_RANGES: dict[str, tuple[float, float]] = {
    "air_temp_c": (-20.0, 60.0),
    "rh_pct": (0.0, 100.0),
    "co2_ppm": (0.0, 5000.0),
    "soil_temp_c": (-10.0, 50.0),
    "moisture_pct": (0.0, 100.0),
    "leaf_temp_c": (-20.0, 70.0),
    "lux": (0.0, 150000.0),
    "ppfd_umol_m2_s": (0.0, 2500.0),
}

JUMP_LIMITS: dict[str, float] = {
    "air_temp_c": 5.0,
    "rh_pct": 20.0,
    "soil_temp_c": 1.0,
    "moisture_pct": 15.0,
    "co2_ppm": 700.0,
    "leaf_temp_c": 5.0,
}


def validate_hard_range(field: str, value: float | None) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    limits = HARD_RANGES.get(field)
    if limits is None:
        return value, None
    low, high = limits
    if value < low or value > high:
        return None, "out_of_range"
    return value, None
