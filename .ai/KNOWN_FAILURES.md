# Known-failures registry

Owner: the maintainer resolving or reviewing an incident. Add or update an entry in the same change that establishes a root cause or validated resolution; review applicable entries in every Implementation Brief. Never include secrets, private keys, exact addresses, private hostnames, or unsanitized production payloads.

Planner copies applicable `failure_id` values and regression checks into the brief. Coder implements the software checks and records manual checks as `NOT RUN` until a human supplies evidence. Reviewer verifies both the selected IDs and whether a newly discovered incident needs a registry update.

```yaml
failures:
  - failure_id: SP-FAIL-001
    category: infrastructure
    symptom: Compose interpolation fails or services use an empty/unintended image.
    context: Local, CI, or release Compose validation without APP_IMAGE and required environment.
    root_causes: [Required image/environment variables were absent or loaded from the wrong env file.]
    unsafe_or_ineffective_fixes: [Using latest, committing .env, skipping Compose config validation.]
    validated_resolution: [Set a non-secret explicit APP_IMAGE and validate the exact base/overlay/profile combination.]
    regression_checks: [Run Compose config --quiet with CI-safe variables, test missing required variables fail clearly.]
    relevant_workflows: [infrastructure/deployment, release]
    verification: software
    references: [.github/workflows/ci.yml, tests/test_compose_config.py]

  - failure_id: SP-FAIL-002
    category: infrastructure
    symptom: A worker container starts but becomes unhealthy or stops refreshing output.
    context: MQTT, State Estimator, daily-story, or other background worker startup/restart.
    root_causes: [Dependency readiness, migration lag, stale/missing health file, unbounded startup failure.]
    unsafe_or_ineffective_fixes: [Adding restart loops without cause, checking only container running state.]
    validated_resolution: [Gate dependencies, expose bounded worker health, inspect logs and functional output.]
    regression_checks: [Test startup failure and recovery, verify health plus a fresh expected artifact.]
    relevant_workflows: [pure software, infrastructure/deployment]
    verification: software_and_rehearsal
    references: [app/worker_health.py, app/readiness.py, docs/OPERATIONS.md]

  - failure_id: SP-FAIL-003
    category: infrastructure
    symptom: Rehearsal writes to production paths/ports or sends duplicate public metrics.
    context: Migration or release rehearsal with Compose profiles.
    root_causes: [Shared project name, mounts, credentials, ports, network, or enabled cloud-export profile.]
    unsafe_or_ineffective_fixes: [Relying on operator memory, starting all profiles, reusing production env.]
    validated_resolution: [Use isolated project/paths/credentials/loopback ports and explicitly disable external export.]
    regression_checks: [Render config and inspect project mounts/ports/profiles; confirm exporter absent and remote writes zero.]
    relevant_workflows: [infrastructure/deployment, rehearsal]
    verification: software_and_manual
    references: [docs/MIGRATION_WINDOWS_TO_UBUNTU.md, docker-compose.dev.yml]

  - failure_id: SP-FAIL-004
    category: infrastructure
    symptom: A rehearsal passes with files/topology that differ from the production release bundle.
    context: Testing from a working tree or ad hoc path, then deploying a separately built artifact.
    root_causes: [Different image digest, override files, release paths, or configuration sources.]
    unsafe_or_ineffective_fixes: [Treating any green local stack as release evidence.]
    validated_resolution: [Rehearse the immutable candidate bundle and compare checksums/image digests/config inputs.]
    regression_checks: [Record candidate digest/checksums before and after rehearsal; validate exact production overlays.]
    relevant_workflows: [infrastructure/deployment, release]
    verification: rehearsal
    references: [deploy/scripts/build-runtime-bundle.sh, docs/MIGRATION_WINDOWS_TO_UBUNTU.md]

  - failure_id: SP-FAIL-005
    category: infrastructure
    symptom: Backup files exist but recovery readiness is unknown or restore fails.
    context: PostgreSQL/photos/private logs/MQTT state backup and migration.
    root_causes: [No isolated restore test, incomplete set, unchecked checksum, incompatible target, missing baseline.]
    unsafe_or_ineffective_fixes: [Counting archive existence as proof, restoring over non-empty production targets.]
    validated_resolution: [Checksummed logical/app-data set, empty isolated target, restore rehearsal, count/hash/API comparison.]
    regression_checks: [Verify SHA256SUMS, restore in isolation, run migrations/readiness, compare counts and representative hashes.]
    relevant_workflows: [data migration, infrastructure/deployment]
    verification: rehearsal_and_manual
    references: [deploy/scripts/restore-migration.sh, docs/UBUNTU_HOST.md, commit:532c53b]

  - failure_id: SP-FAIL-006
    category: edge
    symptom: Edge telemetry/photos disappear after Wi-Fi profile or connectivity loss.
    context: Raspberry Pi boot, AP changes, roaming, or intermittent LAN.
    root_causes: [Missing/wrong profile, radio/network outage, endpoint change, no reconnect/backoff visibility.]
    unsafe_or_ineffective_fixes: [Changing server ingestion before testing link layers, unlimited rapid retries.]
    validated_resolution: [Check link/IP/route/DNS/port/application in order; restore profile and bounded reconnect.]
    regression_checks: [Simulate disconnect/reconnect and queued retry; manually verify profile persistence after reboot.]
    relevant_workflows: [edge/hardware integration]
    verification: software_and_manual
    references: [docs/NETWORK.md, docs/PI_INTEGRATION_RUNBOOK.md, tests/test_mqtt_worker.py]

  - failure_id: SP-FAIL-007
    category: edge
    symptom: Raspberry Pi storage becomes read-only, disappears, or fails under heat.
    context: SD-card/slot exposed to sustained temperature or mechanical stress.
    root_causes: [Physical SD slot/card/contact failure or thermal/power conditions.]
    unsafe_or_ineffective_fixes: [Repeated filesystem writes, reimaging without inspecting hardware, claiming CI coverage.]
    validated_resolution: [Power down safely; inspect slot/card/power/temperature; replace hardware and verify storage.]
    regression_checks: [Manual cold/thermal inspection, boot/storage read-write test, monitor temperature and filesystem errors.]
    relevant_workflows: [edge/hardware integration, incident]
    verification: manual_physical
    references: [docs/CAPACITY_PLANNING.md]

  - failure_id: SP-FAIL-008
    category: edge
    symptom: Camera times out, is absent, or flickers/corrupts frames on a long cable.
    context: CSI/USB capture, boot detection, cable routing, or power variation.
    root_causes: [Loose/damaged cable, excessive cable length/interference, device conflict, driver/power issue.]
    unsafe_or_ineffective_fixes: [Increasing timeout indefinitely, treating one successful frame as stability.]
    validated_resolution: [Inspect/detect device, isolate cable/power/driver, run repeated bounded capture smoke test.]
    regression_checks: [Fake missing-device/timeout tests; manual repeated captures and visual flicker review on target hardware.]
    relevant_workflows: [edge/hardware integration, LLM/vision]
    verification: software_and_manual_physical
    references: [tools/pi_camera_smoke_test.py, docs/PI_INTEGRATION_RUNBOOK.md]

  - failure_id: SP-FAIL-009
    category: schema
    symptom: A consumer expects flat state fields while producer emits nested canonical state, or vice versa.
    context: State/API/storage/dashboard/fixture integration.
    root_causes: [Unversioned shape assumption, adapter bypass, stale fixture/query.]
    unsafe_or_ineffective_fixes: [Supporting ambiguous shapes silently everywhere, dashboard-only field aliases.]
    validated_resolution: [Name/version the shape and convert at one owned adapter boundary; update all consumers.]
    regression_checks: [Schema validation, round-trip, old-fixture replay, API/storage/dashboard consumer tests.]
    relevant_workflows: [schema/data contract, state estimator]
    verification: software
    references: [docs/CONTRACTS.md, app/state_estimator/adapters.py, tests/state_estimator]

  - failure_id: SP-FAIL-010
    category: schema
    symptom: Moisture/humidity/confidence thresholds are off by a factor of 100.
    context: Percent values (0..100) cross a boundary expecting normalized ratios (0..1).
    root_causes: [Unit omitted from name/schema, implicit conversion, reused threshold.]
    unsafe_or_ineffective_fixes: [Clamping until tests pass, undocumented heuristic detection.]
    validated_resolution: [Use unit-bearing names/ranges and an explicit tested conversion at the owner boundary.]
    regression_checks: [Boundary/property cases at 0, 1, 50, 100 and out-of-range rejection; fixture replay.]
    relevant_workflows: [schema/data contract, control/guardrails/executor]
    verification: software
    references: [docs/CONTRACTS.md, config/state_estimator_v1.yaml, tests/test_contract_fixtures.py]

  - failure_id: SP-FAIL-011
    category: testing
    symptom: Contract fixtures pass validators but fail through the real HTTP/MQTT execution path.
    context: Hand-maintained fixtures or tests calling an internal helper only.
    root_causes: [Fixture drift, transport normalization/auth/topic/storage path omitted.]
    unsafe_or_ineffective_fixes: [Changing only expected data, mocking the unit under test end to end.]
    validated_resolution: [Replay versioned fixtures through public ingestion boundaries and downstream persistence/read paths.]
    regression_checks: [Run contract, edge-integration, API, MQTT, and opt-in Docker E2E tests.]
    relevant_workflows: [schema/data contract, edge/hardware integration]
    verification: software
    references: [tests/test_contract_fixtures.py, tests/test_edge_integration_fixtures.py, tests/test_docker_e2e.py]

  - failure_id: SP-FAIL-012
    category: llm
    symptom: Model returns malformed JSON, extra prose, schema-grammar errors, or an overlong response.
    context: Ollama/LLM/VLM structured analysis or assistant output.
    root_causes: [Unsupported schema grammar, weak output boundary, model/runtime mismatch, unchecked response.]
    unsafe_or_ineffective_fixes: [Parsing with eval, trusting markdown fences, retrying an invalid request unchanged.]
    validated_resolution: [Use a minimal supported schema, bounded output/time, strict parsing plus semantic validation, safe unavailable result.]
    regression_checks: [Malformed/truncated JSON, extra prose, unsupported schema, timeout, unavailable model, oversized response.]
    relevant_workflows: [LLM/vision]
    verification: software
    references: [app/ollama.py, tests/test_ollama.py, docs/OLLAMA_TROUBLESHOOTING.md]

  - failure_id: SP-FAIL-013
    category: llm
    symptom: Hidden reasoning or prompt internals appear in user-visible/persisted final output.
    context: Thinking-capable local/remote model and diary/assistant/analysis surfaces.
    root_causes: [Provider response fields conflated, delimiter leakage, raw response published.]
    unsafe_or_ineffective_fixes: [Regex-only secret scrubbing after publication, logging full raw prompts by default.]
    validated_resolution: [Map only the validated final field into the public contract and keep bounded diagnostics private.]
    regression_checks: [Responses containing reasoning/final fields, tags, extra prose, prompt echoes; assert public serialization excludes them.]
    relevant_workflows: [LLM/vision, public contract]
    verification: software
    references: [app/ollama.py, app/daily_story.py, tests/test_daily_story.py]

  - failure_id: SP-FAIL-014
    category: testing
    symptom: Pytest passes on Linux but fails on Windows around temp cleanup, open files, or path semantics.
    context: Filesystem/temp tests under Windows file locking and path rules.
    root_causes: [Unclosed handles, NamedTemporaryFile assumptions, permissions/path separator differences.]
    unsafe_or_ineffective_fixes: [Skipping all Windows tests, retrying cleanup without closing resources.]
    validated_resolution: [Close resources before cleanup, use pytest tmp_path, keep paths platform-neutral.]
    regression_checks: [Run focused filesystem tests on Windows and Linux; assert cleanup after explicit close.]
    relevant_workflows: [pure software, testing]
    verification: software_cross_platform
    references: [pyproject.toml, .github/workflows/ci.yml]

  - failure_id: SP-FAIL-015
    category: testing
    symptom: Editable install/build reports multiple top-level packages or omits application modules.
    context: Adding root directories/packages or changing setuptools discovery.
    root_causes: [Implicit flat-layout discovery captured data/tool directories.]
    unsafe_or_ineffective_fixes: [Deleting unrelated directories, broad wildcard package inclusion.]
    validated_resolution: [Explicitly include only app packages and verify build/import from a clean environment.]
    regression_checks: [python -m pip install -e . in clean env, import app, inspect wheel contents when packaging changes.]
    relevant_workflows: [pure software, packaging]
    verification: software
    references: [pyproject.toml, commit:bc16f24]

  - failure_id: SP-FAIL-016
    category: security
    symptom: SSH authentication is broken or private key material is exposed via authorized_keys/source/logs.
    context: Host provisioning or manual SSH key installation.
    root_causes: [Private key confused with public .pub key, unsafe copy/paste or permissions.]
    unsafe_or_ineffective_fixes: [Committing/redacting after exposure only, printing keys for diagnosis.]
    validated_resolution: [Remove exposed material, rotate the key, install only verified public key, fix permissions.]
    regression_checks: [Manual fingerprint/type check without displaying key; secret scan; verify authorized_keys contains public formats only.]
    relevant_workflows: [security/secrets, infrastructure/deployment]
    verification: manual_security
    references: [docs/UBUNTU_HOST.md, deploy/scripts/provision-host.sh]

  - failure_id: SP-FAIL-017
    category: infrastructure
    symptom: Router/switch/Wi-Fi symptoms are misdiagnosed as an application defect or vice versa.
    context: Edge cannot reach MQTT/HTTP or traffic is intermittent.
    root_causes: [Only one layer tested, stale DHCP/ARP/DNS, VLAN/firewall/port/link issue, service not listening.]
    unsafe_or_ineffective_fixes: [Reinstalling application immediately, widening firewall/public exposure.]
    validated_resolution: [Test physical link, interface/IP, route, name resolution, TCP port, protocol, then application health/logs.]
    regression_checks: [Record layer-by-layer evidence; simulate refused/timeout/disconnect; manually verify switch/router state.]
    relevant_workflows: [edge/hardware integration, infrastructure/deployment, incident]
    verification: software_and_manual
    references: [docs/NETWORK.md, tools/edge_readiness.py, docs/PI_INTEGRATION_RUNBOOK.md]
```

## Contribution rules

- IDs are permanent and never reused. Add the next number; mark superseded guidance explicitly rather than deleting history.
- `validated_resolution` means observed to work, not merely proposed. Unresolved items state that no validated resolution exists.
- Every entry has at least one repeatable regression check and a verification mode. Physical/manual modes can never be closed by CI evidence alone.
- References use repository-relative paths, issue/PR numbers, or commit IDs; link sensitive evidence only from an approved private incident system, never copy it here.
