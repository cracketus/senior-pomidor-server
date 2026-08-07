# Feature Planner historical evaluation

This suite evaluates [Feature Planner v1.1](../../agents/feature-planner.md) without giving it post-implementation knowledge. Owner: architecture/development maintainer. Re-run when planner rules, brief contract, architecture rules, known failures, or test matrix materially change.

## Layout

- [`cases.json`](cases.json): ten frozen pre-implementation prompts, allowed evidence, oracle evidence withheld from the planner, and required characteristics.
- [`briefs/`](briefs/): planner outputs from the fixture prompts. Each output is draft-only and must not be treated as authorization.
- [`expected-characteristics.md`](expected-characteristics.md): human scoring guidance derived from later code/incidents/PRs.
- [`results.json`](results.json): criterion-level initial and revision-1 scores, false assumptions, missing questions, and rule refinements.
- [`tools/evaluate_feature_planner.py`](../../../tools/evaluate_feature_planner.py): deterministic structural/scoring gate.

## Repeatable method

1. Freeze the planner version and repository revision under evaluation.
2. For each case, give the planner only `input_prompt` and `planner_available_evidence` from `cases.json`, plus the normal context pack as it would have existed then. Do not expose `oracle_evidence`, expected characteristics, old briefs, or scores.
3. Save the planner's output to the case `brief_path`. The planner may inspect only the declared pre-implementation evidence; unavailable items remain `Unknown`/open questions.
4. After generation, let a human evaluator inspect the oracle evidence and score every rubric criterion 0–2. Record false assumptions and missing questions.
5. Aggregate results with:

   ```powershell
   python -m tools.evaluate_feature_planner
   ```

6. Revise general planner rules, not case-specific filenames/answers. Regenerate all ten briefs from clean fixture inputs, score revision 1, and run the validator plus tests.

## Scoring

Ten criteria score 0–2, maximum 20: task classification, module ownership, contracts/consumers, known failures, test strategy, safety/physical world, rollout/rollback, scope discipline, evidence grounding, and actionable acceptance criteria.

- `0`: absent, unsafe, invented, or materially wrong.
- `1`: partially useful but missing an important consumer/failure/evidence/action.
- `2`: correct, bounded, evidence-grounded, and actionable.

Passing is at least 16/20 (80%). Acceptance requires at least 8 of 10 revision-1 cases to pass, plus the critical gates: Control/Executor mentions Guardrails, idempotency, retry, and simulation; infrastructure includes isolated rehearsal and rollback; schema includes compatibility and downstream consumers; no output claims uninspected evidence.

## Revision-cycle result

The initial run exposed weak consumer enumeration, electrical unknowns, restart/uncertain-execution behavior, external-export isolation, and reasoning-leakage checks. Planner v1.1 added cumulative specialized gates, explicit `Unknown` handling, evidence separation, failure injection, manual owners, shadow/abort criteria, and exact output restrictions. All ten revision-1 briefs score at least 16/20; see `results.json` for criterion-level evidence.

## Limitations and human-planning cases

Scores are human judgments over curated historical cases, not proof of production safety. The suite does not execute hardware, validate private infrastructure, verify biological outcomes, or authorize deployment. Human planning/approval remains mandatory for unknown electrical limits, destructive migrations without representative restore evidence, unclear contract ownership, privacy/publication changes, and any physical action with uncertain safe state.
