# Scheduled agent run policy

The common artifact is [`scheduled_agent_run_v1`](../schemas/scheduled_agent_run_v1.schema.json).
It records one bounded execution attempt for Scientific Scout, Grant Scout, Story Miner,
Documentation Synchronizer, or Weekly Project Planner. It complements the broader `agent_run_v1`
audit artifact from TOMATO-AI-13; it does not replace human approval, source evidence, or runtime
health records.

## Naming and storage

- `run_id` is stable, repository-safe, and unique for one attempt:
  `YYYYMMDDThhmmssZ-agent_type-short_suffix`.
- Store one immutable JSON artifact per run under an owner-controlled scheduled-run store using
  `scheduled-agent-runs/YYYY/MM/<run_id>.json`. The repository examples are synthetic only.
- `idempotency_key` is stable across retries for the same agent, schedule window, input manifest,
  and prompt/config version. A retry receives a new `run_id` but keeps the same key and points to
  the prior attempt with `previous_run_ref`.
- Input and output references are bounded repository-safe identifiers or approved artifact IDs.
  Never embed raw prompts, private payloads, credentials, or unredacted logs.

## Idempotency and deduplication

1. Before creating a new output, look up the idempotency key in the owner-controlled run index.
2. A completed run with the same idempotency key and equivalent input manifest is a duplicate: record a
   `skipped` run with `previous_run_ref`; do not create a second published output.
3. A failed or partial run may be retried with the same key. The new artifact records the prior run
   and must not overwrite its output.
4. Duplicates in source findings are counted in `quality.duplicates_removed`; deduplication never
   silently changes a source claim.
5. Output publication is a separate decision. Only an accepted successful result may advance the
   workflow's current-output pointer; failed, partial, skipped, and pending results remain audit
   artifacts.

## Status, failure, and recovery

- `success` means the run completed its bounded work and produced the declared outputs.
- `partial` means some outputs or sources were unavailable; the last good output remains current.
- `failed` means no trustworthy new output was produced; preserve the last good output.
- `skipped` means idempotency/deduplication or an explicit safe precondition prevented work.
- Retry only errors marked `retryable: true`, with bounded attempts and backoff recorded outside
  the artifact. Never retry a privacy, schema, authorization, or deterministic validation failure
  unchanged.
- A malformed artifact is rejected and does not advance current output. Repair creates a new run;
  it does not edit history.

## Human decision and retention

`human_decision` records whether a person accepted, modified, rejected, or still needs to review
the result. `notes` are bounded and must not contain private correspondence or raw model reasoning.
Human acceptance does not authorize production deployment, physical actuation, or public release by
itself; those boundaries remain governed by the repository safety rules.

Keep run artifacts for the configured audit period of the owner-controlled store. Retention cleanup
must be dry-run/reviewable, preserve the latest accepted output and its input references, and never
delete the only record needed to explain a published decision. The repository does not configure or
execute that cleanup in this issue.

## Redaction and privacy

Use source and claim rules from [`SOURCE_POLICY.md`](../research/SOURCE_POLICY.md). Store only
redacted references for private material. Reject credentials, exact home location, internal IPs,
private messages, raw sensitive logs, hidden prompts, and model reasoning. AI summaries remain
untrusted analyst output and cannot become evidence merely by appearing in a run artifact.

## Compatibility

The schema is additive to `agent_run_v1`. Existing audit records remain valid; a scheduled run may
reference its broader audit artifact through `input_refs`/`outputs` without duplicating it. Future
fields require a new schema version or an explicitly approved additive compatibility rule.
