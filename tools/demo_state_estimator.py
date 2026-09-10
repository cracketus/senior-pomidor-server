from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.state_estimator.decisions import format_ts
from app.state_estimator.replay import ReplayEvaluation, evaluate_replay

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "tests" / "state_estimator" / "fixtures"
CONFIG_PATH = REPOSITORY_ROOT / "config" / "state_estimator_v1.yaml"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    fixture_name: str
    presentation_order: int

    @property
    def fixture_path(self) -> Path:
        return FIXTURE_DIRECTORY / self.fixture_name


@dataclass(frozen=True)
class ScenarioRun:
    scenario: Scenario
    source_sha256: str
    evaluations: tuple[ReplayEvaluation, ...]


SCENARIOS = {
    item.scenario_id: item
    for item in (
        Scenario("normal_two_pods", "NORMAL", "normal_two_pods.json", 0),
        Scenario("hot_high_vpd", "HOT / DRY AIR", "hot_high_vpd.json", 1),
        Scenario("missing_one_pod", "MISSING SOIL PROBE", "missing_one_pod.json", 2),
        Scenario(
            "stale_required_telemetry",
            "STALE / UNAVAILABLE INPUT",
            "stale_required_telemetry.json",
            3,
        ),
        Scenario("impossible_soil_jump", "IMPOSSIBLE SOIL JUMP", "impossible_soil_jump.json", 4),
    )
}


class DemoError(RuntimeError):
    pass


def parse_evaluation_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("must include a UTC offset or Z suffix")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay synthetic fixtures through the production State Estimator and advisory decisions."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE", "SCENARIO"),
        choices=sorted(SCENARIOS),
        help="compare exactly two registered scenarios",
    )
    selection.add_argument("--scenario", choices=sorted(SCENARIOS), help="evaluate one registered scenario")
    selection.add_argument("--list-scenarios", action="store_true", help="list registered synthetic scenarios")
    parser.add_argument("--json", action="store_true", help="emit deterministic machine-readable evidence")
    parser.add_argument(
        "--view",
        choices=("table", "timeline"),
        default="table",
        help="human-readable layout (default: table)",
    )
    parser.add_argument("--details", action="store_true", help="show guardrail and action reasons")
    parser.add_argument(
        "--at",
        type=parse_evaluation_time,
        metavar="TIMESTAMP",
        help="use an explicit timezone-aware evaluation time instead of fixture timestamps",
    )
    return parser


