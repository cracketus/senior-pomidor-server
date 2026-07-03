from app.state_estimator.derived_metrics import (
    absolute_humidity_g_m3,
    dew_point_c,
    leaf_air_delta_c,
    saturation_vapor_pressure_kpa,
    vpd_kpa,
)


def test_vpd_and_vapor_pressure_formula() -> None:
    assert round(saturation_vapor_pressure_kpa(24.0), 3) == 2.984
    assert round(vpd_kpa(24.0, 60.0), 3) == 1.194


def test_dew_point_and_absolute_humidity_sanity() -> None:
    assert round(dew_point_c(24.0, 60.0), 1) == 15.8
    assert round(absolute_humidity_g_m3(24.0, 60.0), 1) == 13.1


def test_leaf_air_delta() -> None:
    assert leaf_air_delta_c(22.5, 24.0) == -1.5
