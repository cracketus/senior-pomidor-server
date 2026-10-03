# Implementation Brief: #91 integration/performance guardrails

Status: approved via user instruction 2026-09-28; scope: issue #91 and accepted sequence.
Run: 20260928-issue-91; audit: .ai/agent-runs/20260928-issue-91.json.

## Scope and ownership
Reuse disposable Docker E2E (Compose instead of an additional Testcontainers stack).
Add real PostgreSQL rollback/partial-write and plan assertions, bounded HTTP/MQTT
load smoke, endpoint query-count budgets and sanitized performance evidence.
Fix confirmed query amplification at the API query owner, preserving response shape.
No production access, schema migrations, new control behavior or Edge modifications.

## Classification and checks
pure_software, infrastructure_deployment; security_secrets for test isolation.
SP-FAIL-001/003: explicit synthetic Compose config; 009/011: real API/readback;
014: resources closed before cleanup. Consumers: existing HTTP clients/CLI/TUI,
PostgreSQL ORM and CI artifacts. Telemetry wire and public contracts unchanged.
Required: focused/full pytest, ruff lint/format, mypy, bandit/dependency audit,
existing Docker E2E on CI and rendered isolated overlays; count/hash reconciliation.
No production/HIL evidence claimed. Manual release campaign remains NOT_RUN.

## Acceptance and rollback
Query counts do not grow with device count; seeded PostgreSQL selective reads use
an index; injected storage failure leaves no device/event/reading/error partials
and retry succeeds; bounded load preserves all identities and timestamps.
Report sample count/latency/throughput, broad smoke budgets, revision and limits.
No claim of production capacity or statistical benchmark from shared CI runners.
Revert this PR; no durable migration or deployment required.
