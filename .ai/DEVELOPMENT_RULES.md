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

## Validation and handoff

- Run every required check selected by [`TEST_MATRIX.md`](TEST_MATRIX.md), plus focused tests during iteration.
- Report exact commands and outcomes. Label checks `PASS`, `FAIL`, or `NOT RUN` with a reason; never imply manual/physical success from CI.
- Review the final diff for debug artifacts, accidental secrets, unrelated files, contract drift, rollback gaps, and known-failure regressions.
- Reviewer reclassifies the change independently and verifies the brief, rules, tests, manual evidence, and documentation are consistent.

## Context-pack maintenance

| File | Update trigger |
| --- | --- |
| `PROJECT.md`, `ARCHITECTURE_RULES.md`, `SAFETY_RULES.md` | approved stable architecture/safety decision; quarterly verification |
| `CURRENT_STATE.md` | release, topology/contract/subsystem/season/rehearsal change; monthly in active season |
| `KNOWN_FAILURES.md` | incident or newly validated resolution; review during each related brief |
| `TEST_MATRIX.md` and YAML | test/CI/risk change; keep both representations in the same change |
| `AGENTS.md`, agent/workflow/template files | routing or planning-contract change; keep links and evaluation fixtures synchronized |

Changes to the context pack receive the same review as code. Do not place transient chat context or sensitive operational values in it.
