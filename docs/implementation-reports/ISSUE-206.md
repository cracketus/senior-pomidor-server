# Implementation Report: `pomidorctl` read-only CLI

Issue/brief: #206 / `.ai/planning/implementation-brief-206.md`

Agent run ID / audit artifact: `20260911-issue-206-coder` / `.ai/agent-runs/20260911-issue-206-coder.json`

Branch/worktree: current checkout; unrelated untracked briefs preserved.

Task classes and risk flags: `pure_software`, `schema_data_contract`; `security_secrets`, `public_contract`.

Applicable failures: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`, `SP-FAIL-015`.

## Implemented behavior

Added the `pomidorctl` and `python -m app.pomidorctl` entry points for status, plants, edge, anomalies,
decisions, and photos. The client sends only bounded GET requests, disables redirects/retries, enforces
timeout and response-size limits, validates the existing Pydantic operator models, preserves successful
JSON structure, and maps canonical status/error classes to documented exit codes. Token sources and
diagnostics are bounded and secret-safe.

Review follow-up: API storage failures now use the distinct `senior-pomidor.operator-error.v1` contract;
environment tokens share the 8 KiB byte bound with token files; and response bodies are consumed through
streaming bounded reads before being assembled for JSON validation. Persisted state quality labels are
also cross-checked against canonical confidence thresholds; contradictory quality data projects to UNKNOWN.
Operator API routes emit bounded structured request metadata (view, request ID, status, freshness,
completeness, and elapsed milliseconds) without credentials or raw payloads.

## Tests and evidence

| Status | Command | Result |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_pomidorctl.py tests/test_operator_summary.py tests/test_contract_fixtures.py -p no:cacheprovider` | Focused contract/client/boundary tests passed |
| PASS | `python -m app.pomidorctl --help` | Both command surface and help render |
| PASS | `ruff check app/pomidorctl tests/test_pomidorctl.py` | No focused lint findings |
| PASS | `ruff format --check app/pomidorctl tests/test_pomidorctl.py` | 8 files already formatted |
| PASS | `python -m pytest -q -p no:cacheprovider` | 650 passed, 12 skipped |
| PASS | `python -m pytest -q tests/test_operator_summary.py tests/test_api.py -p no:cacheprovider` | 82 passed; bounded operator request logging covered |
| PASS | `python -m mypy app/pomidorctl` | No issues in 7 source files |
| NOT RUN | `nox -s lint format_check types` | Environment creation stalled at editable dependency installation; stopped safely |
| PASS | `bandit -c pyproject.toml -r app tools` | No issues identified |
| FAIL | `pip-audit --skip-editable --cache-dir .pip-audit-cache` | Baseline reports 56 known vulnerabilities in 13 packages; remediation is outside this CLI patch |
| PASS | `git diff --check` | No whitespace errors |
| PASS | `python -c "...setuptools.build_meta.build_wheel..."` | Wheel contains `app/pomidorctl/cli.py` and `pomidorctl = app.pomidorctl.cli:main` |
| PASS | `python -m pytest -q tests/test_pomidorctl.py -p no:cacheprovider` | FastAPI boundary → validated CLI client replay included; 14 passed |
| PASS | Windows token-file/config and subprocess-style CLI tests | Current Windows environment passed |
| NOT RUN | Linux token-file/subprocess matrix | Linux runner unavailable in this workspace |
| NOT RUN | `edge_canary`, production auth/data, physical evidence | Out of scope and not authorized |

## Compatibility and safety

Changes are additive: existing APIs, schemas, storage, Edge contracts, Control, Guardrails, Executor,
GPIO, and exports are untouched. Rollback is removal of the additive package/console entry point or
reversion of the application image/venv; no database or shared-volume operation is needed. The remaining
manual evidence is explicitly `NOT_RUN`.
