# Review Report: <title>

Report schema: `senior-pomidor.review-report.v1`

Reviewer/version:

Issue/brief:

Base/head or diff artifact:

Independence statement: separate context/session, and whether brief/diff were read before implementer rationale

## Verdict

`APPROVE | APPROVE WITH FOLLOW-UPS | REQUEST CHANGES | BLOCKED`

One-sentence evidence-based rationale.

## Independent classification

- Task classes:
- Risk flags:
- Differences from brief classification:
- Applicable `SP-FAIL-*`: coverage, missing evidence, or reason not applicable.

## Scope and architecture assessment

- Acceptance-criterion mapping and scope drift.
- Ownership boundaries and preserved/prohibited paths.

## Findings

Critical findings must precede lower-severity or stylistic notes. Write `None` when there are no
findings. Repeat this exact block for every finding:

```yaml
- id: stable observed finding ID, never an oracle ID
  severity: BLOCKER | HIGH | MEDIUM | LOW | NOTE
  category: safety | correctness | architecture | tests | operations | docs | security
  location: path:line or artifact
  finding: ...
  evidence: ...
  evidence_excerpt: exact observed fragment copied from the reviewed artifact
  impact: ...
  required_change: ...
  suggested_test: ...
```

`location` must name a path present in the reviewed artifact. `evidence_excerpt` must be an exact,
bounded fragment from that artifact rather than a paraphrase. Keep oracle IDs and adjudication labels
out of this report; mapping is a separate human step after raw output is frozen.

## Contract and consumer review

- Artifact/version, producer, consumers, units/ranges, timezone, optionality, compatibility, fixtures,
  rollout and public-data impact; state unaffected or unknown surfaces explicitly.

## Test and evidence matrix

| Status | Required/manual check | Evidence and reviewer assessment |
| --- | --- | --- |
| PASS / FAIL / NOT RUN | Exact check | Result, missing evidence, or why not applicable |

Passing CI alone does not close missing required manual/rehearsal/physical evidence.

## Operations, safety, security and privacy

- Startup/shutdown, health, logs/metrics/audit, failure behavior, rehearsal isolation, external export,
  backup/rollback, physical boundary, secrets and public data.

## Documentation assessment

- Authoritative documents checked, drift found, and required updates.

## Follow-ups outside this PR

- Separate issue proposal and rationale. Write `None` when empty; do not silently expand this PR.

## Limitations and unverified evidence

- Human-only, unavailable, private, physical, deployment or production evidence. Write `None` only
  when verified.
