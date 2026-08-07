# Implementation Brief: Raspberry Pi camera capture and failures

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-03

## Problem

Camera capture must tolerate absence, timeout and unstable frames, but camera model/interface/cable/power facts are not supplied.

## Desired outcome

An edge camera adapter has bounded capture, startup self-test, fake-backend failure behavior and a separately verified stable physical capture procedure.

## Current behavior and evidence

`tools/pi_camera_smoke_test.py` and `docs/PI_INTEGRATION_RUNBOOK.md` are available. Ownership and runtime path in the external edge repository, camera interface and electrical/cable facts are Unknown.

## Scope

- Define adapter protocol, fake backend, bounded capture/result contract, self-test, diagnostics and manual acceptance procedure.

## Out of scope

- Selecting/buying hardware, server image analysis, actuator behavior, claiming physical success from CI.

## Architecture placement

Capture belongs to an edge hardware adapter. Server receives only the existing/new approved photo contract; LLM/VLM remains a downstream untrusted analyst.

## Affected contracts and consumers

Edge capture result/error and photo metadata may be affected. JPEG upload/API/storage consumers require explicit compatibility; power, interface and timing ranges are Unknown.

## Safety/risk classification

Classes: `edge_hardware_integration`, optionally `schema_data_contract`. Flag: `edge_server_compatibility`. Apply `SP-FAIL-008`, `SP-FAIL-011`.

## Proposed implementation sequence

1. Resolve model/interface/power/cable/edge owner and approve safe limits.
2. Define adapter/fake and capture outcome contract.
3. Add disconnected, timeout, corrupt/unstable-frame and recovery tests.
4. Add startup self-test/metrics; then run supervised physical verification.

## Failure modes

Absent device, permission/driver error, timeout, empty/corrupt JPEG, flicker, cable/power instability, restart and upload failure produce bounded errors and no false success.

## Backward compatibility

Preserve current photo schema/upload unless a new version is approved and both edge/server versions are replayed.

## Testing plan

Fake-backend unit tests plus server contract replay and baseline suite. Manual owner performs detection, repeated capture/flicker review, reboot, cable/power and recovery checks.

## Observability

Expose capture outcome, duration, bounded error category, device availability and freshness; omit device paths/private images from public output.

## Documentation updates

Update edge runbook, camera smoke instructions and contracts only after hardware is selected.

## Rollout and rollback

Canary capture with upload disabled, then bounded upload. Abort on heat/power instability, corruption or timeouts; disable adapter and restore prior edge configuration.

## Acceptance criteria

- [ ] Fake tests cover disconnected/timeout/corrupt/recovery and never require camera hardware.
- [ ] Human evidence records repeated stable frames and reboot recovery on approved hardware.

## Blocking open questions

- Camera model/interface, voltage/current source, cable length, driver, edge repository/owner and acceptable frame quality/rate?

## Evidence and references

- `tools/pi_camera_smoke_test.py`; `docs/PI_INTEGRATION_RUNBOOK.md`.
- All physical/electrical and edge implementation facts are unverified.
