# Implementation Brief: New soil sensor adapter

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-09

## Problem

A new soil sensor is requested without model, bus/address, voltage, calibration curve or failure sentinel, so safe electrical and semantic integration cannot yet be planned fully.

## Desired outcome

An approved edge adapter converts raw readings into explicit versioned units with calibration identity, fake-bus failure coverage and manual electrical/calibration evidence.

## Current behavior and evidence

`docs/CONTRACTS.md` and the State Estimator specification describe server/canonical expectations. Edge hardware allocation and selected sensor facts are Unknown.

## Scope

- Electrical/interface decision, pin/address allocation, adapter/fake, calibration/versioning, disconnected/noisy/stuck behavior, server compatibility and physical checklist.

## Out of scope

- Guessing voltage/address/calibration, Control thresholds/actions, unrelated sensor refactoring.

## Architecture placement

Edge hardware adapter owns bus I/O/raw sentinel handling. State Estimator owns canonical units, plausibility, confidence and anomaly detection; Control cannot read raw sensor values directly.

## Affected contracts and consumers

Existing telemetry may be reused only if semantics/units/ranges match exactly; otherwise add a version. Edge, MQTT/HTTP, storage, estimator, fixtures, dashboard/export/public data must be classified.

## Safety/risk classification

Classes: `edge_hardware_integration`, `schema_data_contract`. Flag: `edge_server_compatibility`. Apply `SP-FAIL-007`, `SP-FAIL-010`, `SP-FAIL-011` and disconnected-device rules.

## Proposed implementation sequence

1. Approve model/datasheet, voltage/current/ground/level shifting, I2C or other bus address/pins and calibration method.
2. Define raw-to-unit conversion, calibration profile/version and failure sentinel.
3. Build fake I2C/bus adapter and startup self-test/failure tests.
4. Add server fixture replay, then supervised physical calibration/canary.

## Failure modes

Disconnected device, address conflict, bus timeout, stuck/noisy/out-of-range value, calibration missing/mismatch, restart and heat/power instability lower confidence/fail safe rather than fabricate moisture.

## Backward compatibility

Server tolerant support precedes edge emission. Existing sensor fields retain exact meaning; new optional/versioned fields do not break old edge nodes.

## Testing plan

Fake bus tests for absent/timeout/sentinel/stuck/noise/range/recovery; conversion boundaries and old/new fixture replay. Manual owner verifies wiring, voltage, address scan, reference calibration, reboot and thermal stability.

## Observability

Expose sensor/calibration version, health/confidence, bounded error and freshness; no raw private infrastructure data publicly.

## Documentation updates

Record datasheet decision, safe wiring/address allocation, calibration procedure, contract/schema and troubleshooting.

## Rollout and rollback

Fake -> bench read-only -> one-node shadow comparison -> canary. Abort on electrical uncertainty or implausible drift; disconnect/disable new adapter and retain old sensor path.

## Acceptance criteria

- [ ] Fake and fixture tests cover absence, I2C/bus timeout, sentinel, noise, range, calibration and recovery.
- [ ] Human evidence confirms approved electrical allocation and reference calibration without enabling actions.

## Blocking open questions

- Model/datasheet, voltage/current, interface/address/pins, calibration reference/curve, sentinel, sampling cadence and edge owner?

## Evidence and references

- `docs/CONTRACTS.md`; `docs/state_estimator_spec_v_1_0_en.md`.
- Hardware and calibration facts are Unknown.
