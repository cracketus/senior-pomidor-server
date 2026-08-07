# Agent roles

## Feature Planner

[`feature-planner.md`](feature-planner.md) is the read-only planning role. Invoke it manually with a request such as:

```text
Act as the Senior Pomidor Feature Planner. Read AGENTS.md and the complete context pack,
then apply .ai/workflows/<workflow>.md to this request: <request>.
Inspect only relevant evidence, do not edit files or implement code, and return only a draft
Implementation Brief plus its compact evidence/reference list. Mark unknown facts explicitly.
```

Select `feature`, `bugfix`, `incident-fix`, `schema-change`, `infrastructure-change`, or `hardware-integration`. Apply multiple workflows when classifications overlap. The output remains draft until human approval and does not authorize production/hardware actions.

Ten example outputs across feature, incident, infrastructure, schema, hardware, control and LLM categories are in [`../evaluations/feature-planner/briefs/`](../evaluations/feature-planner/briefs/). They are evaluation fixtures, not approved work orders.

Coding Agent and Reviewer role prompts remain reserved for separately approved work. All roles still follow root [`AGENTS.md`](../../AGENTS.md) and the context pack.
