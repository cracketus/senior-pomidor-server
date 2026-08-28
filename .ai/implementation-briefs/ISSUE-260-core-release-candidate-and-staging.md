# Implementation Brief: Core RC publication and bounded staging qualification

Status: approved

Planner/version: human-approved continuation of the #225 qualification plan / v1

Approver/date: user / 2026-08-28

Issue/decision: #260, absorbing the remaining server scope from #248 and #250

Agent run ID / audit artifact: `20260828-issue-260-coder` /
`.ai/agent-runs/20260828-issue-260-coder.json`

## Problem

PR #268 supplies the report contracts and an isolated staging overlay, but the Core image is not
published as a verified SHA-only multi-platform release candidate, staging has no explicit Edge
interop/credential boundary, and qualification tooling cannot run bounded scenario/soak/finalize
operations. The release validator also has no pre-production mode: it cannot require the four
pre-production gates while explicitly keeping canary and production NOT_RUN.

## Scope and acceptance criteria

- Publish a SHA-only Core GHCR image after the `main` CI gates for `linux/amd64` and `linux/arm64`,
  with the full SHA as OCI revision, and upload a sanitized `senior-pomidor.core.release-candidate.v1`
  artifact containing SHA, digest, immutable ref, platforms, and workflow reference.
- Extend staging with a named interop network, fixed Edge container connection checks, operator-provided
  Mosquitto password/ACL files scoped to `senior-pomidor-staging/#`, and disabled external export.
- Add `tools/staging_qualification.py` with only `preflight`, `scenario`, `soak-check`, and `finalize`
  commands and fixed staging resources; it must reject arbitrary commands and never print secrets.
- Add `preproduction|full` release validation. Pre-production requires software CI, Docker E2E,
  24-hour cross-repository staging, and exact-bundle rehearsal PASS; canary/production remain NOT_RUN
  and the release report remains NOT_RUN. Full retains all-six-gates PASS semantics.
- Preserve production API, telemetry/storage/health/operator contracts and application-only rollback.

## Classification, risks, failures, consumers, rollback, checks

Task classes: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
`edge_hardware_integration`. Risk flags: `security_secrets`, `edge_server_compatibility`,
`production_availability`, `public_contract`. Applicable failures: `SP-FAIL-001`--`004`,
`SP-FAIL-006`, `SP-FAIL-009`--`011`, `SP-FAIL-014`, `SP-FAIL-015`, `SP-FAIL-017`.

Consumers are CI/release workflows, the staging operator, Edge #103, the three existing evidence
contracts, and the release owner. Required checks are focused tests, full pytest, quality, security,
dependency audit, diff check, exact Compose rendering, schema/round-trip/fixture replay, named
consumers and edge failure paths. Manual staging, 24-hour soak, exact-bundle rehearsal, rollback,
canary and production remain `NOT_RUN` until a human runs them on the approved host. Software rollback
is revert; runtime rollback uses the previous immutable application image and preserves shared data.

## Out of scope

Production deployment/writes, production secrets, external export, GPIO/actuators, destructive
database/volume operations, Edge repository changes, and changes to production contracts.

Approval does not authorize production access, secrets, or physical-world activation.
