# Senior Pomidor agent router

Start every planning, implementation, or review task with
[`.ai/CORE_INVARIANTS.md`](.ai/CORE_INVARIANTS.md). Select the remaining context from the canonical
[manifest](.ai/context-manifest.yaml):

```text
python -m tools.agent_context --role <planner|coder|reviewer> --changed-files <file...>
```

Read every selected file and full selected `SP-FAIL-*` record. Use `--full` when changed paths are not
known or while an older integration is in its one-release-cycle transition. Unknown paths and every
risk flag fail safe to the full architecture/safety pack.

Work only from an approved Implementation Brief: an accepted issue with explicit scope and acceptance
criteria, or a human-approved copy of [`.ai/templates/implementation-brief.md`](.ai/templates/implementation-brief.md).
Use the read-only [Feature Planner](.ai/agents/feature-planner.md) and matching workflow when planning is
needed. Record selected task classes, risk flags, known failures, checks, consumers, and rollback before
implementation.

Approved implementation follows the [Coding Agent](.ai/agents/coding-agent.md), uses the
[isolated task workflow](docs/AGENT_TASK_WORKFLOW.md) for agent-created branches/worktrees or Compose
mutation, and returns [`.ai/templates/implementation-report.md`](.ai/templates/implementation-report.md).
Independent review uses [Reviewer](.ai/agents/reviewer.md) in a separate context and returns
[`.ai/templates/review-report.md`](.ai/templates/review-report.md).

Run the checks selected by canonical [`.ai/test-matrix.yaml`](.ai/test-matrix.yaml). Generated Markdown
summaries are navigation aids, not independent routing sources. Record automated and manual evidence as
`PASS`, `FAIL`, or `NOT_RUN`; CI never proves a physical-world outcome.

Prohibited: production deployment or writes; reading or exposing production secrets/private
infrastructure; real GPIO/actuator use; bypassing Guardrails or Executor; direct LLM-to-actuator paths;
destructive database/volume operations; external export in rehearsal; or unapproved contract breaks.
Active-season reliability and data preservation take priority; keep scope narrow and reversible.
