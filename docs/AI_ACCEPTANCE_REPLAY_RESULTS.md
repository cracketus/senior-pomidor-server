# AI workflow acceptance replay results

Status: `FAIL`

Issue: [#168](https://github.com/cracketus/senior-pomidor-server/issues/168)

Base revision: `a96caa1922afd29e569f245d8d22be43b3b580a1`

Task: `tomato-ai-42-acceptance-replay`

Environment: Windows NT `10.0.26200.0`, Python `3.13.6`

Replay mode: deterministic evidence only

## Result summary

| Gate | Status | Evidence |
| --- | --- | --- |
| Context reduction | PASS | 23,326 characters versus the frozen 73,925-character baseline: 68.45% reduction, above the 35% requirement. |
| Selected-context catalog exclusion | PASS | The selected context is compact and the context-router regression test rejects `ALL_TOOLS` content. |
| Feature Planner evaluation | PASS | 10/10 revision cases scored at least 16/20; minimum score 18/20. |
| Frozen Reviewer evaluation | PASS | BLOCKER recall 100%; HIGH recall 100%; false positives 5%; severity agreement 95%; actionable quality 90%. |
| Model routing | PASS | Focused tests verify script/light/medium routing and strong escalation for every configured high-risk condition. |
| Compact sub-agent policy | PASS | `fork_turns=none`, compact JSON packets, structured JSON output, batched critical/noncritical review, and no one-agent-per-case policy. |
| GitHub tool-routing contract | PASS | Focused tests require direct connector routing without discovery and allow `gh` only after recorded connector failure. Issue #168 was created through the connector. |
| Session tool discovery | FAIL | Before the direct connector call, the session filtered the available catalog and received a large truncated connector listing. This violated the no-discovery acceptance rule even though no prompt or secret was exposed. |
| Full pytest | FAIL | The single run completed with 243 passed, 1 skipped, and 12 failed. Nested agent-task fixtures exceeded the Windows Git path limit and reported `fatal: '$GIT_DIR' too big`. |
| Full pytest execution count | PASS | The full suite was executed exactly once. No retry was used to replace the failed evidence. |
| Quality | FAIL | The single run spent the remaining session timeout creating `.nox/lint` and installing the editable project instead of reusing an existing environment. |
| Quality execution count | PASS | Quality was started exactly once and was not retried after the timeout. |
| Validation cache reuse | NOT_RUN | The first validation did not complete, so a second invocation was intentionally not used to rerun the uncached quality check. |
| Validation artifact | FAIL | The interrupted orchestrator preserved the atomic cache entry for failed pytest but did not publish `validation.json`. |
| Compose exclusion | PASS | No Compose command was selected or executed for the pure-software replay. |
| Live model/provider behavior | NOT_RUN | The approved deterministic mode intentionally made no fresh model calls. Static routing evidence is not presented as live-provider evidence. |
| Production, hardware, and external export | NOT_RUN | These systems were outside the approved scope and were not accessed. |

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
`.ai/agents/reviewer.md`. The selected known-failure records were `SP-FAIL-014` and
`SP-FAIL-015`. The focused context-router test also verifies that run artifacts and an
`ALL_TOOLS` dump are absent from the compact packet.

## Evaluation replay

The following read-only commands passed:

```text
python -m pytest -q -p no:cacheprovider --basetemp .agent-validation-tmp-acceptance-focused tests/test_agent_context.py tests/test_model_routing.py tests/test_tool_routing.py tests/test_validate_change.py
26 passed in 5.18s

python -m tools.evaluate_feature_planner
Feature Planner evaluation PASS: 10/10 revision cases >=16/20; minimum score 18/20.

python -m tools.evaluate_reviewer --run .ai/evaluations/reviewer/runs/20260809-9302afb-oracle-blind-09
Reviewer run PASS: BLOCKER 100%; HIGH 100%; false positives 5%; severity 95%; actionable 90%.
```

The Reviewer command names the frozen run explicitly. The command without `--run` validates only the
corpus and is not accepted as evidence for the published oracle-blind result.

## Validation orchestration

The final orchestration command was invoked once:

```text
python -m tools.validate_change --base origin/main --task-key tomato-ai-42-acceptance-replay --explain --force full
```

It did not meet the acceptance gates:

```text
full_pytest: FAIL in 39.832s
243 passed, 1 skipped, 12 failed
common failure: fatal: '$GIT_DIR' too big

quality: FAIL after the 300.4s session timeout
last operation: python -m pip install -e '.[dev]' for a newly created .nox/lint environment

validation.json: not published
validation-cache.json: failed full_pytest entry preserved atomically
compose_config: NOT_RUN
```

The nested validation base path included the task worktree, validation temp directory, task key, pytest
case directory, fixture repository, and another `.agent-worktrees` directory. This exceeded Windows Git
path handling in 12 `tests/test_agent_task.py` cases. The quality session did not reuse the environment
from the primary checkout because no reusable `.nox` environment existed in the isolated worktree.

A second validation invocation was not made. It would have reused the cached failed pytest result but
would also have started the uncached quality check again, violating the replay's exactly-once rule. Cache
reuse therefore remains `NOT_RUN`, and the overall replay remains `FAIL`.

Compose remained `NOT_RUN` because the approved task has only the additive `pure_software` class and no
infrastructure or risk override.

PR #167 is not used as evidence for this gate: its approved brief explicitly added
`infrastructure_deployment` and `security_secrets`, so its Compose selection was correct but is not a
pure-software replay.

## Evidence boundary

This replay validates deterministic repository behavior and the already frozen Reviewer evidence. It
does not validate current model-provider availability, prompt/output volume from a fresh Reviewer run,
physical outcomes, production availability, secrets, Docker infrastructure, or external exports. Those
items remain `NOT_RUN` rather than being inferred from green automated checks.

Rollback is a revert of this report-only commit. No runtime contract, durable data, deployment state,
or production topology changes.
