# Implementation Report: edge reliability metrics and Grafana dashboard

Issue/brief: Human-approved implementation plan for server issue #229.

Agent run ID / audit artifact: `20260825-issue-229-coder` /
`.ai/agent-runs/20260825-issue-229-coder.json`.

Branch/worktree: `feature/TOMATO-229-edge-reliability-metrics` /
`.agent-worktrees/tomato-229-edge-reliability-metrics`.

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`;
`edge_server_compatibility`, `production_availability`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`,
`SP-FAIL-009`, `SP-FAIL-011`, `SP-FAIL-014`.

## Implemented behavior

- Added a per-cycle public edge reliability snapshot from the deterministically selected latest telemetry
  event for each registered device. Status and freshness semantics come from
  `build_operator_edge_reliability()` at the fixed 1200-second boundary.
- Added fixed one-hot overall/watchdog/spool/application/freshness state sets, bounded watchdog-state and
  disk-state sets, and optional non-negative numeric gauges. Missing values are omitted rather than zeroed.
- Preserved plant sample timestamps and cursor/checkpoint behavior while repeating current reliability state
  on every exporter cycle.
- Added the separate provisioned `Senior Pomidor Edge Reliability` dashboard with a `device_id` variable,
  latest-event lateral joins, explicit `UNKNOWN`, allowlisted state history, counters, freshness, backlog,
  storage pressure, and timelines.
- Added four provisioned Grafana alert rules for unavailable/stale telemetry, critical watchdog recovery,
  spool/disk/worker failure, and inactive application state. No contact point or notification policy changed.
- Added a sanitized synthetic SVG dashboard example using `demo-edge-01` and relative time only.

## Files changed and purpose

- `app/grafana_cloud_exporter.py`: reliability snapshot query, metric conversion, state sets, numeric allowlist,
  and exporter result accounting.
- `docker/grafana/provisioning/dashboards/json/senior-pomidor-edge-reliability.json`: separate read-only dashboard.
- `docker/grafana/provisioning/alerting/edge-reliability-alerts.yml`: four reliability alert rules.
- `tests/test_grafana_cloud_exporter.py`: conversion, privacy, protobuf, latest snapshot, replay, and cursor tests.
- `tests/test_grafana_provisioning.py`: UID/datasource/panels/SQL/alerts/sanitized-example tests.
- `docs/images/edge-reliability-dashboard-demo.svg`: sanitized synthetic documentation visual.
- `docs/CONTRACTS.md`, `docs/PUBLIC_DATA_POLICY.md`, `docs/OPERATIONS.md`, `README.md`, `CHANGELOG.md`,
  `.ai/CURRENT_STATE.md`: public contract, privacy, operator, release, and current-state documentation.
- `.ai/agent-runs/20260825-issue-229-coder.json`: bounded audit record.

## Design decisions

- Reused the #228 builder for every exported reliability/freshness status. Only normalized numeric fields and
  fixed raw state allowlists are handled in the exporter.
- Timestamped reliability samples at export time because they are current-state snapshots; plant observations
  retain their original timestamps and independent checkpoint.
- Folded any watchdog `*_failed` state into `recovery_failed`, and all other unknown strings into `unknown`,
  preventing unbounded labels.
- Kept local PostgreSQL observability independent of the public metric projection. The dashboard is private/LAN
  and read-only; the Cloud path is a smaller allowlist.

## Deviations from brief

- Runtime Compose rehearsal and live Grafana alert-transition inspection were `NOT_RUN` because the local Docker
  daemon was unavailable. The exact task-owned observability Compose configuration rendered successfully.
- The documentation visual is a sanitized synthetic SVG preview, not evidence from a running Grafana instance.

## Tests added

- Healthy, recovering, suppressed, budget-exhausted, recovery-failed, spool-degraded, application-inactive,
  stale, future-timestamp, and missing-block conversions.
- Exact metric-name and label sets, one-hot states, heartbeat/freshness ages, optional numeric handling, and
  sample/protobuf privacy exclusions.
- Latest event per device, repeated current snapshot, two-device behavior, future latest-event fail-safe, and
  unchanged plant cursor/checkpoint semantics.
