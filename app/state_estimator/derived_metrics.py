from __future__ import annotations

import math


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def actual_vapor_pressure_kpa(air_temp_c: float, rh_pct: float) -> float:
    return saturation_vapor_pressure_kpa(air_temp_c) * (rh_pct / 100.0)


def vpd_kpa(air_temp_c: float, rh_pct: float) -> float:
    return saturation_vapor_pressure_kpa(air_temp_c) - actual_vapor_pressure_kpa(air_temp_c, rh_pct)


def leaf_vpd_kpa(leaf_temp_c: float, air_temp_c: float, rh_pct: float) -> float:
    return saturation_vapor_pressure_kpa(leaf_temp_c) - actual_vapor_pressure_kpa(air_temp_c, rh_pct)


def dew_point_c(air_temp_c: float, rh_pct: float) -> float:
    if rh_pct <= 0:
        return float("nan")
    gamma = math.log(rh_pct / 100.0) + (17.27 * air_temp_c) / (237.3 + air_temp_c)
    return (237.3 * gamma) / (17.27 - gamma)


def absolute_humidity_g_m3(air_temp_c: float, rh_pct: float) -> float:
    actual_hpa = actual_vapor_pressure_kpa(air_temp_c, rh_pct) * 10.0
    return 216.7 * actual_hpa / (air_temp_c + 273.15)


def leaf_air_delta_c(leaf_temp_c: float, air_temp_c: float) -> float:
    return leaf_temp_c - air_temp_c


def weighted_average(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _value, weight in values if weight > 0)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values if weight > 0) / total_weight
