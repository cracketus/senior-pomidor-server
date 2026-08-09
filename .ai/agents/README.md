# Agent roles

All roles start with root [`AGENTS.md`](../../AGENTS.md), [`CORE_INVARIANTS.md`](../CORE_INVARIANTS.md),
and the deterministic packet selected by `python -m tools.agent_context`. Use `--full` when proposed
paths are unknown or for a legacy full-pack integration during the one-release-cycle transition.

## Feature Planner

[`feature-planner.md`](feature-planner.md) is read-only, applies the matching workflow under
[`../workflows/`](../workflows/README.md), and returns only a draft Implementation Brief plus evidence.
Its ten frozen evaluation cases are under [`../evaluations/feature-planner/`](../evaluations/feature-planner/README.md).

## Coding Agent

[`coding-agent.md`](coding-agent.md) implements one approved brief and returns the mandatory
[Implementation Report](../templates/implementation-report.md). Agent-created branches/worktrees and
Compose mutation use the [isolated task workflow](../../docs/AGENT_TASK_WORKFLOW.md).

## Reviewer

[`reviewer.md`](reviewer.md) independently reviews the brief, diff, report, and evidence without editing
code. It returns the strict [Review Report](../templates/review-report.md). Reviewer v1 remains
byte-stable because the published oracle-blind run is bound to its exact hash; compact routing reduces
the surrounding packet without rewriting that evaluated instruction. A future Reviewer instruction
change requires a new independent oracle-blind run before its metrics can replace the baseline.

No role authorizes production deployment, production data/secrets access, or real hardware activation.
