from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.state_estimator.replay import evaluate_replay
from tools import demo_state_estimator as demo

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_payload(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_public_evaluation_helper_returns_complete_advisory_result() -> None:
    evaluations = evaluate_replay(
        fixture_payload("normal_two_pods"),
        timezone="Europe/Vienna",
        config_path=str(demo.CONFIG_PATH),
    )

    evaluation = evaluations[-1]
    assert evaluation.result.state["schema_version"] == "state_v1"
    assert evaluation.result.sensor_health["schema_version"] == "sensor_health_v1"
    assert evaluation.result.anomalies == []
    assert evaluation.result.diagnostics["schema_version"] == "estimator_diagnostics_v1"
    assert evaluation.guardrails["schema_version"] == "guardrails_v1"
    assert evaluation.action_simulation["schema_version"] == "action_simulation_v1"
    assert evaluation.action_simulation["actuation"] == {
        "physical_actuation": False,
        "watering_proposed": False,
    }


def test_normal_and_hot_scenarios_use_current_production_results() -> None:
    normal = demo.load_scenario(demo.SCENARIOS["normal_two_pods"])
    hot = demo.load_scenario(demo.SCENARIOS["hot_high_vpd"])

    normal_final = normal.evaluations[-1]
    hot_final = hot.evaluations[-1]
    assert normal_final.result.state["env"]["vpd_kpa"] == 1.194
    assert normal_final.result.state["soil"]["avg_moisture_pct"] == 42.5
    assert normal_final.result.anomalies == []
    assert normal_final.action_simulation["decision"] == "NO_ACTION"
    assert {item["type"] for item in hot_final.result.anomalies} == {"HIGH_TEMP", "HIGH_VPD"}
    assert hot_final.action_simulation["decision"] == "WOULD_INCREASE_SAMPLING"
    assert hot_final.action_simulation["sampling_recommendation"]["recommended_poll_seconds"] == 120


def test_human_comparison_is_stable_and_distinguishes_evidence_layers() -> None:
    scenarios = [demo.SCENARIOS["normal_two_pods"], demo.SCENARIOS["hot_high_vpd"]]
    first = demo.render_table([demo.load_scenario(item) for item in scenarios])
    second = demo.render_table([demo.load_scenario(item) for item in scenarios])

    assert first == second
    assert "NORMALIZED MEASUREMENTS" in first
    assert "DERIVED STATE" in first
    assert "ESTIMATOR INTERPRETATION" in first
    assert "GUARDRAILS / ADVISORY" in first
    assert "State data-quality score" in first
    assert "1.194 kPa" in first
    assert "2.920 kPa" in first
    assert "HIGH_TEMP [WARN], HIGH_VPD [WARN]" in first
    assert "WOULD_INCREASE_SAMPLING" in first
    assert "Physical actuation" in first
    assert "do not prove physiological plant stress" in first


def test_json_output_is_byte_stable_and_omits_runtime_timing() -> None:
    scenarios = [demo.SCENARIOS["normal_two_pods"], demo.SCENARIOS["hot_high_vpd"]]
    first = demo.render_json([demo.load_scenario(item) for item in scenarios], clock_source="fixture")
    second = demo.render_json([demo.load_scenario(item) for item in scenarios], clock_source="fixture")

    assert first.encode() == second.encode()
    payload = json.loads(first)
    assert payload["schema_version"] == "state_estimator_demo_v1"
    assert payload["estimator_versions"] == ["0.1.0"]
    assert payload["config_versions"] == ["state_estimator_config_v1"]
    assert [item["scenario_id"] for item in payload["scenarios"]] == ["normal_two_pods", "hot_high_vpd"]
    for scenario in payload["scenarios"]:
        assert len(scenario["source_sha256"]) == 64
        for frame in scenario["frames"]:
            assert "processing_ms" not in frame["diagnostics"]
            assert frame["action_simulation"]["actuation"]["physical_actuation"] is False


def test_fixture_and_explicit_clocks_control_decision_timestamps() -> None:
    fixture_clock = demo.load_scenario(demo.SCENARIOS["hot_high_vpd"]).evaluations[-1]

    assert fixture_clock.guardrails["generated_ts"] == "2026-07-02T08:01:00Z"
    assert fixture_clock.action_simulation["generated_ts"] == "2026-07-02T08:01:00Z"
    assert fixture_clock.action_simulation["sampling_recommendation"]["until_ts"] == "2026-07-02T08:31:00Z"

    at = datetime(2026, 7, 2, 8, 5, tzinfo=UTC)
    explicit_clock = demo.load_scenario(demo.SCENARIOS["hot_high_vpd"], evaluation_at=at).evaluations[-1]
    assert explicit_clock.guardrails["generated_ts"] == "2026-07-02T08:05:00Z"
    assert explicit_clock.action_simulation["generated_ts"] == "2026-07-02T08:05:00Z"
    assert explicit_clock.action_simulation["sampling_recommendation"]["until_ts"] == "2026-07-02T08:35:00Z"


@pytest.mark.parametrize(
    "scenario_id",
    ["missing_one_pod", "stale_required_telemetry", "impossible_soil_jump"],
)
def test_registered_diagnostic_scenarios_are_supported(scenario_id: str) -> None:
    run = demo.load_scenario(demo.SCENARIOS[scenario_id])

    assert run.evaluations
    assert run.evaluations[-1].action_simulation["actuation"]["physical_actuation"] is False


def test_malformed_fixture_fails_cleanly_without_traceback(tmp_path: Path, monkeypatch, capsys) -> None:
    fixture = tmp_path / "malformed.json"
    fixture.write_text("{broken", encoding="utf-8")
    scenario = demo.Scenario("malformed", "MALFORMED", fixture.name, 99)
    monkeypatch.setattr(demo, "FIXTURE_DIRECTORY", tmp_path)
    monkeypatch.setitem(demo.SCENARIOS, scenario.scenario_id, scenario)

    result = demo.main(["--scenario", "malformed"])

    captured = capsys.readouterr()
    assert result == 2
    assert "not valid UTF-8 JSON" in captured.err
    assert "Traceback" not in captured.err


def test_unknown_scenario_is_rejected_with_nonzero_exit(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        demo.main(["--scenario", "does_not_exist"])

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_offline_runner_does_not_open_network_or_database_connections(monkeypatch, capsys) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline demo attempted external I/O")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Session, "execute", forbidden)

    assert demo.main(["--scenario", "normal_two_pods", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "offline_advisory_only"


def test_scenario_order_is_deterministic_and_baseline_first() -> None:
    args = demo.build_parser().parse_args(["--compare", "hot_high_vpd", "normal_two_pods"])

    assert [item.scenario_id for item in demo._selected_scenarios(args)] == [
        "normal_two_pods",
        "hot_high_vpd",
    ]


def test_runtime_image_packages_runner_and_registered_fixtures() -> None:
    dockerfile = (demo.REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY tools/__init__.py tools/demo_state_estimator.py ./tools/" in dockerfile
    assert "COPY tests/state_estimator/fixtures ./tests/state_estimator/fixtures" in dockerfile
    for scenario in demo.SCENARIOS.values():
        assert scenario.fixture_path.is_file()
