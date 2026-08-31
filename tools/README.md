# Repository tools

This directory contains local developer, agent-harness, operations, validation, staging, and research utilities for Senior Pomidor Core.

Run Python tools from the repository root with the project environment activated. The repository requires Python 3.12+.

```bash
python -m tools.<module> --help
```

When a tool exposes `--help`, treat that output and the implementation itself as the source of truth for flags. Operational runbooks under `docs/` may impose additional preconditions that are intentionally not duplicated here.

## Safety and side effects

Not every script is read-only. Before running an unfamiliar tool, check its section below and its `--help` output.

- **Read/inspect** tools generally query files, configuration, databases, or local services and print a report.
- **Local-write** tools may write reports, caches, audit records, generated documentation, or backup artifacts.
- **Operational** tools may start/stop isolated Compose services, create Git branches/worktrees, create commits, or exercise staging infrastructure.
- Production deployment, destructive production changes, and physical hardware authority remain outside these utilities unless an explicit human-owned runbook says otherwise.

## Agent harness and AI development workflow

### `agent_task.py`

Creates and manages isolated coding-agent tasks: branches/worktrees, generated local environment, bounded Compose actions, fixed checks, cleanup, and retirement.

Typical workflow:

```bash
python -m tools.agent_task preflight
python -m tools.agent_task create --issue 276 --slug codex-traces --kind feature
python -m tools.agent_task inspect 276-codex-traces
python -m tools.agent_task compose 276-codex-traces config
python -m tools.agent_task cleanup 276-codex-traces
python -m tools.agent_task retire 276-codex-traces
```

Use `python -m tools.agent_task --help` and the subcommand help for the full command set. See `docs/AGENT_TASK_WORKFLOW.md` for the isolation and safety contract.

### `validate_change.py`

Plans, runs, caches, and records deterministic validation selected from the repository test/risk matrix for an active agent task.

```bash
python -m tools.validate_change --base main --task-key <task-key> --explain
```

Use `--force full` only when the heavier validation path is intended.

### `agent_context.py`

Selects a deterministic, read-only context pack for a planner, coder, or reviewer from changed files, task classes, risk flags, known failures, and the test matrix.

```bash
python -m tools.agent_context \
  --role coder \
  --changed-files app/example.py tests/test_example.py

python -m tools.agent_context \
  --role reviewer \
  --changed-files app/example.py \
  --format json
```

### `agent_maturity.py`

Calculates the required agent maturity level from task classes and risk flags. It is also imported by validation code for maturity-gate decisions.

```bash
python -m tools.agent_maturity --help
```

The CLI reports the required level only; it does not grant authority.

### `agent_audit.py`

Validates sanitized `agent_run_v1` records and aggregates bounded run metrics. It can also produce a monthly retrospective.

```bash
python -m tools.agent_audit .ai/agent-runs/<run>.json
python -m tools.agent_audit .ai/agent-runs/*.json --month 2026-08
```

Raw prompts, secrets, environment dumps, and unrestricted tool output are intentionally outside this audit format.

### `agent_usage.py`

Appends a privacy-safe local aggregate usage record for planner/coder/reviewer runs.

```bash
python -m tools.agent_usage --help
```

The tool records bounded counts and elapsed time rather than raw model input/output.

### `model_routing.py`

Selects a deterministic model tier for a known operation based on configured risk/escalation signals. It does **not** invoke a model.

```bash
python -m tools.model_routing --help
```

### `tool_routing.py`

Selects the configured tool/connector for a known operation without catalog discovery, including the configured fallback path after a recorded connector failure.

```bash
python -m tools.tool_routing --help
```

### `evaluate_feature_planner.py`

Validates and scores the checked-in Feature Planner evaluation suite and its revision results.

```bash
python -m tools.evaluate_feature_planner
```

This is a deterministic corpus/result validator; it does not call an LLM.

### `evaluate_reviewer.py`

Validates the oracle-blind Reviewer corpus or scores a completed reviewer evaluation run.

```bash
python -m tools.evaluate_reviewer
python -m tools.evaluate_reviewer --run <run-directory>
```

