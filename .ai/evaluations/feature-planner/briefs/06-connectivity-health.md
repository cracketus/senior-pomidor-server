# Implementation Brief: Edge connectivity health telemetry

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-06

## Problem

Operators cannot reliably distinguish Wi-Fi/link loss from MQTT/API failure, and diagnostics must not expose private network data.

## Desired outcome

A bounded versioned edge health artifact reports layered connectivity state and freshness, survives reconnect/reboot, and supports private operations without publishing identifiers.

## Current behavior and evidence

`docs/NETWORK.md` and `tools/edge_readiness.py` provide permitted network/readiness evidence. The edge implementation repository, available radio metrics and public-status consumer are Unknown.

## Scope

- Define privacy-safe health schema, collection cadence, stale semantics, storage/observability, reconnect tests and rollout compatibility.

## Out of scope

- Router reconfiguration, credential/SSID/IP publication, automatic network repair, unrelated telemetry refactor.

## Architecture placement

Edge network adapter observes link/interface/connectivity; server ingestion/storage exposes bounded health. State Estimator may consume freshness but does not own Wi-Fi recovery.

## Affected contracts and consumers

New health version/producer required. Edge, MQTT/HTTP, storage, API/dashboard/alerts and public projection must be marked affected/unaffected; SSID, IP, MAC and routes are private and excluded.

## Safety/risk classification

Classes: `edge_hardware_integration`, `schema_data_contract`. Flags: `edge_server_compatibility`, `public_contract`. Apply `SP-FAIL-006`, `SP-FAIL-017`, `SP-FAIL-011`.

## Proposed implementation sequence

1. Inventory available privacy-safe signals and consumers.
2. Approve versioned states/freshness and redaction.
3. Add fake disconnect/reconnect/reboot/stale tests and server fixture replay.
4. Canary privately before dashboard/public consideration.

## Failure modes

Interface absent, no route, TCP refused/timeout, MQTT disconnected, stale sample, reboot clock/counter reset and server unavailable remain distinguishable without guessing root cause.

## Backward compatibility

Additive artifact; older edge remains accepted and displayed as unsupported/unknown, not unhealthy. Server rolls out before edge.

## Testing plan

Baseline plus schema round-trip, old/new fixture replay, simulated layer failures/reconnect/backoff/reboot/stale and privacy serialization tests. Manual target Wi-Fi profile/reboot evidence.

## Observability

Private health shows bounded layer/status/age/reconnect count; public output exposes only coarse sanitized freshness if policy approves.

## Documentation updates

Update network troubleshooting, contracts, dashboard/alert meaning and public-data policy if affected.

## Rollout and rollback

Server tolerant reader first, then one edge canary. Abort on ingestion load/privacy leakage; disable producer while preserving old telemetry.

## Acceptance criteria

- [ ] Layer failures and stale/reconnect behavior are deterministic and do not expose private network identifiers.
- [ ] Old edge payloads remain accepted throughout rollout.

## Blocking open questions

- Edge owner/repository, available signals/permissions, cadence/retention and allowed private/public consumers?

## Evidence and references

- `docs/NETWORK.md`; `tools/edge_readiness.py`.
- Edge runtime and production network conditions are unverified.
