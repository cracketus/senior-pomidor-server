# Implementation Report: Validated versioned topology provider

Issue/brief: [#332](https://github.com/cracketus/senior-pomidor-server/issues/332) / human-approved
Implementation Brief

Agent run ID / audit artifact: `20260909-issue-332-coder` /
`.ai/agent-runs/20260909-issue-332-coder.json`

Branch/worktree: `feature/TOMATO-332-map-topology-provider` /
`.agent-worktrees/tomato-332-map-topology-provider`

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`;
`security_secrets`, `production_availability`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-004`, `SP-FAIL-014`, `SP-FAIL-015`, `SP-FAIL-016`.
`SP-FAIL-016` was router-selected through `pyproject.toml`; its SSH symptom is not applicable, while the
selected secret and dependency checks were retained.

## Implemented behavior

- Adds strict immutable `senior-pomidor.map.v1` models with separate identity namespaces, bounded
  collections, explicit units/ranges, UTC timestamps, half-open intervals, typed references, provenance,
  profiles, bindings, and complete revisions.
- Loads only bounded UTF-8, single-document safe YAML from regular files; rejects aliases, custom tags,
  duplicate mapping keys, unknown fields, malformed content, invalid identities/references/intervals,
  non-finite values, and invalid revision history.
- Verifies SHA-256 over canonical validated content with sorted object keys, finite JSON numbers, UTF-8, and
  UTC microseconds, excluding only the digest field.
- Resolves `AS_KNOWN_CORE` by observation time and `RECONSTRUCTED` by request cutoff, using explicit
  supersession as the sole overlap winner.
- Atomically swaps a fully validated immutable catalog. Failed first load reports `TOPOLOGY_UNAVAILABLE`;
  failed later reload reports `TOPOLOGY_INVALID` while retaining the exact prior catalog and digest.
- Provides immutable topology snapshots and target/capability binding results with revision, digest,
  profile version, provenance, entities, and bindings.
- Packages four sanitized full-history revisions covering source-channel identity, targets A/B, replacement,
  relocation, and an append-only retroactive correction.

## Files changed and purpose

- `app/map/`: isolated models, canonical digest support, validation, historical resolution, and atomic provider.
- `config/topology/`: four complete synthetic, digest-bound history revisions with no private identifiers.
- `tests/test_map_topology.py`: happy, history, strict-input, graph, digest, reload, and concurrency regressions.
- `pyproject.toml`: moves PyYAML from development-only to the runtime dependency set.
- `Dockerfile`, `tests/test_release_assets.py`: package and assert the complete topology history and runtime parser.
- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`, `.ai/CURRENT_STATE.md`: record only the topology slice as implemented.
- This report and the matching bounded `agent_run_v1` artifact: implementation and validation evidence.

## Design decisions

- A revision file is a complete immutable topology, so readers never assemble partially updated state.
- Canonical channel IDs are globally unique; source-local keys are unique only within their owning source.
  This permits the same pod key on different sources without identity collision.
- Revision overlaps form an explicit backward-only acyclic supersession chain. Any incomparable overlap is
  rejected before publication.
- Directed cycles are permitted only when every participating cycle edge is physical-link or data-flow.
  Any cycle containing containment or capability-dependency is rejected.
- Provider status contains only availability, active revision/digest, and a fixed error code; parser details
  and local paths stay inside the validation boundary.

## Deviations from brief

- The brief's literal `--issue 332` task-create command was rejected because the checked-in wrapper requires
  `TOMATO-123`-style identities. The task was created as `TOMATO-332`, yielding task key
  `tomato-332-map-topology-provider`; implementation scope and issue linkage are unchanged.
- `tools.validate_change` hard-codes `audit_record=None` whenever an `.ai/agent-runs/` path changes, making
  its maturity gate fail with "missing audit record" for the audit artifact it requires. The audit file was
  therefore held in the task-owned state directory for the successful canonical full run, then restored and
  validated separately with `tools.agent_audit` plus the final focused/diff checks. The provider code,
  topology data, packaging, tests, state/spec documentation, and this report were present in the successful run.
- No staging, production, real-data, or hardware operation was performed, as required by the brief.

## Tests added

- Synthetic seed, immutable snapshots, distinct A/B bindings, profile/digest/provenance exposure, and
  canonical round-trip.
- S06-S08 replacement, half-open relocation boundary, as-known history, reconstructed cutoff, and late correction.
- Duplicate key/ID/local identity, alias/tag/multi-document YAML, unknown schema/field, digest mismatch,
  reference/type errors, non-UTC time, invalid intervals, ambiguous overlap, and supersession failures.
- Containment/capability cycle rejection and physical/data-flow cycle acceptance.
- Missing/invalid first load, exact previous-catalog retention, bounded status, and complete old/new snapshots
  under a concurrent reload.
- Runtime dependency placement and complete Docker image topology-history inclusion.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_map_topology.py tests/test_release_assets.py` | 52 passed. |
| PASS | `python -m pytest -q` | 561 passed, 12 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed. |
| PASS | `nox -s security` | Bandit found no issues. |
| PASS | `nox -s deps_audit` | No known vulnerabilities found. |
| PASS | `python -m tools.agent_task compose tomato-332-map-topology-provider config` | Isolated configuration rendered and validated; no containers started. |
| PASS | `python -m tools.validate_change --base origin/main --task-key tomato-332-map-topology-provider --explain --force full` | Exit 0; focused/full pytest, quality, diff, security, dependency audit, and isolated Compose passed. Non-command/manual evidence remained `NOT_RUN`. |
| PASS | `python -m tools.agent_audit .ai/agent-runs/20260909-issue-332-coder.json` | Bounded `agent_run_v1` artifact is valid. |
| PASS | `git diff --check origin/main --` | No whitespace errors. |
| NOT RUN | Isolated rehearsal, rollback, post-deploy health | Human authorization/observation not provided; no runtime start was needed for this isolated library slice. |
| NOT RUN | Production, real bindings/calibration, database, external export, hardware | Prohibited and outside scope. |

## Compatibility checks

- Schema validation and serialization round-trip pass through the real YAML loader and all four current
  history fixtures. S06-S08 select both temporal modes and their exact boundaries.
- Packaging assertions cover `app*` package discovery, the runtime PyYAML dependency, and full
  `config/topology/` Docker image inclusion (`SP-FAIL-004`, `SP-FAIL-015`).
- Tests run on Windows using `tmp_path` and closed file handles (`SP-FAIL-014`).
- Future raw reader #333, evaluator #334, private API #335, operator clients, and synthetic demo are named but
  not yet implemented, so end-to-end named-consumer checks are `NOT_RUN`. Existing Edge, MQTT/HTTP, storage,
  estimator/control, dashboards, and public export have no imports or contract changes.

## Safety impact

- No API, startup, database, estimator, control, Guardrails, Executor, network, external-export, or hardware
  path is added or changed.
- No secrets, private identifiers, private infrastructure, production access, deployment, or canonical-data
  write occurred. The catalog is explicitly synthetic and calibration claims are synthetic-only.
- Rollback is a normal revert or previous immutable application image. There is no migration or data rollback;
  PostgreSQL, canonical state, photos, shared services, and pending Edge spool remain untouched.

## Known limitations

- Map reader, evaluator, API, operator UI, and real-data activation remain unimplemented under #333-#336.
- No physical-world, staging, rollout, rollback, or post-deploy health evidence exists for this slice.

## Documentation changes

- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md` distinguishes the implemented topology boundary from every future slice.
- `.ai/CURRENT_STATE.md` records the packaged synthetic provider without describing it as an active service/API.

## Manual verification steps

- `NOT_RUN`: isolated rehearsal and application-image rollback/post-deploy health. A human may separately
  authorize these against an immutable candidate using task-owned paths and disabled external export.
- `NOT_RUN`: real topology/binding/calibration verification and all physical checks. Abort on private data,
  production paths, non-synthetic bindings, external export, database writes, or hardware access.

## Final diff review

- Scope is limited to the isolated provider, synthetic history, packaging/dependency assertions, tests, and
  truthful state/spec/report updates. No route or canonical-data mutation was introduced.
- No secrets, private infrastructure, real identifiers, debug artifacts, weakened checks, unsafe defaults,
  unrelated refactors, or rollback gaps were found.
