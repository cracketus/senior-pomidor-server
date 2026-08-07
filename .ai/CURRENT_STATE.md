# Current state

Owner: maintainer performing a release or operational change. Update after every deployed subsystem, contract, topology, season, or rehearsal change and review at least monthly during the active season. Snapshot date: 2026-08-06. Do not add addresses, credentials, hostnames, or other private infrastructure values.

## Running/deployable services

- `api`: FastAPI health/read/ingestion endpoints and LAN dashboard.
- `worker`: MQTT telemetry subscriber.
- `state-estimator-worker`: canonical state, confidence, health, anomaly, diagnostics, and private JSONL generation.
- `migrate`: one-shot Alembic migration gate.
- Local-development overlay: PostgreSQL, Mosquitto, optional Grafana, Ollama, daily story, and Grafana Cloud exporter profiles.
- Production application: source-free immutable bundle managed by systemd/Compose. PostgreSQL, Grafana, and Ollama are separate shared platform services on `srv-platform`; the application must not lifecycle-manage them.

## Active contracts and storage

- Edge telemetry: `senior-pomidor.edge.telemetry.v1` and `.v2` over MQTT and HTTP fallback.
- Edge photo: `senior-pomidor.edge.photo.v1` JPEG multipart upload.
- Derived artifacts: `state_v1`, `sensor_health_v1`, `anomaly_v1`, estimator diagnostics, private JSONL.
- Public status: sanitized `senior-pomidor.status.v1`; optional Grafana Cloud export contains only the documented low-cardinality projection.
- PostgreSQL is the durable source of truth for application records; uploaded photos and private estimator logs use application-owned persistent paths.

See [`docs/CONTRACTS.md`](../docs/CONTRACTS.md), schemas in [`docs/schemas/`](../docs/schemas/), and fixtures in [`tests/fixtures/contracts/`](../tests/fixtures/contracts/).

## Implemented vs. not implemented

Implemented: telemetry/photo ingestion and reads, MQTT reconnect behavior, readiness/migrations, State Estimator and deterministic replay, Grafana dashboards/alerts, bounded public export, backup/restore tooling, offline vision analysis, and local daily story. Provider-neutral assistant utilities remain under `app/assistant/`, but no assistant service is active in the current Compose topology.

Development workflow: Feature Planner 1.1 produces draft-only Implementation Briefs through six task workflows. Its historical evaluation suite contains ten frozen cases and is validated by `python -m tools.evaluate_feature_planner`. Coding Agent 1.0 implements only approved briefs and returns a versioned Implementation Report. The local agent-task CLI creates isolated branches/worktrees and renders bounded loopback-only Compose tasks with fake hardware and external export disabled. These tools do not authorize production deployment, production access, or hardware actions.

Not implemented as active physical-control contracts: World Model forecasts, Weather Adapter policy, autonomous Control scheduling, actuator Guardrails beyond read-only action simulation, Executor/hardware command delivery, GPIO control, and public dataset publishing APIs. Do not describe prototypes such as `action_v1`, `forecast_36h_v1`, `targets_v1`, or `sampling_plan_v1` as production contracts.

## Operational constraints and gaps

- The growing season is active: prefer availability, ingestion correctness, data preservation, and small reversible changes over unrelated refactoring.
- Coding agents do not have production secrets, production shell/database access, real GPIO, actuators, or permission to deploy by default.
- Standard CI is software-only. Camera, cable, Wi-Fi, SD-card, sensor, GPIO, and biological outcomes need explicit manual evidence.
- Backups and restore tooling exist, but recovery confidence depends on a recent isolated restore rehearsal; a backup file alone is not proof.
- Rehearsal uses a distinct Compose project, loopback-only ports, isolated paths/credentials, and must not enable the Grafana Cloud exporter.
- Windows and Linux remain relevant to development and migration; filesystem, permissions, path, and temporary-directory behavior must be checked deliberately.
- Edge code is maintained outside this repository. Any edge-facing contract change requires an identified edge consumer and a coordinated compatibility plan; do not invent a repository URL if it is not recorded in an approved brief.

## Deployment and rehearsal

Local development uses `docker-compose.yml` plus `docker-compose.dev.yml`. Production uses `docker-compose.yml` plus `docker-compose.prod.yml` and platform-managed dependencies as documented in [`docs/UBUNTU_HOST.md`](../docs/UBUNTU_HOST.md). Migration/cutover and isolated rehearsal are documented in [`docs/MIGRATION_WINDOWS_TO_UBUNTU.md`](../docs/MIGRATION_WINDOWS_TO_UBUNTU.md); rollback must stop only the application and preserve shared services/data.

## Known gaps requiring follow-up

- Keep this snapshot synchronized with releases and season status; updates are manual.
- Expand restore rehearsal evidence on a regular cadence.
- Add separate approved designs before implementing World Model, Weather Adapter, Control, Guardrails, Executor, or real hardware paths.
- Track unresolved incidents in [`KNOWN_FAILURES.md`](KNOWN_FAILURES.md) without embedding sensitive incident data.
