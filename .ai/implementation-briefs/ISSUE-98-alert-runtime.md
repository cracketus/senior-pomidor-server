# Implementation Brief: #98 complete alert runtime coverage

Status: approved by user 2026-09-28 for issue #98 and the accepted #247 sequence.
Run: 20260928-issue-98; audit: .ai/agent-runs/20260928-issue-98.json.

Reuse existing isolated Docker E2E/Grafana provisioning and five Edge alert scenarios.
Add all non-Edge rule runtime cases, positive hold/Pending, datasource error/recovery,
empty-data baseline and bounded evidence. Production expressions and duration configs
remain unchanged; only copied test provisioning uses accelerated scheduling/holds.
A coverage test rejects provisioned rules without an explicit runtime case.

Classes: pure_software, infrastructure_deployment, schema_data_contract.
Risks: security_secrets. SP-FAIL-001/003 isolation; 009/010 units/shape;
011 real Grafana scheduler rather than SQL-only; 014 closed files/resources.
Consumers: provisioning, PostgreSQL read-only role, Grafana scheduler, CI evidence.
Required: focused/full pytest, lint/format/types, security/audit, Compose render and
Docker runtime CI; no production, HIL or real seasonal dataset required/claimed.
Acceptance: each rule fires and recovers, Pending observed before firing for a positive
hold, empty data follows configured OK policy, revoked reader permission produces
observable execution error and restoration recovers; no source provisioning mutation.
Abort on missing/unexpected rules, evaluator errors outside injected phase, timeout,
non-isolated stack or unexpected exporter. Revert tests/tooling; no runtime migration.
