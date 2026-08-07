# Task classification and test matrix

Owner: test/CI maintainer. Markdown is the human source of truth; keep [`.ai/test-matrix.yaml`](test-matrix.yaml) synchronized in the same change. Review when commands, CI, contracts, topology, or physical-control capabilities change.

Legend: **R** required before handoff; **M** manual/rehearsal evidence required and never implied by CI; **O** optional unless a risk flag promotes it; **N/A** not applicable. `NOT RUN` requires a recorded reason and blocks completion when the check is **R** or **M**.

## Deterministic classification

Choose every class whose condition is true; requirements accumulate.

| Class | Select when the diff changes |
| --- | --- |
| `pure_software` | Python behavior with no contract, deployment, hardware, control, or model boundary below |
| `schema_data_contract` | schema/version, API/MQTT payload, persistence shape/migration, units, timezone, fixture, dashboard/export/public field |
| `infrastructure_deployment` | Docker/Compose/Dockerfile, CI, deploy/systemd scripts, environment contract, ports/networks/mounts, backup/restore/release |
| `edge_hardware_integration` | edge compatibility, MQTT connectivity behavior, camera/sensor/GPIO/I2C/device adapter or hardware instructions |
| `control_guardrails_executor` | target/budget/action selection, safety gate, physical command, retry/idempotency/acknowledgement, stale-state control behavior |
| `llm_vision` | prompt/model/provider, structured model output, image analysis, timeouts/retries or model-visible/public content |
| `documentation_only` | only prose/comments/context pack changes and no executable config/schema/fixture/command behavior |

If `documentation_only` is selected with any other class, drop it and use the other classes. Unknown or cross-cutting behavior defaults to `pure_software` plus the closest specialized class. A documentation claim about a physical/deployment procedure still carries the matching manual risk review.

## Risk flags

Set a flag when its condition is true; risk overlays add checks and cannot remove class checks.

| Flag | Trigger | Added evidence |
| --- | --- | --- |
| `physical_action` | can cause, permit, suppress, repeat, or time a real actuator action | deterministic simulation; duplicate/retry/timeout/restart/stale/Guardrails tests; human safe-hardware plan and rollback (**M**) |
| `data_loss_migration` | changes durable schema, retention, backup/restore, deletion, paths/volumes | isolated upgrade/restore, counts/hashes, backup and rollback (**M**) |
| `security_secrets` | auth, credential handling, exposure, public surface, permissions, key material | `nox -s security deps_audit`, secret-safe diff/evidence, threat/rollback review |
| `edge_server_compatibility` | changes anything consumed/produced by edge or rollout order | old fixture replay, both-version tests, named edge consumer and manual canary (**M**) |
| `production_availability` | startup, health, dependency, topology, release, network, worker cadence | Compose health/failure checks, rehearsal, rollback and post-deploy health plan (**M**) |
| `public_contract` | changes documented API/schema/status/export/dataset/dashboard contract | all consumers, compatibility/release note, old fixture and serialization checks |

## Safe command catalog

Run from repository root. These commands use local test resources only and must not be pointed at production.

```powershell
# Baseline behavior and quality
python -m pytest -q
nox -s lint format_check types

# Security (network may be needed only by dependency audit)
nox -s security
nox -s deps_audit

# Contract and focused suites
python -m pytest -q tests/test_contract_fixtures.py tests/test_edge_integration_fixtures.py tests/test_validation.py tests/test_api.py tests/test_mqtt_worker.py
python -m pytest -q tests/state_estimator
python -m pytest -q tests/test_ollama.py tests/test_ai_analysis.py tests/test_daily_story.py tests/test_assistant.py

# Render local Compose only; does not start services or export metrics
$env:APP_IMAGE='senior-pomidor-server:agent'
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile observability --profile daily-story config --quiet
Remove-Item Env:APP_IMAGE

# Opt-in local Docker E2E; verify local ports are free first
$env:RUN_DOCKER_E2E='1'
python -m pytest -q tests/test_docker_e2e.py
Remove-Item Env:RUN_DOCKER_E2E

# Whitespace/error check for any change
git diff --check

# Required when Feature Planner/workflow/brief/evaluation contracts change
python -m tools.evaluate_feature_planner
python -m pytest -q tests/test_feature_planner_evaluation.py
```

Never add `cloud-export` to a rehearsal command. Before any Docker E2E/rehearsal, confirm its env, bind mounts, ports, project name, and targets are local and isolated. Real GPIO, I2C, cameras, sensors, and actuators are never standard CI dependencies.

## Class requirements

