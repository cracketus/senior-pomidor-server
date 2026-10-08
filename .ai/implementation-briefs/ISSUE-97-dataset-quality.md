# Implementation Brief: #97 dataset quality and public projections

Status: approved by user 2026-09-28 for software portion of #97.
Run: 20260928-issue-97; audit .ai/agent-runs/20260928-issue-97.json.
Classes: pure_software, schema_data_contract; risks: security_secrets, public_contract.
SP-FAIL-009/010/011: consume real API stored-row shape, units and UTC semantics;
014: bounded files, explicit close. Privacy baseline: docs/PUBLIC_DATA_POLICY.md.

Implement offline bounded JSONL validation of existing telemetry read API rows:
record/observation duplicates, invalid IDs/UTC time, receive/observe skew, ordering,
optional cadence gaps, missing/nonfinite/out-of-range metrics. Preserve inputs.
Report only counts, bounded row numbers and fixed finding codes, never private values.
No DB connection/extraction/publication: actual season acceptance needs an approved snapshot.

Add adversarial public projection tests and fix discovered arbitrary-string channels
in public status (network result, readiness/service strings). Keep schema/field names;
unknown/malformed values become null/unknown/redacted following existing privacy policy.
Consumers: status page, existing Grafana projection tests, offline research tooling.
Required focused/full pytest, schema/round-trip/API stored-row tests, lint/format/types,
security/dependency audit and privacy regression tests. No production/HIL claim.
Rollback: revert code; raw records untouched, no migration. No auto-publishing.
