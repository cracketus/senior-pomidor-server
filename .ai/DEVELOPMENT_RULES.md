# Development rules

Owner: repository maintainer. Review with CI/tooling changes and quarterly. The root [`AGENTS.md`](../AGENTS.md) is the short router; this file owns workflow detail.

## Before editing

1. Start from an approved issue/Implementation Brief with scope, non-goals, acceptance criteria, rollback, classification, risk flags, affected contracts/consumers, and applicable `SP-FAIL-*` IDs.
2. Inspect the working tree and preserve unrelated user changes. Verify paths and commands against the checkout.
3. Read only the authoritative documents/modules relevant to the classification, then write the selected automated and manual checks into the brief.

## While editing

- Make the smallest coherent change; avoid active-season refactoring outside scope.
- Preserve owner boundaries in [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md).
- Change versioned schemas and all consumers/fixtures/docs together. Never silently reinterpret units or timezone.
- Add failure-path tests, not only happy paths. Convert applicable known failures into automated regression tests or explicit manual evidence.
- Use fakes/simulation for hardware and stub local model responses. Tests must not contact production, activate hardware, or enable external exports.
- Keep secrets and private infrastructure out of diffs and command output. Do not read `.env` unless a specifically authorized task requires it.
- Update [`CURRENT_STATE.md`](CURRENT_STATE.md) only when current deployed/deployable facts change; update [`PROJECT.md`](PROJECT.md) only for stable decisions.
- Coding work follows [`agents/coding-agent.md`](agents/coding-agent.md). Use the isolated
  [`agent task workflow`](../docs/AGENT_TASK_WORKFLOW.md) for agent-created branches/worktrees and
  any Compose mutation. Do not call Docker with arbitrary agent-generated arguments.

## Validation and handoff

- Run every required check selected by canonical [`test-matrix.yaml`](test-matrix.yaml), plus focused tests during iteration.
- For an active isolated task, prefer `python -m tools.validate_change --base <ref> --task-key <key>
  [--explain] [--force full]`; legacy explicit task checks remain supported for one release cycle.
- Report exact commands and outcomes. Label checks `PASS`, `FAIL`, or `NOT RUN` with a reason; never imply manual/physical success from CI.
- Review the final diff for debug artifacts, accidental secrets, unrelated files, contract drift, rollback gaps, and known-failure regressions.
- Reviewer follows [`agents/reviewer.md`](agents/reviewer.md) in a separate read-only session/context,
  reclassifies the change independently, verifies the brief, rules, tests, manual evidence and
  documentation, and returns [`templates/review-report.md`](templates/review-report.md).
- Handoff uses [`templates/implementation-report.md`](templates/implementation-report.md), including
  exact commands, explicit deviations, compatibility/safety impact, and pending manual evidence.

## Context-pack maintenance

| File | Update trigger |
| --- | --- |
| `PROJECT.md`, `ARCHITECTURE_RULES.md`, `SAFETY_RULES.md` | approved stable architecture/safety decision; quarterly verification |
| `CURRENT_STATE.md` | release, topology/contract/subsystem/season/rehearsal change; monthly in active season |
| `known-failures.yaml` | incident or validated resolution; regenerate the compact Markdown index |
| `test-matrix.yaml` | test/CI/risk change; regenerate the Markdown summary |
| `AGENTS.md`, agent/workflow/template files | routing or planning-contract change; keep links and evaluation fixtures synchronized |

Changes to the context pack receive the same review as code. Do not place transient chat context or sensitive operational values in it.
Run `python -m tools.ai_context_docs` to reject generated-summary drift. Legacy full-pack integrations
remain supported for one release cycle through `tools.agent_context --full`.
