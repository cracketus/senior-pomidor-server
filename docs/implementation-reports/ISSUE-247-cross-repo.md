# Implementation Report: #247 real Edge/Core verification

Issue/brief: #247, #248–#252; `.ai/implementation-briefs/ISSUE-247-cross-repo.md`.

Agent run ID / audit artifact: `20260927-issue-247-coder`,
`.ai/agent-runs/20260927-issue-247-coder.json`.

Branch/worktree: `feature/ISSUE-247-cross-repo-verification`, isolated task
`issue-247-cross-repo-verification`; base `aea94fd6235f0ecc242e5d1806332715fd7b85ce`.
PR: https://github.com/cracketus/senior-pomidor-server/pull/365.

Task classes: pure_software, schema_data_contract, infrastructure_deployment,
edge_hardware_integration (synthetic sensors only).
Risk flags: edge_server_compatibility, security_secrets, production_availability, public_contract.
Applicable failures: SP-FAIL-001/002/003/004/005/006/009/010/011/014/017.

## Implemented behavior and files

- `tools/cross_repo`, `tests/cross_repo`: bounded isolated real Edge formatter,
  durable SQLite spool, delivery worker, HTTP/MQTT ingestion and PostgreSQL/read APIs.
  Normal delivery, duplicate transport, outages, restart, fresh delivery during replay,
  lost durable ACK, timestamp preservation, stale/future data, high VPD, malformed and
  legacy payloads have explicit assertions. Estimator replay uses actual persisted events,
  production normalization/estimation/persistence and observation-time duration policy.
- `tests/test_system_properties.py`: deterministic bounded Hypothesis identity/order,
  units/optionality, invalid timestamp, freshness and Vienna DST properties.
- `.github/workflows/cross-repo.yml`: candidate/current Edge, candidate/previous Edge,
  released v0.3.0 Core/current Edge. Pins and exact Git/image identities are recorded.
- Evidence schema and validator reject extra fields, missing scenarios, bad counts,
  wrong revisions/digests, invalid intervals and unsupported future-action claims.
  Release qualification requires the same published images and still requires existing
  staging, soak, restore/rollback and canary evidence.
- `app/operator_summary.py`: use column `.desc()` expressions to satisfy current
  SQLAlchemy typing for window ordering; SQL ordering and operator semantics are unchanged.

## Design decisions and deviations

One cohesive draft PR integrates the six authorized steps instead of six sequential PRs;
no issue is automatically closed and operational acceptance remains separate. This packaging
change does not expand the authorized implementation scope. The historical brief's staged
PR language is preserved as planning history.

Sensor acquisition and sample clock are controlled; transport/storage/retries remain real.
The estimator is deterministically replayed against persisted rows, not replaced with a fake.
Read API/SQL snapshots reconcile within a deadline because live ingestion can advance between
reads. Legacy fixtures must first appear through MQTT, then survive HTTP replay without duplication.

A fresh random project, internal network, no published ports, owned volumes, bounded resources,
no devices/host mounts/exporter and local-only Docker endpoint address SP-FAIL-001/003.
Failures preserve bounded synthetic diagnostics; cleanup always attempts stop/down without
volume deletion. Revert this PR to roll back tooling; existing telemetry and databases need
no migration. SP-FAIL-005 restore evidence remains a release-maintainer gate, not simulated PASS.

## Tests and evidence

Commands below used existing development environments with the project dependencies.

| Status | Command/check | Evidence |
|---|---|---|
| PASS | `python -m pytest tests/test_cross_repo_harness.py tests/test_system_properties.py -q` | 24 passed |
| PASS | `ruff check app tools tests`; `ruff format --check app tools tests` | clean |
| PASS | `python -m bandit -q -r app tools -c pyproject.toml` | no findings |
| FAIL | Initial PR CI | wrong Edge repository name, missing Bandit annotations, SQLAlchemy typing; corrected in follow-up |
| PASS | Initial PR test and docker-e2e jobs | run 36342171167 |
| NOT RUN | Current full cross-repository matrix | run 36377718853 in progress; report to be updated after completion |
| PASS | Linux/Windows property, evidence and CLI smoke | run 36378275152, harness-contracts jobs |
| NOT RUN | Exact published-image qualification | maintainer campaign must supply image digests |
| NOT RUN | Staging/24h soak/restore/rollback/canary/hardware | maintainer-owned operational campaign |

Full local suite previously returned 709 passed, 2 skipped, 1 failed: the existing Compose
render test requires Docker, which is absent in this environment. Docker checks run in GitHub.
Mypy passed with a fresh cache after detecting a corrupted local cache; dependency audit
passed after updating the development environment pip, as the canonical nox session does.

## Compatibility, safety and limitations

Telemetry v1/v2, HTTP ACK and operator API contracts are preserved; no database migration,
production access, physical action, private dataset or exporter is involved. Existing CLI/TUI
consumers continue to use unchanged responses. Current/previous Edge and rollback Core are
verification targets until the executable matrix passes, not unconditional support claims.

Strict CI reports are software evidence; local Docker image IDs are not registry manifest
digests. Preflight failure reports may be partial diagnostics and cannot pass qualification.
Future actuator invariants remain NOT_IMPLEMENTED. Branch protection is maintainer-owned.
Full #247 also contains performance, mutation/fuzzing, dataset protection and alert backlog.

## Documentation and review

Runbook, contract/operations/staging links, current state and invariant mappings describe
reproduction, artifact identity and remaining gates. Historical release evidence is untouched.
Independent review is required by AGENTS.md; prior findings about high-VPD assertions,
freshness assertions, digest matching and cleanup were addressed and await re-review.
Final diff and evidence review remain in progress; draft status is intentional.
