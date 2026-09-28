# Review Report: #247 real Edge/Core verification

Report schema: `senior-pomidor.review-report.v1`

Reviewer/version: independent Reviewer 1.0.

Issue/brief: `.ai/implementation-briefs/ISSUE-247-cross-repo.md`; authorized six-step software implementation.

Base: `aea94fd6235f0ecc242e5d1806332715fd7b85ce`.

Verified implementation head: `c1b0f73b8be98df9e8db87c6f2ae1dbb8f2fd589`.

Tested candidate Core: PR merge commit `e94b9289eae5b48c3a7f9a526bc0d87d3a69f0d9`.

Audit: `.ai/agent-runs/20260927-issue-247-coder.json`.

Independence: separate read-only context. Brief, code and archived evidence inspected independently; no files edited.

## Verdict

`APPROVE`

Approve the bounded software implementation and its PR for human review. All previously identified implementation findings are resolved, and archived reports independently pass validation for the declared three-pair matrix. This verdict does not approve operational release qualification, production deployment or hardware activation.

## Independent classification

- Task classes: `pure_software`, `schema_data_contract`, `infrastructure_deployment`, `edge_hardware_integration`.
- Risk flags: `edge_server_compatibility`, `public_contract`; security and availability checks additionally selected by the brief.
- Operational canary, staging, restore and rollout checks remain `NOT_RUN` for their separate, explicitly deferred acceptance campaign.
- SP-FAIL-001/002: configuration, startup and consumer execution covered by successful matrix execution.
- SP-FAIL-003: internal network, no published ports, owned volumes and disabled export inspected.
- SP-FAIL-004: exact identities recorded; release validator requires matching published-image refs.
- SP-FAIL-005: restore acceptance remains separate and is not represented as CI success.
- SP-FAIL-006/017: outage, retry, restart and recovery scenarios passed.
- SP-FAIL-009/010/011: real transport, persistence, legacy fixtures, derived state and production estimator entry point exercised.
- SP-FAIL-014: Windows/Linux contract and property checks reported passing.

## Scope and architecture assessment

The implementation preserves real Edge formatter, durable spool, delivery worker, MQTT/HTTP and real Core/PostgreSQL paths. Only sensor acquisition and sample time are injected.

High-VPD assertions cover persisted metrics, canonical state and anomaly generation. A separate `run_once()` check inspects the persisted snapshot before the API can perform fallback estimation.

The fresh sample is now queued before recovery, resolving the previous controller-scheduling race. No production or physical-control responsibility was introduced.

## Findings

None.

Prior REVIEW247-01 through REVIEW247-06 are resolved.

## Contract and consumer review

Telemetry and ACK contracts remain unchanged. The versioned evidence schema rejects malformed, incomplete and mismatched reports. Source-built CI evidence is distinguished from published-image qualification.

Legacy fixtures traverse MQTT before HTTP replay. Observation identity, timestamps, counts and readback are reconciled. Future actuator invariants remain `NOT_IMPLEMENTED`.

## Test and evidence matrix

| Status | Check | Evidence and reviewer assessment |
|---|---|---|
| PASS | Archived current/current report | Independently validated expected Core/Edge SHAs; 11 scenarios |
| PASS | Archived previous-Edge report | Independently validated expected Core/Edge SHAs; 11 scenarios |
| PASS | Archived rollback-Core report | Independently validated expected Core/Edge SHAs; 11 scenarios |
| PASS | Record reconciliation | Each report: 20 generated/persisted/read back; zero missing, duplicate or unexpected |
| PASS | `git diff --check` | Reviewer execution |
| PASS | Full CI, Docker E2E, quality and security | Recorded run `36378964066`; 710 passed, 2 skipped |
| PASS | Windows/Linux property, evidence and CLI checks | Recorded run `36378964088` |
| NOT_RUN | Published-image release qualification | Requires rerun against selected release digests |
| NOT_RUN | Staging, soak, restore/rollback, canary and hardware | Separate maintainer-owned operational acceptance |

Reviewer independently executed the strict evidence validator using the existing development Python environment. All three archived reports passed.

## Operations, safety, security and privacy

The HTTP bridge operates inside the private test network with bounded requests and responses. No host ports, devices, production mounts or external exporter are introduced.

Diagnostics failure does not prevent cleanup attempts. Cleanup preserves volumes. Evidence contains bounded software results and synthetic identities; no production dataset or service logs were added to the archived report directory.

Rollback consists of reverting the tooling/CI change without database migration or deletion.

## Documentation assessment

Implementation report, audit and archived evidence distinguish:

- Tested implementation head from tested PR merge commit.
- Source-built image identity from release-image digest.
- Software verification from operational qualification.
- Completed six-step scope from residual epic backlog.

The frozen v0.3.1 candidate is not requalified or modified by this work.

## Follow-ups outside this PR

Complete the separately authorized release campaign using exact published images, staging/soak, restore/rollback and canary evidence. Remaining performance, mutation/fuzzing and other #247 backlog should stay separately tracked.

## Limitations and unverified evidence

No independent Docker execution or physical testing was performed in the reviewer environment. Runtime conclusions rely on the inspected archived CI reports and recorded CI outcomes; their strict schema, identities and reconciliation counts were independently validated. Subsequent changes are limited to evidence and documentation; runtime changes would require renewed review and verification.
