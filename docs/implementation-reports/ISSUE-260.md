# Implementation Report: Core RC publication and bounded staging qualification

Issue/brief: #260 / `.ai/implementation-briefs/ISSUE-260-core-release-candidate-and-staging.md`

Agent run ID / audit artifact: `20260828-issue-260-coder` /
`.ai/agent-runs/20260828-issue-260-coder.json`

Branch/worktree: `main` working copy; pre-existing `.agent-clone-225/` preserved unchanged.

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
`edge_hardware_integration`; `security_secrets`, `edge_server_compatibility`,
`production_availability`, `public_contract`.

Applicable failures: `SP-FAIL-001`--`004`, `SP-FAIL-006`, `SP-FAIL-009`--`011`, `SP-FAIL-014`,
`SP-FAIL-015`, `SP-FAIL-017`.

## Implemented behavior

- CI publishes only the full Core SHA tag after `test`, `quality`, `security`, and `docker-e2e`, with
  two platforms, OCI revision, digest verification, and a sanitized RC metadata artifact.
- Staging has fixed named interop/Edge identities, separate operator-provided MQTT credential mounts,
  an ACL example restricted to `senior-pomidor-staging/#`, and export disabled.
- `tools.staging_qualification` exposes only bounded `preflight`, `scenario`, `soak-check`, and
  `finalize` commands; scenario and long-running evidence remain `NOT_RUN` until human staging evidence.
- Release validation accepts `preproduction` and `full`; pre-production requires the first four gates,
  explicitly rejects canary/production PASS, and retains overall report status `NOT_RUN`.

## Files changed and purpose

- `.github/workflows/ci.yml`, `docs/schemas/core-release-candidate-v1.schema.json`: Core RC publication.
- `docker-compose.staging.yml`, `deploy/senior-pomidor-staging.env.example`, `deploy/staging/*`: staging isolation.
- `tools/release_qualification.py`, `tools/staging_qualification.py`: bounded validation/controller.
- `tests/test_release_qualification.py`, `tests/test_staging_environment.py`,
  `tests/test_staging_qualification.py`: mode, isolation, and secret-output failure paths.
- `.ai/implementation-briefs/ISSUE-260-*.md`, `.ai/agent-runs/20260828-*.json`: approved brief/audit.

## Deviations from brief

The real Edge proxy, host, 24-hour staging run, runtime-bundle rehearsal, rollback, canary, and
production observation were not available and remain `NOT_RUN`. No production or physical access was used.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_release_qualification.py tests/test_staging_environment.py tests/test_staging_qualification.py tests/test_compose_config.py tests/test_release_assets.py` | 44 passed. |
| NOT RUN | `python -m pytest -q` | Final full suite pending. |
| NOT RUN | `nox -s lint format_check types security deps_audit` | Pending final verification. |
| NOT RUN | `git diff --check` | Pending final verification. |
| NOT RUN | Docker E2E / Ubuntu staging / 24h soak / rollback | Human-owned and unavailable. |

## Compatibility and safety

Production HTTP, MQTT, storage, health, operator, Grafana, and export contracts are unchanged.
Application-only rollback preserves shared PostgreSQL/Grafana/Ollama and volumes. Compose staging uses
loopback-published ports, separate paths/credentials, fake/synthetic inputs, and disabled external export.

## Manual verification

Human operator must prepare the fixed staging host and Edge container, verify the named network and ACL
files without exposing credentials, run all ten scenarios, continue the exact immutable bundle for 24h,
perform exact-bundle rollback rehearsal, and attach sanitized reports. Status: `NOT_RUN`.

## Final diff review

No production secrets, private paths, raw payloads, GPIO/actuator operations, arbitrary shell execution,
or destructive database/volume operations were added. Unrelated user files were preserved.
