# Project facts

Owner: project maintainer. Review when a stable architectural decision changes; otherwise verify quarterly. Last verified: 2026-08-06.

## Purpose and scope

Senior Pomidor is an open, transparent embodied-AI project for observing and eventually assisting a real plant-growing system. This repository is the server side. It ingests Raspberry Pi edge telemetry and photos, stores audit artifacts, derives canonical state, exposes read APIs, and provides local/publicly sanitized observability. The physical world is always outside the server trust boundary.

The system is split into three domains:

- **Server:** API, MQTT ingestion, durable PostgreSQL storage, State Estimator, offline/local AI consumers, observability, packaging, and deployment assets in this repository.
- **Edge:** Raspberry Pi sensing, camera capture, connectivity, and hardware adapters. It communicates through versioned MQTT/HTTP contracts; edge/server compatibility is evaluated independently.
- **Physical world:** sensors and eventual actuators. Hardware state, wiring, power, placement, and biological outcomes require human observation and may not be reproducible in CI.

## Stable ownership boundaries

- `app/api.py`, `app/main.py`: HTTP transport and read surfaces; business/storage behavior belongs in services or focused modules.
- `app/mqtt_worker.py`, `app/telemetry.py`, `app/validation.py`: edge telemetry transport, validation, and compatibility.
- `app/models.py`, `app/db.py`, `migrations/`: durable application data and schema evolution.
- `app/state_estimator/`: normalization, confidence, derived metrics, sensor health, anomalies, deterministic replay, and canonical state.
- `app/ollama.py`, `app/ai_analysis.py`, `app/daily_story*`, `app/assistant/`: bounded analyst/communication consumers. Their model output is untrusted input.
- `docker/`, `docker-compose*.yml`, `deploy/`: local and production topology. Shared production PostgreSQL, Grafana, and Ollama remain platform-owned.
- `docs/schemas/` and `tests/fixtures/contracts/`: machine-readable edge contracts and compatibility fixtures.
- `tests/`: executable behavioral evidence; `docs/`: operator and contract guidance.

Future World Model, Weather Adapter, Control, Guardrails, and Executor responsibilities are defined in [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md). They must not be collapsed into the currently implemented State Estimator or AI consumers.

## Project-wide principles

- External and cross-module data artifacts are explicitly versioned. Units, ranges, optionality, timezone, and compatibility are part of the contract.
- Timestamps are UTC at interchange/storage boundaries; local scheduling and biological-day interpretation use `Europe/Vienna` with DST-aware conversions.
- Unit/schema consistency must be preserved end to end. Percent (`0..100`) and normalized ratio (`0..1`) values are never interchangeable without named conversion.
- Every consequential decision and failure path must be observable and reproducible from bounded inputs, configuration version, and audit artifacts.
- Public outputs follow [`docs/PUBLIC_DATA_POLICY.md`](../docs/PUBLIC_DATA_POLICY.md); private telemetry, images, paths, infrastructure, and credentials are not made public by default.
- LLM/VLM output is untrusted, schema-validated analyst input. There is no direct LLM-to-actuator path.
- Physical actions, once implemented, must pass deterministic Guardrails and an idempotent Executor.
- Active-season reliability takes priority over non-essential refactoring.

## Authoritative sources

- Runtime topology and operations: [`docs/OPERATIONS.md`](../docs/OPERATIONS.md)
- Active contracts: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md)
- State Estimator design: [`docs/state_estimator_spec_v_1_0_en.md`](../docs/state_estimator_spec_v_1_0_en.md)
- Production platform boundary: [`docs/UBUNTU_HOST.md`](../docs/UBUNTU_HOST.md)
- Edge checks: [`docs/PI_INTEGRATION_RUNBOOK.md`](../docs/PI_INTEGRATION_RUNBOOK.md)

This file summarizes agent-critical invariants; those documents and runtime tests remain authoritative for detail.
