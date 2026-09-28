# Implementation Report: #91 integration/performance guardrails

Run: `20260928-issue-91`; audit: `.ai/agent-runs/20260928-issue-91.json`.
Approved scope and classification: `.ai/implementation-briefs/ISSUE-91-performance.md`.

The HTTP latest-across-devices endpoint previously loaded each device separately.
It now selects latest events using an indexed per-device scalar subquery in one query with batched relationships, preserving
active-device filtering, ordering and response shape. Query-budget tests prevent
per-device amplification. Storage fault injection checks retry without partial rows.
The existing isolated Compose E2E now includes PostgreSQL atomicity/query plans,
HTTP load, MQTT duplicate bursts and retained bounded performance evidence.
See `docs/PERFORMANCE_VERIFICATION.md` for exact commands/budgets and limitations.

Validation at initial handoff:
- PASS: focused API/query-budget/lifecycle tests, 67 passed.
- PASS: ruff lint/format and diff check.
- Full local suite: 716 passed, 2 skipped, 1 failed because Docker executable is absent.
  Docker/config/runtime evidence must come from CI; this is not a full local PASS.
- NOT_RUN: real PostgreSQL/HTTP/MQTT Docker performance phase locally (Docker absent).
- Independent review and final CI results will be recorded after execution.

No schema migration, production operations, physical action or public field additions.
Rollback is code revert. Existing frozen v0.3.1 is untouched. Edge sender throughput
is outside this Core smoke workload and is not claimed by its measurements.

## Final source review and CI evidence

Independent review APPROVE. Indexed latest lookup, fixed workload epoch and recursive telemetry plan check resolve all findings.

- https://github.com/cracketus/senior-pomidor-server/actions/runs/36438466336
- https://github.com/cracketus/senior-pomidor-server/actions/runs/36438466373

Final PR checks remain authoritative for the latest commit; no operational PASS is inferred.
