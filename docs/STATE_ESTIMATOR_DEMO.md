# Deterministic State Estimator demo

This offline runner replays registered synthetic telemetry fixtures through the production State Estimator,
sensor-health and anomaly logic, deterministic Guardrails, and advisory action simulation. It does not use the
database, network, Raspberry Pi, external models, Executor, or actuator adapters. Physical actuation and watering
remain explicitly `false`.

The normal comparison takes less than a second after Python or the application container has started. Allow about
two minutes to introduce the evidence layers and explain the hot/high-VPD timeline during a call.

## Compare the presentation scenarios

From a local checkout:

```bash
python tools/demo_state_estimator.py --compare normal_two_pods hot_high_vpd
```

From a running application image built from this revision:

```bash
docker compose exec api python tools/demo_state_estimator.py \
  --compare normal_two_pods hot_high_vpd
```

The default table separates normalized measurements, derived state, estimator interpretations, Guardrails, and the
advisory decision. Use the timeline to show that the hot scenario contains two frames and that warning anomalies
appear only when the production estimator emits them:

```bash
python tools/demo_state_estimator.py --scenario hot_high_vpd --view timeline --details
```

List all registered diagnostic scenarios:

```bash
python tools/demo_state_estimator.py --list-scenarios
```

An explicit timezone-aware evaluation clock can demonstrate freshness behavior without consulting the wall clock:

```bash
python tools/demo_state_estimator.py --scenario hot_high_vpd --at 2026-07-02T08:05:00Z
```

## Capture deterministic JSON evidence

Use `-T` when redirecting output from Compose so no pseudo-terminal control bytes enter the evidence file:

```bash
docker compose exec -T api python tools/demo_state_estimator.py \
  --compare normal_two_pods hot_high_vpd --json > state-estimator-demo.json
```

The JSON records scenario and source-fixture identity, a SHA-256 fixture digest, evaluation time, production schema
and configuration versions, every replay frame, canonical state, sensor health, anomalies, Guardrails, and advisory
action simulation. Keys, scenarios, anomalies, and reasons have deterministic ordering. Runtime-only
`diagnostics.processing_ms` is declared and omitted so repeated runs against the same revision, configuration, and
fixtures remain byte-stable.

For a prerecorded terminal fallback, capture the human-readable output before the call:

```bash
python tools/demo_state_estimator.py \
  --compare normal_two_pods hot_high_vpd --details > state-estimator-demo.txt
```

Keep the text and JSON capture with the exact Git revision used to produce them. Do not edit captured values into a
more persuasive result.

## Interpretation limits

These fixtures are sanitized synthetic examples used to demonstrate current software behavior. They prove neither
that a physical sensor produced the input nor that the system behaved correctly in real balcony, greenhouse, or
field conditions. Real operating evidence requires identified hardware, calibration, timestamps, configuration,
and independently recorded observations.

The aggregate value is an engineering state data-quality score. It is not AI confidence, model accuracy, plant
health confidence, or a probability of stress. Environmental anomalies identify observed risk conditions; they do
not prove physiological plant stress. The action result is advisory-only and never invokes Executor or hardware.

An anomaly, `CAUTION`, or `BLOCKED` result is a successful scenario evaluation and therefore does not change the
process exit code. Unknown scenarios, malformed fixtures, invalid timestamps, missing files, or a violated
advisory-only safety invariant return a non-zero exit.
