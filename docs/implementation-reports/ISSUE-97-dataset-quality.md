# Implementation Report: #97 dataset quality and public projections

Run `20260928-issue-97`; audit `.ai/agent-runs/20260928-issue-97.json`.
Brief: `.ai/implementation-briefs/ISSUE-97-dataset-quality.md`.

Added bounded offline JSONL validation of actual telemetry readback shape and a
strict report schema. Findings contain fixed codes/row numbers, never private values.
Tests pass actual ingested/stored/API data through validation, round-trip schema,
duplicates/time/order/gaps and impossible-value checks; sources remain unchanged.

Found and fixed arbitrary-string channels inside allowlisted public-status fields.
Network types/results, readiness/service strings and device labels now follow bounded
public projection rules. Existing Grafana exporter projection tests are retained.
Review found unhashable schema and huge-integer input crashes; both fixed with tests
through CLI and projection helpers. Final CI/re-review remains required.

Local targeted tests PASS; no production access, extraction or publication performed.
Real Season1 dataset acceptance is NOT_RUN pending an owner-approved snapshot under
#302. This PR deliberately does not close that manual/data acceptance by synthetic CI.
No migration. Revert code to roll back; input snapshots are read-only.
