# Implementation Brief: Documentation ownership map

Status: approved

Planner/version: Codex draft / 2026-08-10

Approver/date: User approval / 2026-08-10

Issue/decision: #150 / TOMATO-AI-30

## Problem

The repository has no versioned machine-readable map that identifies which documents describe
which source paths, who owns the decision, or how documentation conflicts must be handled. This
makes later drift detection unable to distinguish mechanical synchronization from semantic review.
The proposed map and its validator are not yet present in the inspected tree; this is an observed
absence, not evidence that no external process exists.

## Desired outcome

A versioned `docs_map_v1` map covers the principal schema/model, API/storage, Compose/deployment,
State Estimator, future control boundaries, hardware adapters, and public README/status areas.
A deterministic read-only validator rejects malformed, unknown, ownerless, or conflicting mappings
and emits a bounded coverage report.

## Current behavior and evidence

- `.ai/CORE_INVARIANTS.md`, `.ai/ARCHITECTURE_RULES.md`, `.ai/TEST_MATRIX.md`, and
  `.ai/known-failures.yaml` define ownership, contract, safety, and check requirements.
- `SP-FAIL-009` and `SP-FAIL-010` require named versioned shapes and explicit units/conversions.
- `SP-FAIL-011` requires replay through real consumer boundaries.
- The `docs-map.yaml` path and validator are not found in the inspected repository tree.
- Exact external/edge repository consumers are `Unknown` and must be recorded as such rather than
  invented.

## Scope

- Add versioned `docs_map_v1` YAML with source path patterns, authoritative documents, owner,
  authority direction, mechanical fields, semantic-review requirement, conflict behavior,
  cross-repository/edge impact, and required checks.
- Cover the seven areas named in the issue plan.
- Add a read-only validator and deterministic coverage report.
- Add synthetic fixtures and focused failure-path tests for complete coverage, unknown paths,
  missing owners, authority conflicts, and mechanical versus semantic mappings.

## Out of scope

- Changing runtime code, existing documentation meaning, schemas, Compose behavior, or public claims.
- Automatically treating code as authoritative during a conflict.
- Inferring edge repositories, hardware facts, production topology, or consumer ownership.
- Workflow-triggered fixes, comments, PRs, issue creation, deployment, or main-branch mutation.

## Architecture placement

- The map and validator belong to repository tooling and governance, not application runtime.
- The validator reports ambiguity as `human_review`/failure and never resolves authority by recency.
- Future Control/Guardrails/Executor entries describe boundaries only; they do not create those
  components or grant actuation authority.

## Affected contracts and consumers

- New contract: `docs_map_v1`; producer is the versioned map; consumers are the validator,
  coverage report, and later read-only drift analyzer. Paths, owners, and check IDs are strings;
  no telemetry units or timestamps are introduced.
- API/MQTT/storage/edge/dashboard/export consumers: unaffected by behavior, but named as
  `unaffected with evidence` or `unknown` per map entry.
- Documentation and CI tooling consume the map; no production or public dataset is written.

## Safety/risk classification

- Task classes: `pure_software`, `schema_data_contract`.
- Risk flags: `public_contract` because the map governs public/status and contract documentation.
- Applicable failures: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`.
- No physical action, production access, secret, deployment, or hardware evidence is authorized.

## Proposed implementation sequence

1. Inspect current paths and authoritative documents; record unknown consumers.
2. Define and validate `docs_map_v1`, including closed enums and fail-closed conflict rules.
3. Add representative synthetic fixtures for each covered area.
4. Implement deterministic coverage/conflict validation with bounded secret-safe output.
5. Add focused tests, schema round-trip, named-consumer checks, and full selected checks.

## Failure modes

| Failure | Detection | Safe behavior | Test/recovery |
|---|---|---|---|
| Unknown source path | validator error | report incomplete; no synchronization | unknown-path fixture; add reviewed mapping |
| Missing owner/consumer | schema/semantic error | fail closed | ownerless fixture |
| Conflicting authority | conflict rule | `human_review`; never choose code/docs | conflict fixture |
| Malformed YAML/schema | parse/schema error | no report marked complete | malformed fixture |
| Windows path/cleanup issue | focused test | bounded temp cleanup | `tmp_path`, explicit close; SP-FAIL-014 |

## Backward compatibility

The map is additive and versioned. Existing files, fixtures, runtime contracts, and docs remain
unchanged. Unknown future paths fail closed until a map update is reviewed. `docs_map_v1` is not
retired or silently reinterpreted without a new version and migration note.

## Testing plan

- Required: focused validator/failure-path tests; schema validation; serialization round-trip;
  named-consumer checks; `git diff --check`; `python -m pytest -q`; `nox -s lint format_check types`.
- Required: `python -m tools.evaluate_feature_planner` if planner/governance contracts change.
- Optional: platform-specific replay where no executable path is affected.
- Manual: `NOT_RUN` for production, physical, deployment, and external-consumer outcomes.

## Observability

The validator emits a deterministic bounded report containing map version, checked paths, coverage,
errors, conflicts, and check IDs. It must not include secrets, environment values, private hosts,
or raw payloads. A report is successful only when all required paths are known and conflict-free.

## Documentation updates

Add the map, its schema/README usage, fixtures, and tests. Do not update claims in existing public
documentation unless a separate semantic review approves the wording.

## Rollout and rollback

Rollout is local/CI read-only validation only. Abort on unknown paths, conflict, malformed input, or
secret scan findings. Rollback removes the map validator, fixtures, and generated artifacts; it must
not modify runtime data, shared services, or `main`. Owner: development maintainer.

## Acceptance criteria

- [ ] `docs_map_v1` validates and serializes deterministically.
- [ ] All seven required areas have owner, authority, consumer impact, conflict behavior, and checks.
- [ ] Unknown paths, missing owners, conflicts, and malformed maps fail closed.
- [ ] Mechanical and semantic entries are distinguished in fixtures and tests.
- [ ] No runtime, production, hardware, secret, or `main` mutation occurs.
- [ ] Required automated checks are recorded as `PASS`, `FAIL`, or `NOT_RUN`.

## Blocking open questions

- Human maintainer must confirm authoritative document paths and owners where repository evidence is
  currently `Unknown`.
- Human maintainer must confirm whether public README/status is one authority or separate owners.

## Evidence and references

- `.ai/CORE_INVARIANTS.md`, `.ai/ARCHITECTURE_RULES.md`, `.ai/TEST_MATRIX.md`.
- `.ai/known-failures.yaml`: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`.
- User-supplied TOMATO-AI-30–33 implementation plan; issue details not verified because GitHub CLI
  authentication was unavailable.

Approval of this brief does not itself authorize production deployment, production data/secrets access, or real hardware activation.
