# Implementation Brief: Agent audit evidence and maturity gates

Status: approved

Planner/version: human-approved execution plan supplied in task

Approver/date: user / 2026-08-10

Issue/decision: TOMATO-AI-13 / #133 and TOMATO-AI-14 / #134

## Problem

Agent work currently has bounded local usage records but no versioned public audit artifact or
machine-enforced maturity policy.

## Desired outcome

Sanitized `agent_run_v1` records validate strictly, aggregate deterministically, and maturity gates
return `PASS`, `FAIL`, or `NOT_RUN` without authorizing merge, deployment, or physical enablement.

## Scope

- Add audit validator/metrics, two synthetic records, schema, retrospective-compatible output, and policy gate.
- Integrate the gate into validation when audit/maturity artifacts are part of the change.
- Document handoff identifiers and human-only boundaries.

## Out of scope

- Runtime API, database, Compose, GPIO, production deployment, external export, and migration changes.

## Safety/risk classification

- Task classes: `pure_software`.
- Risk flags: `security_secrets` applies to redaction and privacy review.
- Applicable failures: SP-FAIL-014, SP-FAIL-015, SP-FAIL-016.
- Manual privacy review remains human-owned and `NOT_RUN` here.

## Rollout and rollback

Local tooling and committed synthetic artifacts only. Roll back by removing the new tooling/policy
and preserving existing `agent_usage` records; no durable application data is touched.

## Testing plan

- Focused audit, maturity, and validation tests; full pytest; nox quality; diff check.
- Manual privacy review and human approval: `NOT_RUN` until independently performed.

## Acceptance criteria

- [x] Strict unknown-field and redaction validation with deterministic aggregate metrics.
- [x] Machine-readable levels, required evidence, approvals, downgrade conditions, and fail-closed gate.
- [x] Existing usage schema remains unchanged.
- [x] No production, Compose, hardware, or external-export path is invoked.
