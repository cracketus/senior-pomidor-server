# Implementation Brief: Raspberry Pi local status indicator

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-07

## Problem

A local indicator is requested for healthy, degraded connectivity and error states, but LED/driver, voltage, GPIO pin and active polarity are unknown.

## Desired outcome

A fake-tested edge indicator adapter renders deterministic prioritized states with a boot-safe default and separately approved physical wiring.

## Current behavior and evidence

`docs/PI_INTEGRATION_RUNBOOK.md` and `.ai/SAFETY_RULES.md` are allowed. No indicator allocation, electrical design, edge implementation or available GPIO map is evidenced.

## Scope

- State priority/arbitration, stale behavior, rate limiting, adapter/fake protocol, startup self-test, manual wiring/reboot evidence.

## Out of scope

- Selecting electrical parts without specifications, actuator/control behavior, production installation authorization.

## Architecture placement

The indicator is a read-only edge output adapter consuming bounded health state. It cannot share an actuator command path or override Guardrails.

## Affected contracts and consumers

Internal indicator-state contract is new. Health producer and edge adapter are affected; server/public contracts are unaffected unless remote indicator state is later approved.

## Safety/risk classification

Class: `edge_hardware_integration`. No physical-action actuator flag, but electrical/manual safety applies. Unknown voltage/current/pin/polarity blocks hardware work.

## Proposed implementation sequence

1. Approve LED/driver, resistor/current, voltage/ground, GPIO allocation and polarity.
2. Define priority (boot/error/degraded/healthy), stale/offline state and update rate.
3. Build fake GPIO adapter and absence/write-failure/recovery tests.
4. Run supervised physical self-test/reboot and document rollback.

## Failure modes

Boot pin glitch, GPIO unavailable/conflict, active-low inversion, write failure, stale health and rapid flapping default to a safe bounded indication without affecting ingestion.

## Backward compatibility

Feature defaults disabled; existing edge operation remains unchanged when adapter is absent/unconfigured.

## Testing plan

Fake GPIO tests cover priorities, stale, flapping/rate limit, startup default, disconnected/write failure and recovery. Manual owner verifies voltage/current, wiring, heat and reboot state.

## Observability

Private logs expose requested/rendered state and bounded adapter errors; no network identifiers or high-frequency log spam.

## Documentation updates

Update approved GPIO allocation, wiring diagram/specification, configuration and physical verification runbook.

## Rollout and rollback

Disabled-by-default canary. Abort on electrical uncertainty, pin conflict, heat or ingestion impact; power down and remove/disable adapter.

## Acceptance criteria

- [ ] Fake tests prove deterministic safe state/priorities/failure recovery without real GPIO.
- [ ] Human checklist confirms approved voltage, pin, polarity, resistor/driver and reboot behavior.

## Blocking open questions

- LED/driver type, voltage/current, resistor, GPIO pin/conflicts, active polarity, edge owner and required blink/state semantics?

## Evidence and references

- `docs/PI_INTEGRATION_RUNBOOK.md`; `.ai/SAFETY_RULES.md`.
- All electrical and GPIO facts are Unknown.
