# AI workflow acceptance replay results

Status: `PASS`

Issue: [#168](https://github.com/cracketus/senior-pomidor-server/issues/168)

Source revision: `152ed213f217743269c2a212138df74ab4d40e4a`

Replay task: `tomato-ai-42-acceptance-replay-v2`

Environment: Windows NT `10.0.26200.0`, Python `3.13.6`

Replay mode: deterministic evidence only; no fresh model-provider calls

## Result summary

| Gate | Status | Evidence |
| --- | --- | --- |
| Context reduction | PASS | 23,326 characters versus the frozen 73,925-character baseline: 68.45% reduction, above the 35% requirement. |
| Selected-context catalog exclusion | PASS | The compact context contains three selected files and no `ALL_TOOLS` or Reviewer run artifacts. |
| Replay-window catalog discovery | PASS | The clean replay-v2 window used known deterministic commands directly and performed no tool-catalog lookup. |
| Feature Planner evaluation | PASS | 10/10 revision cases scored at least 16/20; minimum score 18/20. |
| Frozen Reviewer evaluation | PASS | BLOCKER recall 100%; HIGH recall 100%; false positives 5%; severity agreement 95%; actionable quality 90%. |
| Model routing | PASS | Focused tests verify bounded script/light/medium tiers and strong escalation for every configured high-risk condition. |
| Compact sub-agent policy | PASS | `fork_turns=none`, compact JSON packets, structured JSON output, batching, and no one-agent-per-case policy. |
| GitHub tool-routing contract | PASS | Focused tests require direct connector routing without discovery and permit `gh` only after recorded connector failure. |
| Focused replay tests | PASS | 28 tests passed in 4.69s. |
| Full pytest | PASS | 257 passed and 1 skipped in 38.92s on the first final validation invocation. |
| Full pytest execution count | PASS | The full suite executed exactly once for the final relevant diff. |
| Quality | PASS | Shared lint, format, and type environments completed successfully in 20s without installation. |
| Quality execution count | PASS | Quality executed exactly once for the final relevant diff. |
| Validation cache reuse | PASS | The second invocation reused full pytest and quality evidence without executing either command. |
| Validation artifact | PASS | Atomic `validation.json` records the final PASS/NOT_RUN evidence and cache reasons. |
| Compose exclusion | PASS | `compose_config` was not selected and no local Compose command executed. |
| Live model/provider behavior | NOT_RUN | Deterministic mode intentionally made no fresh model calls. Static routing evidence is not presented as live-provider evidence. |
| Production, hardware, secrets, and external export | NOT_RUN | These systems were outside the approved scope and were not accessed. |

## Context replay

The replay used the frozen `reviewer_129_130_session` case from
`.ai/evaluations/context-router/replay-v1.yaml`:

```text
legacy full context: 73,925 characters
selected context:    23,326 characters
removed:             50,599 characters
reduction:           68.45%
selected files:      3
full context:        false
risk flags:          none
```

The selected files were `.ai/CORE_INVARIANTS.md`, `.ai/DEVELOPMENT_RULES.md`, and
`.ai/agents/reviewer.md`. The selected complete known-failure records were `SP-FAIL-014` and
`SP-FAIL-015`.

## Evaluation replay

The following deterministic commands passed:

```text
python -m pytest -q -p no:cacheprovider --basetemp E:\MyProjects\senior-pomidor-server\.agent-validation-tmp-replay-v2\focused-2 tests/test_agent_context.py tests/test_model_routing.py tests/test_tool_routing.py tests/test_validate_change.py
28 passed in 4.69s

python -m tools.evaluate_feature_planner
Feature Planner evaluation PASS: 10/10 revision cases >=16/20; minimum score 18/20.

python -m tools.evaluate_reviewer --run .ai/evaluations/reviewer/runs/20260809-9302afb-oracle-blind-09
Reviewer run PASS: BLOCKER 100%; HIGH 100%; false positives 5%; severity 95%; actionable 90%.
```

An earlier preflight invocation supplied a `--basetemp` whose parent did not exist, so pytest could not
start five temp-dependent tests. The ignored parent was created and the measured focused replay used a
new path. This was a command-setup correction, not a retry of a failed behavioral assertion.

The Reviewer command names the immutable run explicitly. The command without `--run` validates only the
corpus and is not accepted as published-run evidence.

## Validation orchestration

The final orchestration command was invoked twice:

```text
python -m tools.validate_change --base origin/main --task-key tomato-ai-42-acceptance-replay-v2 --explain --force full
```

The first invocation produced:

```text
full_pytest: PASS
257 passed, 1 skipped in 38.92s
basetemp: E:\MyProjects\senior-pomidor-server\.agent-validation-tmp-d6a265377c0e\8141729a742f

quality: PASS
shared envdir: E:\MyProjects\senior-pomidor-server\.nox
install step: skipped
lint, format_check, types: PASS in 20s

diff_check: PASS
compose_config: NOT_RUN (not selected)
validation.json: published atomically
```

The second invocation reported `cached_identical_relevant_diff_command_environment_and_config` for
full pytest and quality. No second pytest or nox process was started. Diff check ran again because the
report evidence changed and passed. Validator-managed `focused_tests` was `NOT_RUN` because the
report-only diff changed no test file; the separate 28-test focused replay above provides the required
focused evidence.

## Previous replay and remediation

The first replay remains preserved in [PR #169](https://github.com/cracketus/senior-pomidor-server/pull/169)
with status `FAIL`. It found Windows nested-worktree path overflow, ineffective nox reuse, and a session
catalog lookup. [PR #171](https://github.com/cracketus/senior-pomidor-server/pull/171) fixed the validation
path and environment-reuse defects. Replay v2 does not rewrite the historical result; it records new
evidence against the merged remediation revision.

## Evidence boundary

This replay validates deterministic repository behavior and the frozen Reviewer evidence. It does not
validate current model-provider availability, prompt/output volume from a fresh Reviewer run, physical
outcomes, production availability, secrets, Docker infrastructure, or external exports. Those items
remain `NOT_RUN` rather than being inferred from automated checks.

Rollback is a revert of this report-only commit. No runtime contract, durable data, deployment state,
or production topology changes.
