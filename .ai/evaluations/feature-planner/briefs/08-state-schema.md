# Implementation Brief: Reconcile flat and nested state schemas

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-08

## Problem

A flat consumer state payload conflicts with nested canonical state; silent dual interpretation could break edge, storage, dashboard or fixtures.

## Desired outcome

One versioned canonical shape remains authoritative and an owned compatibility adapter supports an explicit migration window with all consumers verified.

## Current behavior and evidence

`docs/CONTRACTS.md`, `docs/schemas/` and `tests/fixtures/contracts/` are permitted evidence. The identity/version of the flat consumer and its deployed population are Unknown.

## Scope

- Inventory consumers, define old/new shape and adapter, preserve units/timezone/optionality, replay fixtures and stage rollout.

## Out of scope

- Silent in-place field reinterpretation, unrelated estimator changes, deleting old support before evidence.

## Architecture placement

Canonical normalization stays with State Estimator/contract owner; one transport/compatibility adapter converts legacy shape. Dashboards do not become schema adapters.

## Affected contracts and consumers

Schema version, nested paths, units/ranges, UTC/Europe-Vienna semantics, optional/null and unknown fields require explicit tables. Inventory edge, MQTT/HTTP/API, storage/migration, fixtures, estimator/control, dashboards, export/public dataset and docs.

## Safety/risk classification

Class: `schema_data_contract`. Flags: `edge_server_compatibility`, `public_contract`; add `physical_action` if Control consumes it. Apply `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`.

## Proposed implementation sequence

1. Identify flat producer/consumers and capture sanitized old fixtures.
2. Approve additive version/adapter and compatibility window.
3. Add round-trip and old/current/new replay through HTTP/MQTT/storage and downstream queries.
4. Deploy tolerant server first, migrate consumers, observe usage, then retire by separate approval.

## Failure modes

Missing nested fields, mixed shapes, percent/ratio mismatch, timezone drift, unknown fields, old storage rows and dashboard query mismatch fail explicitly or adapt at the single boundary.

## Backward compatibility

Old fixtures remain accepted for the declared window; new producer is never deployed before tolerant consumers. Rollback retains adapter and old schema reader.

## Testing plan

Baseline, JSON schema validation, round-trip, boundary units, DST/timestamps, old/current/new fixtures via API/MQTT/storage, estimator and dashboard/export/public serialization tests.

## Observability

Count schema versions/adapter use/rejections and bounded reason without raw private payloads; retirement requires observed old-version absence.

## Documentation updates

Update contracts/schemas/fixtures, consumer matrix, rollout/retirement guide and dashboards/public policy if fields change.

## Rollout and rollback

Tolerant reader -> shadow adapter metrics -> canary producer -> consumer migration. Abort on rejection/semantic drift; restore old producer while adapter remains.

## Acceptance criteria

- [ ] Every downstream consumer is classified and old/current/new fixtures preserve documented units/timezone/optionality.
- [ ] Mixed-version rollout and rollback pass through real ingestion/storage paths.

## Blocking open questions

- Flat producer/consumer identities, deployed versions, exact field mapping, retention window and any Control/public consumers?

## Evidence and references

- `docs/CONTRACTS.md`; `docs/schemas/`; `tests/fixtures/contracts/`.
- Flat consumer identity and deployed state are unverified.
