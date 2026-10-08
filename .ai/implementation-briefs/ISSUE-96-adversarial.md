# Implementation Brief: #96 bounded mutation and API fuzzing

Status: approved by user 2026-09-28, accepted issue #96.
Run: 20260928-issue-96; audit .ai/agent-runs/20260928-issue-96.json.
Classes pure_software, schema_data_contract, infrastructure_deployment; risk security_secrets.
SP-FAIL-009/010/011: execute actual validation/estimator and HTTP routes, preserve units;
014: temporary checkout cleanup after process exit. No production or hardware access.

Add deterministic OpenAPI-guided bounded GET/query and telemetry-body fuzzing using
existing Hypothesis, local TestClient/SQLite and schema validation of successful responses.
Add a bounded mutation runner for explicit high-value validation/parsing/confidence/range
functions in a tracked-file temporary copy. Baseline must pass; survivors/timeouts/errors
remain distinct, actionable and non-PASS. Nightly/manual heavy job; short fuzz suite in PR.
No additional runtime dependency, runtime contract change or external HTTP target.

Required checks: focused/full pytest, lint/format/types, security/audit, schema validation,
real TestClient consumer execution, baseline plus actual mutation run. Reports must include
revision, mutation location/operator and bounded outcome; no private payloads or environment.
Rollback: revert tooling/tests/workflow. Existing scenario and property tests stay intact.
