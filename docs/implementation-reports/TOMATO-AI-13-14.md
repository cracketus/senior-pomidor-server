# Implementation Report: Agent audit evidence and maturity gates

Issue/brief: TOMATO-AI-13 / TOMATO-AI-14; `.ai/implementation-briefs/TOMATO-AI-13-14.md`

Task classes and risk flags: `pure_software`; `security_secrets` for redaction review.

## Implemented behavior

- Added strict `agent_run_v1` validation, bounded metrics, monthly retrospective output, and pilots.
- Added levels 1–4 policy, required level mapping, fail-closed evidence/approval gates, and downgrade triggers.
- Integrated maturity validation into `validate_change` for audit/maturity diffs.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q -p no:cacheprovider --basetemp .pytest-temp-tomato-ai-final tests/test_agent_audit.py tests/test_agent_maturity.py tests/test_validate_change.py` | 12 passed |
| PASS | `python -m pytest -q` | 277 passed, 1 skipped before final audit-validation hardening; final focused replay passed |
| NOT RUN | `nox -s lint format_check types` | Timed out twice during environment/session bootstrap; direct ruff checks passed |
| PASS | `ruff check` / `ruff format --check` (changed files) | Passed |
| PASS | `git diff --check` | No whitespace errors |
| PASS | `bandit -q -r tools/agent_audit.py tools/agent_maturity.py` | Passed |
| NOT RUN | Manual privacy review of pilot artifacts | Human review required |

## Safety impact

No runtime, database, Compose, production, secret, external-export, Guardrails/Executor, or hardware
path is changed. Merge, deployment, and physical enablement remain human-only.

## Known limitations

Level 3/4 manual compatibility, rehearsal, deterministic replay, and physical evidence are not
proved by CI and remain `NOT_RUN` until a human records them.
