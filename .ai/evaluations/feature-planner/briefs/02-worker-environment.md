# Implementation Brief: Diagnose unhealthy worker and missing environment

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-02

## Problem

A Compose worker is unhealthy after startup and a required image/environment value may be absent. The missing value is a hypothesis, not a proven root cause; ingestion must be preserved.

## Desired outcome

Invalid configuration fails before startup with a bounded message, and a correctly configured worker becomes healthy and produces fresh functional output after dependency recovery.

## Current behavior and evidence

The fixture permits inspection of `docker-compose.yml`, `docker-compose.dev.yml` and `app/worker_health.py`. The affected worker, logs, rendered environment and exact missing variable beyond possible `APP_IMAGE` are Unknown.

## Scope

- Reproduce locally, validate exact overlay/profile environment, test health/dependency failure and implement the smallest validated correction.

## Out of scope

- Production mutation, secret inspection, broad worker refactor, changing shared platform services.

## Architecture placement

Compose owns environment/dependency wiring; the worker owns bounded health state. Functional freshness, not container-running alone, proves recovery.

## Affected contracts and consumers

Environment and health contracts are affected. Ingestion/storage consumers must remain compatible; ports, mounts and public contracts are unchanged unless evidence proves otherwise.

## Safety/risk classification

Classes: `infrastructure_deployment`, `pure_software`. Flag: `production_availability`. Apply `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`.

## Proposed implementation sequence

1. Capture secret-safe reproduction and exact Compose command/profile.
2. Render config with explicit non-secret `APP_IMAGE`; verify missing required values fail clearly.
3. Inject dependency/startup failure and recovery; add regression before correction.
4. Make minimal config/health change and rehearse in isolation.

## Failure modes

Missing image/env, migration/database unready, stale health file, crash loop and recovery without fresh ingestion require distinct observable states.

## Backward compatibility

Preserve existing optional/default env behavior; newly required variables need release documentation and preflight validation.

## Testing plan

Run baseline, Compose config for exact overlays/profiles, config/worker tests and isolated build/up/health/fresh-output rehearsal. External export remains disabled.

## Observability

Bounded worker health records dependency/error category and freshness without environment values or credentials.

## Documentation updates

Update `.env.example`, operations/startup checks and known failure only if the validated root cause changes guidance.

## Rollout and rollback

Use a distinct rehearsal project/paths/loopback ports. Abort on ingestion/data freshness regression. Roll back the application config/image only; do not stop shared services.

## Acceptance criteria

- [ ] Invalid environment fails before worker start; valid startup and dependency recovery become healthy with fresh output.
- [ ] Isolated rehearsal proves no production path or external export is used.

## Blocking open questions

- Which worker/profile/command failed, what health reason/log evidence exists, and is ingestion currently buffered or lost?

## Evidence and references

- `docker-compose.yml`; `docker-compose.dev.yml`; `app/worker_health.py`.
- Root cause and production state are unverified.
