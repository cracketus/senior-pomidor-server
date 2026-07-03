import json
from pathlib import Path

from app.state_estimator.config import load_estimator_runtime
from app.state_estimator.replay import replay_observations

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def stable_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_config_loads_independent_pod_probe_metadata() -> None:
    config, calibration = load_estimator_runtime()

    assert config.minimum_valid_soil_probes == 1
    assert set(calibration.soil_probes) == {"pod_1", "pod_2"}
    assert calibration.soil_probes["pod_1"].position is None
    assert calibration.soil_probes["pod_2"].position is None
    assert calibration.soil_probes["pod_1"].dry_threshold_pct == 20.0
    assert calibration.soil_probes["pod_2"].dry_threshold_pct == 20.0


def test_replay_output_is_byte_stable_after_sorted_serialization() -> None:
    payload = load_fixture("normal_two_pods.json")

    first = replay_observations(payload, timezone="Europe/Vienna")
    second = replay_observations(payload, timezone="Europe/Vienna")

    assert stable_json(first) == stable_json(second)


def test_normal_replay_fixture_has_two_configured_pods_without_false_anomalies() -> None:
    states = replay_observations(load_fixture("normal_two_pods.json"), timezone="Europe/Vienna")

    state = states[-1]
    probes = state["soil"]["probes"]
    assert [probe["id"] for probe in probes] == ["pod_1", "pod_2"]
    assert state["refs"]["anomaly_ids"] == []
    assert state["soil"]["zone_pattern"] == "unknown"


def test_missing_one_pod_degrades_soil_confidence_without_duplicate_probes() -> None:
    state = replay_observations(load_fixture("missing_one_pod.json"), timezone="Europe/Vienna")[-1]

    probes = state["soil"]["probes"]
    assert [probe["id"] for probe in probes] == ["pod_1", "pod_2"]
    assert [probe["id"] for probe in probes].count("pod_1") == 1
    assert [probe["id"] for probe in probes].count("pod_2") == 1
    assert state["quality"]["soil_confidence"] < 1.0


def test_high_vpd_replay_fixture_triggers_after_duration() -> None:
    states = replay_observations(load_fixture("hot_high_vpd.json"), timezone="Europe/Vienna")

    assert states[0]["refs"]["anomaly_ids"] == []
    assert any("HIGH_VPD" in anomaly_id for anomaly_id in states[-1]["refs"]["anomaly_ids"])


def test_low_vpd_replay_fixture_triggers_after_duration() -> None:
    states = replay_observations(load_fixture("humid_low_vpd.json"), timezone="Europe/Vienna")

    assert states[0]["refs"]["anomaly_ids"] == []
    assert any("LOW_VPD" in anomaly_id for anomaly_id in states[-1]["refs"]["anomaly_ids"])