| Class | Automated (**R**) | Manual/rehearsal (**M**) | Optional (**O**) |
| --- | --- | --- | --- |
| `pure_software` | focused tests; full pytest; Ruff check/format; mypy | none unless risk flag adds it | coverage, security |
| `schema_data_contract` | baseline; schema validation; serialization round-trip; old/current fixture replay; API/MQTT/storage and every named consumer test | edge/public consumer verification when flagged | Docker E2E |
| `infrastructure_deployment` | baseline; Compose config for changed overlays/profiles; config/release tests; shell/static checks appropriate to changed scripts | isolated build/up/health/rollback rehearsal for availability/data changes | Docker build/E2E for docs-only command edits |
| `edge_hardware_integration` | baseline; contract replay; reconnect/timeout/disconnected-device failures; fake GPIO/I2C/camera/backend tests added with the feature | target-device connectivity/capture/sensor inspection and reboot recovery | local Docker E2E |
| `control_guardrails_executor` | baseline; deterministic replay/simulation; allowed/blocked Guardrails; duplicate, retry, timeout, late ACK, restart, stale/low-confidence and storage-failure tests | supervised safe-hardware procedure and rollback only when physical action is possible | performance/soak simulation |
| `llm_vision` | baseline; strict schema/semantic validation; malformed JSON, extra prose/reasoning, timeout, unavailable model, bounded output and privacy tests | representative local-model acceptance if model/runtime behavior changed | cross-model evaluation |
| `documentation_only` | `git diff --check`; verify every changed relative link/path/command against checkout; run Feature Planner evaluation when its agent/workflow/template/evaluation contract changes | procedure walkthrough if it changes physical/deployment instructions | full pytest/quality |

For a new hardware/Executor subsystem whose focused test path does not yet exist, adding those fake/failure-path tests is part of the implementation; do not substitute a generic suite. Database migrations require an isolated PostgreSQL migration/restore procedure from the approved brief—this repository currently has no generic safe one-command round-trip harness.

## High-risk exit criteria

Every high-risk brief (`physical_action`, `data_loss_migration`, `security_secrets`, or `production_availability`) includes:

- failure injection and observable expected state;
- a rollback/abort boundary and owner;
- proof that rehearsal/test paths cannot reach production hardware, data, secrets, or external export;
- `PASS`/`FAIL`/`NOT RUN` for automated and manual evidence;
- relevant entries from [`KNOWN_FAILURES.md`](KNOWN_FAILURES.md).

No production deployment is performed by a coding agent merely because this matrix passes.

## Historical classification examples

| Example | Classes | Flags | Key required evidence |
| --- | --- | --- | --- |
| Add a FastAPI read filter | `pure_software`, possibly `schema_data_contract` if response changes | `public_contract` when documented | API tests, full baseline, compatibility |
| Add telemetry v3 while accepting v1/v2 | `schema_data_contract`, `edge_hardware_integration` | `edge_server_compatibility`, `public_contract` | all-version fixtures through HTTP/MQTT/storage, edge canary plan |
| Change percent to normalized moisture | `schema_data_contract`, `control_guardrails_executor` | `public_contract`, `physical_action` if consumed by control | boundary/range replay, all consumers, fail-safe simulation |
| Harden MQTT reconnect | `pure_software`, `edge_hardware_integration` | `production_availability` | disconnect/backoff/recovery tests, worker health and rehearsal plan |
| Add an Alembic migration | `schema_data_contract`, `infrastructure_deployment` | `data_loss_migration`, `production_availability` | isolated upgrade/restore, old data, backup/rollback/readiness |
| Change Compose healthcheck | `infrastructure_deployment` | `production_availability` | rendered config, start/failure/recovery health, rollback rehearsal |
| Change State Estimator thresholds | `pure_software`, `control_guardrails_executor` | `public_contract` if outputs change | deterministic fixture replay, stale/impossible inputs, dashboard consumer |
| Add Executor retry logic | `control_guardrails_executor`, `edge_hardware_integration` | `physical_action`, `production_availability` | fake adapter duplicate/timeout/restart/late-ACK/storage-failure tests, supervised plan |
| Change Ollama structured output | `llm_vision`, possibly `schema_data_contract` | `public_contract` if exposed | malformed/extra/reasoning/timeout/unavailable/privacy tests |
| Edit the Raspberry Pi camera runbook | `documentation_only` | none unless procedure can affect production/hardware | link/command verification and manual procedure walkthrough |

## Role guidance

- **Planner:** classify by changed behavior, set all risk flags, list consumers and `SP-FAIL-*`, and put exact required/manual commands and rollback in the approved brief.
- **Coder:** implement required failure-path tests, use only fake/simulation hardware, run selected checks, and report manual checks honestly as pending.
- **Reviewer:** reclassify independently; reject missing consumers, risk flags, rollback, failure injection, manual evidence, or accidental production/export reachability.