def load_scenario(scenario: Scenario, *, evaluation_at: datetime | None = None) -> ScenarioRun:
    try:
        raw = scenario.fixture_path.read_bytes()
    except OSError as exc:
        raise DemoError(f"cannot read fixture for {scenario.scenario_id}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemoError(f"fixture for {scenario.scenario_id} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise DemoError(f"fixture for {scenario.scenario_id} must contain a JSON object")
    try:
        evaluations = evaluate_replay(
            payload,
            timezone="Europe/Vienna",
            config_path=str(CONFIG_PATH),
            evaluation_at=evaluation_at,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DemoError(f"fixture for {scenario.scenario_id} cannot be evaluated: {exc}") from exc
    if not evaluations:
        raise DemoError(f"fixture for {scenario.scenario_id} produced no estimator frames")
    for evaluation in evaluations:
        actuation = evaluation.action_simulation.get("actuation", {})
        if actuation.get("physical_actuation") is not False or actuation.get("watering_proposed") is not False:
            raise DemoError(f"safety invariant failed for {scenario.scenario_id}: advisory output proposed actuation")
    return ScenarioRun(
        scenario=scenario,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        evaluations=tuple(evaluations),
    )


def build_evidence(runs: list[ScenarioRun], *, clock_source: str) -> dict[str, Any]:
    estimator_versions = sorted(
        {
            str(run.evaluations[-1].result.diagnostics.get("estimator_version"))
            for run in runs
            if run.evaluations[-1].result.diagnostics.get("estimator_version") is not None
        }
    )
    config_versions = sorted(
        {
            str(run.evaluations[-1].result.diagnostics.get("config_version"))
            for run in runs
            if run.evaluations[-1].result.diagnostics.get("config_version") is not None
        }
    )
    return {
        "schema_version": "state_estimator_demo_v1",
        "mode": "offline_advisory_only",
        "clock_source": clock_source,
        "estimator_versions": estimator_versions,
        "config_versions": config_versions,
        "volatile_fields_omitted": ["scenarios[].frames[].diagnostics.processing_ms"],
        "scenarios": [_scenario_evidence(run) for run in runs],
    }


def _scenario_evidence(run: ScenarioRun) -> dict[str, Any]:
    return {
        "scenario_id": run.scenario.scenario_id,
        "title": run.scenario.title,
        "source_fixture": run.scenario.fixture_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "source_sha256": run.source_sha256,
        "frames": [_frame_evidence(evaluation) for evaluation in run.evaluations],
    }


def _frame_evidence(evaluation: ReplayEvaluation) -> dict[str, Any]:
    diagnostics = {key: value for key, value in evaluation.result.diagnostics.items() if key != "processing_ms"}
    return {
        "evaluation_ts": format_ts(evaluation.evaluation_ts),
        "state": evaluation.result.state,
        "sensor_health": evaluation.result.sensor_health,
        "anomalies": evaluation.result.anomalies,
        "diagnostics": diagnostics,
        "guardrails": evaluation.guardrails,
        "action_simulation": evaluation.action_simulation,
    }


def render_json(runs: list[ScenarioRun], *, clock_source: str) -> str:
    return json.dumps(
        build_evidence(runs, clock_source=clock_source),
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )


def render_table(runs: list[ScenarioRun], *, details: bool = False) -> str:
    finals = [run.evaluations[-1] for run in runs]
    headers = [run.scenario.title for run in runs]
    rows: list[tuple[str, list[str]] | str] = [
        "SOURCE",
        ("Scenario", [run.scenario.scenario_id for run in runs]),
        ("Source fixture", [run.scenario.fixture_name for run in runs]),
        ("Frames evaluated", [str(len(run.evaluations)) for run in runs]),
        ("Evaluation time", [format_ts(item.evaluation_ts) for item in finals]),
        "NORMALIZED MEASUREMENTS",
        ("Air temperature", [_temperature(item) for item in finals]),
        ("Relative humidity", [_humidity(item) for item in finals]),
        ("Soil moisture probes", [_soil_probes(item) for item in finals]),
        "DERIVED STATE",
        ("Air VPD", [_vpd(item) for item in finals]),
        ("Soil moisture average", [_soil_average(item) for item in finals]),
        "ESTIMATOR INTERPRETATION",
        ("State data-quality score", [_data_quality(item) for item in finals]),
        ("Sensor health", [str(item.result.sensor_health.get("overall_status")) for item in finals]),
        ("Environmental anomalies", [_anomalies(item) for item in finals]),
        "GUARDRAILS / ADVISORY",
        ("Guardrail", [_guardrail(item) for item in finals]),
        ("Recommendation", [str(item.action_simulation.get("decision")) for item in finals]),
        ("Recommended sampling", [_sampling(item) for item in finals]),
        ("Physical actuation", [_physical_actuation(item) for item in finals]),
    ]
    field_width = max(len("FIELD"), *(len(row[0]) for row in rows if not isinstance(row, str)))
    column_widths = [
        max(len(header), *(len(row[1][index]) for row in rows if not isinstance(row, str)))
        for index, header in enumerate(headers)
    ]
    lines = _heading(finals)
    lines.append("")
    lines.append(_table_line("FIELD", headers, field_width, column_widths))
    lines.append(_table_line("-" * field_width, ["-" * width for width in column_widths], field_width, column_widths))
    for row in rows:
        if isinstance(row, str):
            lines.extend(("", row))
        else:
            lines.append(_table_line(row[0], row[1], field_width, column_widths))
    if details:
        lines.extend(("", "DETAILS"))
        for run, evaluation in zip(runs, finals, strict=True):
            lines.append(f"{run.scenario.scenario_id}:")
            lines.append(f"  blocking reasons: {_reason_list(evaluation.guardrails.get('blocking_reasons'))}")
            lines.append(f"  caution reasons:  {_reason_list(evaluation.guardrails.get('caution_reasons'))}")
            lines.append(f"  action reasons:   {_reason_list(evaluation.action_simulation.get('reasons'))}")
    lines.extend(("", _limitation()))
    return "\n".join(lines)


def render_timeline(runs: list[ScenarioRun], *, details: bool = False) -> str:
    finals = [run.evaluations[-1] for run in runs]
    lines = _heading(finals)
    for run in runs:
        lines.extend(
            (
                "",
                f"SCENARIO: {run.scenario.title} ({run.scenario.scenario_id})",
                f"Source:   {run.scenario.fixture_path.relative_to(REPOSITORY_ROOT).as_posix()}",
            )
        )
        for index, evaluation in enumerate(run.evaluations, start=1):
            lines.extend(
                (
                    "",
                    f"Frame {index}/{len(run.evaluations)}  {format_ts(evaluation.evaluation_ts)}",
                    f"  normalized    temperature={_temperature(evaluation)}, "
                    f"RH={_humidity(evaluation)}, soil={_soil_probes(evaluation)}",
                    f"  derived       air VPD={_vpd(evaluation)}, soil average={_soil_average(evaluation)}",
                    f"  interpretation anomalies={_anomalies(evaluation)}, data quality={_data_quality(evaluation)}",
                    f"  guardrails    {_guardrail(evaluation)}",
                    f"  advisory      {evaluation.action_simulation.get('decision')}, "
                    f"sampling={_sampling(evaluation)}, actuation={_physical_actuation(evaluation)}",
                )
            )
            if details:
                lines.append(f"  caution       {_reason_list(evaluation.guardrails.get('caution_reasons'))}")
                lines.append(f"  action reasons {_reason_list(evaluation.action_simulation.get('reasons'))}")
    lines.extend(("", _limitation()))
    return "\n".join(lines)


def _heading(finals: list[ReplayEvaluation]) -> list[str]:
    estimator_versions = sorted({str(item.result.diagnostics.get("estimator_version")) for item in finals})
    config_versions = sorted({str(item.result.diagnostics.get("config_version")) for item in finals})
    return [
        "Senior Pomidor - deterministic State Estimator replay",
        f"Estimator: {', '.join(estimator_versions)}    Config: {', '.join(config_versions)}",
        "Mode: OFFLINE / ADVISORY ONLY",
    ]


def _table_line(label: str, values: list[str], field_width: int, column_widths: list[int]) -> str:
    cells = [label.ljust(field_width)]
    cells.extend(value.ljust(column_widths[index]) for index, value in enumerate(values))
    return "  ".join(cells).rstrip()


def _state(evaluation: ReplayEvaluation) -> dict[str, Any]:
    return evaluation.result.state


def _temperature(evaluation: ReplayEvaluation) -> str:
    return _number_with_unit(_state(evaluation).get("env", {}).get("air_temp_c"), "C", 1)


def _humidity(evaluation: ReplayEvaluation) -> str:
    return _number_with_unit(_state(evaluation).get("env", {}).get("rh_pct"), "%", 1)


def _vpd(evaluation: ReplayEvaluation) -> str:
    return _number_with_unit(_state(evaluation).get("env", {}).get("vpd_kpa"), "kPa", 3)


def _soil_average(evaluation: ReplayEvaluation) -> str:
    return _number_with_unit(_state(evaluation).get("soil", {}).get("avg_moisture_pct"), "%", 1)


def _soil_probes(evaluation: ReplayEvaluation) -> str:
    probes = _state(evaluation).get("soil", {}).get("probes", [])
    values = [_number_with_unit(probe.get("moisture_pct"), "%", 1) for probe in probes if isinstance(probe, dict)]
    return ", ".join(values) if values else "unavailable"


def _data_quality(evaluation: ReplayEvaluation) -> str:
    quality = _state(evaluation).get("quality", {})
    value = quality.get("state_confidence")
    score = f"{float(value):.3f}" if isinstance(value, int | float) and not isinstance(value, bool) else "unavailable"
    return f"{quality.get('level', 'UNKNOWN')} / {score}"


def _anomalies(evaluation: ReplayEvaluation) -> str:
    anomalies = [
        f"{item.get('type')} [{item.get('severity')}]" for item in evaluation.result.anomalies if isinstance(item, dict)
    ]
    return ", ".join(anomalies) if anomalies else "none"


def _guardrail(evaluation: ReplayEvaluation) -> str:
    allowed = "allowed" if evaluation.guardrails.get("allowed") else "blocked"
    return f"{evaluation.guardrails.get('level')} / {allowed}"


def _sampling(evaluation: ReplayEvaluation) -> str:
    value = evaluation.action_simulation.get("sampling_recommendation", {}).get("recommended_poll_seconds")
    return f"{value} s" if isinstance(value, int) and not isinstance(value, bool) else "unavailable"


def _physical_actuation(evaluation: ReplayEvaluation) -> str:
    value = evaluation.action_simulation.get("actuation", {}).get("physical_actuation")
    return str(value).lower() if isinstance(value, bool) else "unavailable"


def _number_with_unit(value: Any, unit: str, digits: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unavailable"
    return f"{float(value):.{digits}f} {unit}"


def _reason_list(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(sorted(str(item) for item in value))


def _limitation() -> str:
    return (
        "Limit: environmental anomalies indicate observed risk conditions; "
        "they do not prove physiological plant stress."
    )


def _selected_scenarios(args: argparse.Namespace) -> list[Scenario]:
    names = args.compare if args.compare is not None else [args.scenario]
    selected = [SCENARIOS[name] for name in names]
    return sorted(selected, key=lambda item: (item.presentation_order, item.scenario_id))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_scenarios:
        for scenario in sorted(SCENARIOS.values(), key=lambda item: (item.presentation_order, item.scenario_id)):
            print(f"{scenario.scenario_id:28} {scenario.title} ({scenario.fixture_name})")
        return 0
    scenarios = _selected_scenarios(args)
    try:
        runs = [load_scenario(scenario, evaluation_at=args.at) for scenario in scenarios]
        if args.json:
            output = render_json(runs, clock_source="explicit" if args.at is not None else "fixture")
        elif args.view == "timeline":
            output = render_timeline(runs, details=args.details)
        else:
            output = render_table(runs, details=args.details)
    except DemoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