- Dashboard UID/datasource/device variable/panel coverage, lateral latest SQL, fixed allowlists, explicit
  `UNKNOWN`, storage fields without backlog bytes, four alert rules, and sanitized example contents.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_grafana_cloud_exporter.py tests/test_grafana_provisioning.py -q -p no:cacheprovider` | 30 passed. |
| PASS | `python -m pytest tests/test_contract_fixtures.py tests/test_edge_integration_fixtures.py tests/test_grafana_cloud_exporter.py tests/test_grafana_provisioning.py tests/test_grafana_cloud_compose.py -q -p no:cacheprovider` | 50 passed. |
| PASS | `python -m pytest -q -p no:cacheprovider` | 444 passed, 3 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed; final reuse run covered 222 files / 116 source files. |
| PASS | `python -m tools.agent_task compose tomato-229-edge-reliability-metrics config --profile observability` | Task-owned observability configuration validated. |
| PASS | `python -m tools.ai_context_docs` | Context summaries are current. |
| PASS | `git diff --check` | No whitespace errors; only configured Windows line-ending warnings. |
| FAIL | `python -m tools.validate_change --base origin/main --task-key tomato-229-edge-reliability-metrics --explain --force full` | Focused 30, full 444/3 skipped, quality, diff, and Compose config PASS; overall failed because `validate_change` passes `audit_record=None` and cannot load the human-approved dialogue brief/evidence/approval refs. |
| NOT RUN | Isolated Compose up, synthetic seed, dashboard and alert transitions | Docker Desktop Linux engine pipe was unavailable. |
| NOT RUN | Real edge canary / physical edge checks | Requires an operator-observed candidate and edge device; no GPIO or actuator work is in scope. |

## Compatibility checks

- Existing telemetry v1/v2 fixtures, normalized edge reliability fixture, #227 evaluator, #228 operator model,
  Cloud exporter, Compose, Grafana provisioning, latest/history consumers, and full test suite pass.
- The change is additive: no HTTP API, database schema, telemetry schema, plant metric name/timestamp, cursor,
  or checkpoint changes. Edge producers require no rollout change.

## Safety impact

- No production access/write, deployment, migration, destructive database/volume operation, external remote
  write, GPIO/actuator use, or Guardrails/Executor change occurred.
- Public labels are limited to sanitized `device_id` and fixed status/state enums. Reasons/results/errors, boot
  IDs, service names, PIDs, network identifiers, paths, and raw JSON are excluded and regression-tested.
- Rollback is the previous application image plus removal/reversion of the new dashboard and alert provisioning
  files. PostgreSQL data, platform Grafana state, and edge devices require no transformation.

## Known limitations

- Live Grafana layout and alert transitions remain pending operator rehearsal because Docker was unavailable.
- The synthetic SVG is documentation-only and cannot prove Grafana rendering or datasource behavior.
- Canonical validation remains overall `FAIL` because the current maturity integration hard-codes no audit
  record and cannot load the task's human-approved dialogue brief/evidence references; all selected executable
  checks passed.
- Alert notification/contact-point setup remains owned by #47.

## Documentation changes

- `docs/CONTRACTS.md` defines exact public metric names, labels, state enums, freshness, snapshot, and omission
  semantics.
- `docs/PUBLIC_DATA_POLICY.md` replaces a blanket health-data boundary with the explicit reliability allowlist.
- `docs/OPERATIONS.md` documents the dashboard, rules, missing-device alert behavior, and sanitized example.

## Manual verification steps

- `NOT RUN`: in the isolated task project with external export disabled, start the observability profile; ingest
  synthetic healthy, recovering, suppressed, and spool-degraded telemetry for `demo-edge-01`; verify dashboard
  state/freshness/timelines and the four alert transitions; stop with the same task wrapper. Abort if any target
  is non-loopback, Cloud export is enabled, missing data appears healthy, or a private string appears.
- `NOT RUN`: operator edge canary against an approved deployed candidate. CI cannot prove real process/systemd,
  disk, radio, or physical-world behavior.

## Final diff review

- Unrelated changes were absent. The diff was reviewed for secret/private-field leakage, arbitrary labels,
  unsafe SQL state strings, missing-device no-data masking, plant cursor drift, external export, migrations,
  debug artifacts, and rollback gaps.
