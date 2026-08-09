# Reviewer evaluation

This suite calibrates [Reviewer 1.0](../../agents/reviewer.md) against four pinned historical commit
diffs and six safe seeded-mutation cases. It never runs application code, contacts production, enables
external export, or uses hardware. Owner: development/safety maintainer.

## Immutable layout

- [`cases/v2.json`](cases/v2.json) contains only case descriptions and hash-pinned artifacts. Text
  hashes use canonical LF line endings so immutable runs verify identically on Windows and Linux. It does
  not contain oracle IDs.
- [`oracles/v6.json`](oracles/v6.json) is the current versioned answer set. Changing it requires a new oracle
  version, rationale, and a completely new blind run.
- [`patches/`](patches/) contains non-executable seeded diffs. The secret case uses an unmistakably
  synthetic, non-key sentinel.
- `runs/<run-id>/manifest.json` binds the Reviewer instructions, Review Report JSON schema, oracle,
  cases, patch/commit artifacts, repository revision, model tier and launch parameters by SHA-256.
- `runs/<run-id>/raw/RV-*.json` stores the model output verbatim. Raw findings have their own IDs and
  never contain `expected_id`, oracle IDs or adjudication labels.
- `runs/<run-id>/mapping.json` is the later human one-to-one mapping from observed finding ID to oracle
  finding ID. Unmapped observed findings count as false positives.
- `runs/<run-id>/metrics.json` is the deterministic result and `adjudication.md` records human mapping
  rationale without rewriting raw output.

The legacy root files `cases.json`, `expected-findings.json` and `observed-findings.json` are retained
only as evidence for the invalidated exploratory run described in
[`runs/20260808-exploratory-invalidated/`](runs/20260808-exploratory-invalidated/). They are not scorer
inputs and must not be described as a baseline.

## Oracle-blind process

1. Freeze Reviewer instructions and the current versioned cases file. A human evaluator separately freezes a new
   versioned oracle.
2. Create a manifest containing the exact hashes required by the schema above. Start a fresh context
   which has not received the oracle, prior reports, mapping, results, or implementer rationale.
3. Give the Reviewer the approved case description and hash-verified artifacts. Preserve each complete
   structured response verbatim as `raw/RV-*.json`; do not normalize or rewrite it.
4. Only after all raw reports are frozen, create the one-to-one `mapping.json`. A mapping may not reuse
   an observed or oracle ID and may not cross cases.
5. Compute and freeze `metrics.json`, document rationale in `adjudication.md`, then run:

   ```powershell
   python -m tools.evaluate_reviewer --run .ai/evaluations/reviewer/runs/<run-id>
   python -m pytest -q tests/test_reviewer_evaluation.py
   ```

6. Any Reviewer, oracle, case or artifact hash mismatch invalidates the run. If adjudication changes
   the oracle, create a new oracle version and repeat the complete blind run.

Running `python -m tools.evaluate_reviewer` without `--run` validates only the frozen corpus. It does
not claim a model evaluation passed.

## Gates

- BLOCKER recall: 100%.
- HIGH recall: at least 85%.
- False-positive rate: at most 20%.
- Severity agreement: at least 80%.
- Actionable quality: at least 90%.
- Critical findings precede lower-severity findings.
- Missing required manual/rehearsal evidence is reported as HIGH/BLOCKER and is never closed by green
  automated checks.

Actionability is structural and evidence-bound: `location` must occur in an artifact,
`evidence_excerpt` must be an exact artifact fragment, the required change must name a concrete action,
and the suggested check must be reproducible or explicitly manual.

## Limitations

This small corpus is calibration evidence, not proof that arbitrary reviews are complete. Static
fragments do not exercise real concurrency, Docker, migrations, networking, hardware, plant response,
production data or private infrastructure. Human review remains mandatory for physical actions,
electrical limits, destructive migration, security incidents, production rollout/rollback,
public-data decisions, ambiguous ownership and evidence unavailable to the repository.
