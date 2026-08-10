# Claims policy

## Evidence vocabulary

Use the same labels in research notes and public drafts. Source identity, access level,
verification date, citation, confidence, uncertainty, and visibility follow the shared
[`SOURCE_POLICY.md`](../research/SOURCE_POLICY.md) and [`evidence-schema.yaml`](../research/evidence-schema.yaml).

| Label | Meaning | Public treatment |
| --- | --- | --- |
| `measured` | Recorded by a named instrument/boundary with unit and timestamp | Publish only after privacy and quality review |
| `observed` | Human or image observation with context | Attribute the observation and avoid generalisation |
| `inferred` | Derived using a documented method | Explain inputs, method, and uncertainty |
| `speculative` | Hypothesis, idea, or future work | Label explicitly; never phrase as a result |

## Publication rules

1. A claim must have an evidence label and a source or task-local reference.
2. Measured values retain units, timestamp semantics, and relevant quality limitations.
3. Inferences do not become measured facts by repetition or model-generated summarisation.
4. Scientific and funding claims require current source review; stale eligibility is not evidence.
5. AI-generated text is a draft aid only. It cannot add evidence, remove limitations, or authorize
   publication by itself.
6. Public material must pass privacy review under `docs/PUBLIC_DATA_POLICY.md`.

## Safe language

Prefer: “in this observation,” “the available data suggest,” “we measured,” “we have not yet
validated,” and “this is a hypothesis.” Avoid universal claims, causal claims without evidence,
guarantees of plant outcomes, and claims that software success proves a physical-world outcome.