The evaluation enforces explicit BLOCKER/HIGH recall, false-positive, severity, and actionability gates.

### `ai_context_docs.py`

Checks generated summaries in AI-context documentation against their YAML sources.

Check for drift:

```bash
python -m tools.ai_context_docs
```

Rewrite generated sections:

```bash
python -m tools.ai_context_docs --write
```

`--write` modifies tracked documentation.

### `docs_map.py`

Validates `docs-map.yaml` and checks whether supplied source paths are mapped to documentation ownership/coverage entries.

```bash
python -m tools.docs_map --source-path app/example.py
python -m tools.docs_map --source-path app/example.py --report /tmp/docs-map-report.json
```

## Codex trace research

### `find_codex_sessions.py`

Cross-platform discovery utility for finding local Codex rollout/session JSONL files belonging to an arbitrary project. It searches `CODEX_HOME` when set, otherwise `~/.codex`, and can include both active and archived sessions.

The scanner reads only a bounded early portion of each rollout while looking for `session_meta`; it does not load entire potentially very large JSONL files into memory. Damaged or unreadable sessions are reported as warnings instead of aborting the entire scan.

Find by project directory name:

```bash
python -m tools.find_codex_sessions my-project
```

Find by project path:

```bash
python -m tools.find_codex_sessions /home/user/src/my-project
```

Windows:

```powershell
python -m tools.find_codex_sessions C:\work\my-project
```

Return the newest matches as JSON:

```bash
python -m tools.find_codex_sessions my-project --limit 20 --format json
```

Useful options include `--codex-home`, `--match`, `--active-only`, `--ignore-case`, `--format`, `--limit`, and `--fail-on-error`.

Raw Codex rollout files are private research inputs by default. Do not copy them into the repository without explicit sanitization/review.

## Data, backup, and lifecycle

### `backup.py`

Creates or verifies a bounded backup snapshot for the Compose deployment. It captures database and configured persistent artifacts, records checksums/provenance, and supports optional `age` encryption for an environment file.

Create a backup using the default Compose files:

```bash
python -m tools.backup --backup-root backups
```

Verify an existing manifest:

```bash
python -m tools.backup --verify backups/<snapshot>/manifest.json
```

Machine-readable output:

```bash
python -m tools.backup --verify backups/<snapshot>/manifest.json --json
```

This is an operational tool. Review backup/restore documentation before using it against important data.

### `backup_data.ps1`

Windows/PowerShell backup helper for the Docker Compose stack. It produces a timestamped `daily` or `migration` backup directory, PostgreSQL dump/audit/count artifacts, Compose metadata, SHA-256 manifests, and additional Docker-volume archives in migration mode.

```powershell
.\tools\backup_data.ps1
.\tools\backup_data.ps1 -Mode migration -BackupRoot backups -ProjectName senior-pomidor-server
```

The script expects PostgreSQL to be running and contains explicit assumptions about the Compose volume names.

### `lifecycle.py`

Builds a **dry-run** report of data that would be eligible for retention cleanup. It does not perform destructive cleanup.

```bash
python -m tools.lifecycle
python -m tools.lifecycle --telemetry-retention-days 180 --photo-retention-days 180
```

Use `none`, `disabled`, or `off` for retention categories that should not have a cutoff.

### `state_estimator_audit.py`

Summarizes recent persisted State Estimator outputs and active anomalies, including confidence range, selected null rates, and soil-probe value ranges.

```bash
python -m tools.state_estimator_audit
python -m tools.state_estimator_audit --node-id <node-id> --hours 48
```

Requires access to the configured application database.

## Photos, vision, and camera diagnostics

### `analyze_recent_photos.py`

Runs offline VLM analysis over stored project photos, linking them with nearby telemetry before calling a local Ollama vision model. Results are appended to a JSONL output file.

Inspect what would be analyzed without calling Ollama:

```bash
python -m tools.analyze_recent_photos --dry-run --limit 5
```

Run analysis:

```bash
python -m tools.analyze_recent_photos --model <ollama-model> --limit 5
```

Use `--database-url`, `--device-id`, `--since-hours`, `--ollama-host`, and `--output` as needed.

