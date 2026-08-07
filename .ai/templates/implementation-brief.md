# Implementation Brief: <title>

Status: draft | approved

Planner/version:

Approver/date:

Issue/decision:

## Problem

What is wrong or missing, for whom, and why it matters. Separate observations from hypotheses.

## Desired outcome

Describe measurable behavior after the change, not the implementation.

## Current behavior and evidence

List inspected code/tests/docs/issues/commits/log-safe evidence. Mark supplied-but-unverified claims as assumptions and unavailable facts as `Unknown`.

## Scope

- In-scope behavior and artifacts.

## Out of scope

- Explicit non-goals and deferred work.

## Architecture placement

- Current owner and extension point.
- Responsibility boundaries preserved.
- Why this layer owns the change; future-only components are labelled as such.

## Affected contracts and consumers

- Artifact/schema/version, producer, units/ranges, timezone, optionality and compatibility.
- Edge, MQTT/HTTP/API, storage/migration, fixtures, State Estimator/Control, dashboards, export/public dataset and docs: mark each affected, unaffected with evidence, or unknown.

## Safety/risk classification

- Task classes from `TEST_MATRIX.md`:
- Risk flags:
- Applicable `SP-FAIL-*` IDs and concrete regression implications:
- Safety/production/physical boundaries and manual evidence owner:

## Proposed implementation sequence

Numbered, bounded steps ordered for compatibility, safe defaults, tests and observability before enablement.

## Failure modes

Failure, detection signal, safe behavior, test/fault injection and recovery. Include specialized workflow failures.

## Backward compatibility

Compatibility window, old fixtures/data, rollout order, mixed-version behavior and retirement/forward-fix plan.

## Testing plan

Exact focused/full automated commands plus required simulation/replay and manual/rehearsal checks. Every selected matrix requirement is `required`, `manual`, or `optional`.

## Observability

Signals, health/log/audit location, success/failure meaning, freshness/bounds and secret-safe handling.

## Documentation updates

Authoritative documents, schemas/examples/runbooks/context state and release notes to update.

## Rollout and rollback

Preconditions, shadow/canary/rehearsal stages, abort criteria, rollback steps/owner and post-rollback health/data checks. State `not applicable` only with evidence.

## Acceptance criteria

- [ ] Measurable evidence for each in-scope outcome, failure path, compatibility and documentation obligation.

## Blocking open questions

- Question, why it blocks, owner and evidence needed. If none, state `None`.

## Evidence and references

- Repository-relative inspected sources and issue/commit IDs.
- Explicitly unverified inputs/assumptions.

Approval of this brief does not itself authorize production deployment, production data/secrets access, or real hardware activation.
