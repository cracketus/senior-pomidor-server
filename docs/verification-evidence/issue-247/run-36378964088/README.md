# Actual cross-repository CI evidence — #247

Source: [workflow run 36378964088](https://github.com/cracketus/senior-pomidor-server/actions/runs/36378964088).
Harness head: `c1b0f73b8be98df9e8db87c6f2ae1dbb8f2fd589`.
Candidate Core: PR merge commit `e94b9289eae5b48c3a7f9a526bc0d87d3a69f0d9`.
These JSON files are copied unchanged from the completed Actions artifacts, not generated fixtures.

| Pair/report | Scenarios | Final generated / persisted / read back | Duplicate / missing / unexpected |
| --- | --- | --- | --- |
| [current-current](current-current.json) | 11 PASS | 20 / 20 / 20 | 0 / 0 / 0 |
| [previous-edge](previous-edge.json) | 11 PASS | 20 / 20 / 20 | 0 / 0 / 0 |
| [rollback-core](rollback-core.json) | 11 PASS | 20 / 20 / 20 | 0 / 0 / 0 |

Each pair additionally verifies two legacy devices through MQTT, HTTP replay and readback.
The primary-device reconciliation counts above exclude these separately asserted legacy fixtures.
Exact Edge revisions, image IDs, UTC intervals, configuration hashes and checkpoint counts are
inside each report. All three reports passed the strict software evidence validator.

Original artifact IDs: current-current `10952320985`, previous-edge `10951809294`, rollback-core
`10951849290`. Bounded synthetic service logs remain in the Actions artifacts (30-day retention).
No service logs or raw payloads are copied into this directory.

These are CI results for the recorded commits. They do not qualify the frozen v0.3.1 release,
other commits, other image digests, staging, 24-hour soak, restore/rollback or physical canary.
The current Core/Edge images were built from source, so published-image qualification must rerun
with both digest-pinned images and match the report to the qualification inputs.

See [runbook](../../../CROSS_REPO_VERIFICATION.md) for reproduction and release handoff.
