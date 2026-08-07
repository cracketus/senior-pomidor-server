# Implementation Brief: Harden malformed LLM output and reasoning leakage

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-10

## Problem

A local model consumer sometimes returns malformed JSON, extra prose or reasoning text, and output may reach a public summary.

## Desired outcome

Only strictly parsed and semantically validated bounded final fields reach consumers; invalid/unavailable responses use a safe fallback and reasoning/prompt content remains private.

## Current behavior and evidence

`app/ollama.py`, `tests/test_ollama.py` and `docs/OLLAMA_TROUBLESHOOTING.md` are available. The exact consumer/public schema, affected model/runtime and observed raw response are Unknown.

## Scope

- Reproduce sanitized response classes, strengthen response boundary/validation, bounded diagnostics/fallback, regression tests and public serialization review.

## Out of scope

- Publishing raw prompts/reasoning, model upgrade without evidence, retrying invalid requests unchanged, Control/actuation use.

## Architecture placement

Provider client owns transport errors; consumer contract parser owns strict schema/semantic validation; public serializer maps only approved final fields. LLM remains an untrusted analyst.

## Affected contracts and consumers

Model response and public summary contracts may be affected. Required/optional fields, lengths, allowed values and privacy classification must be inventoried; storage/logging/dashboard consumers require review.

## Safety/risk classification

Classes: `llm_vision`, possibly `schema_data_contract`. Flags: `public_contract`, `security_secrets` if prompt/private data handling changes. Apply `SP-FAIL-012`, `SP-FAIL-013`.

## Proposed implementation sequence

1. Capture synthetic sanitized malformed/extra/reasoning fixtures and identify exact consumer.
2. Approve minimal supported schema plus semantic/length bounds and final-only mapping.
3. Add failures before changing parser/fallback; bound private diagnostics.
4. Evaluate representative model/runtime locally, then canary public serialization with no raw output.

## Failure modes

Malformed/truncated JSON, markdown fences/extra prose, reasoning/prompt echo, schema-grammar rejection, wrong types/semantics, oversized response, timeout, unavailable model and retry exhaustion produce a bounded fallback.

## Backward compatibility

Preserve valid current final output. Any public schema change is versioned/additive; diagnostic fields stay private.

## Testing plan

Baseline and focused tests for every failure above, public serialization privacy, raw response exclusion, timeout/unavailable behavior and supported schema. Optional representative cross-model evaluation is recorded separately.

## Observability

Record model/runtime, duration, bounded error category and validation outcome privately; never log raw prompt, reasoning or sensitive response by default.

## Documentation updates

Update output contract, model troubleshooting, privacy/public-data boundary and fallback/operator guidance.

## Rollout and rollback

Replay fixtures, shadow validation, local model acceptance, then canary. Abort on valid-output regression or leakage; restore previous public path or disable model output and use deterministic fallback.

## Acceptance criteria

- [ ] Malformed/extra/reasoning/timeout/unavailable/oversized cases never reach public final output or trusted fields.
- [ ] Valid responses remain compatible and diagnostics contain no raw prompt/reasoning/private payload.

## Blocking open questions

- Exact consumer/public schema, sanitized failing samples, affected models/runtimes, allowed fallback and private diagnostic retention?

## Evidence and references

- `app/ollama.py`; `tests/test_ollama.py`; `docs/OLLAMA_TROUBLESHOOTING.md`.
- Exact incident response and public consumer are unverified.