### `check_photo_storage.py`

Cross-checks photo records in the database against files in photo storage and reports missing database-backed files and orphan JPEGs.

```bash
python -m tools.check_photo_storage
python -m tools.check_photo_storage --storage-dir data/photos
```

Returns a non-zero exit code when inconsistencies are found.

### `pi_camera_smoke_test.py`

Raspberry Pi/Linux camera diagnostic. It prints device/environment information, runs `rpicam-hello --list-cameras`, attempts a Picamera2 still capture, and probes `/dev/video0` through OpenCV/V4L2.

```bash
python -m tools.pi_camera_smoke_test
python -m tools.pi_camera_smoke_test --output /tmp/camera-test.jpg --timeout 12
```

This utility is hardware/platform-specific and is not expected to work on ordinary Windows development hosts.

### `test_daily_story_ollama.py`

Manual local experiment for the Daily Story + Ollama path.

```bash
python tools/test_daily_story_ollama.py <MODEL>
```

The script currently contains local test-environment constants (database URL, node ID, prompt paths, Ollama host) and prints context/prompts before the generated story. Review those constants and the privacy implications before running it or sharing its output.

## Edge and integration readiness

### `edge_readiness.py`

Checks whether Core is ready for a Raspberry Pi edge device: API reachability, readiness endpoint, MQTT TCP availability, and writable photo storage.

```bash
python -m tools.edge_readiness
python -m tools.edge_readiness --json
```

Endpoints/paths can be overridden with `--api-base-url`, `--mqtt-host`, `--mqtt-port`, `--photo-storage-dir`, and `--timeout-seconds`.

## Staging and release qualification

### `staging_qualification.py`

Bounded staging qualification controller with named commands for preflight, approved scenarios, soak-check state, and finalization state.

```bash
python -m tools.staging_qualification preflight
python -m tools.staging_qualification scenario <scenario-id>
python -m tools.staging_qualification soak-check
python -m tools.staging_qualification finalize
```

Some scenarios deliberately remain `NOT_RUN` until the required real staging/Edge procedure supplies evidence.

### `staging_overnight_check.sh`

Read-only Linux/Bash soak monitor for the isolated staging deployment. It checks the expected staging topology repeatedly and writes bounded logs/result evidence; it does not restart services, remove containers, or change volumes.

One check cycle:

```bash
bash tools/staging_overnight_check.sh --once
```

Full configured soak:

```bash
bash tools/staging_overnight_check.sh
```

Runtime is controlled through `STAGING_SOAK_*`, `SERVER_ROOT`, `STAGING_ROOT`, and `STAGING_API_BASE_URL`. The script requires the isolated staging env file and validates that it is actually operating in staging mode.

### `release_qualification.py`

Creates and validates bounded release-evidence reports against checked-in JSON schemas and semantic gates.

Inspect commands:

```bash
python -m tools.release_qualification --help
python -m tools.release_qualification validate --help
python -m tools.release_qualification system-invariants --help
```

Examples:

```bash
python -m tools.release_qualification validate \
  --kind release-validation \
  --report <report.json> \
  --require-pass
```

`system-invariants` requires explicit Core/Edge revision and image identity and writes a report to `--output`.

## Public/status tooling

### `public_status.py`

Builds a sanitized Core + Edge status document from local Compose state and the Core API. With no output/publishing options it prints JSON to stdout.

```bash
python -m tools.public_status
python -m tools.public_status --output /tmp/senior-pomidor-status.json
```

It can also update a checked-out Pages/status-data repository and optionally push the resulting commit:

```bash
python -m tools.public_status --pages-repo <checkout> --push
```

`--pages-repo`/`--push` are mutating Git operations; inspect the generated status before enabling publishing.

## Quick discovery

List Python tools:

```bash
python - <<'PY'
from pathlib import Path
for path in sorted(Path('tools').glob('*.py')):
    if path.name != '__init__.py':
        print(path)
PY
```

For a Python CLI that supports argparse, start with:

```bash
python -m tools.<module> --help
```

If a tool is used by a specific runbook or CI workflow, prefer that documented invocation over inventing a new operational sequence.
