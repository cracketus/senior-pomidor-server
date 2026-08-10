# External source and evidence policy

## Purpose

This policy gives Scientific Scout, Grant Scout, Story Miner, Documentation Synchronizer, and
Weekly Project Planner one source and evidence model. It governs how a source may support a claim;
it does not turn an external source or an AI summary into a trusted safety or physical-action input.

The machine-readable companion is [`evidence-schema.yaml`](evidence-schema.yaml), with synthetic
records in [`evidence-examples.yaml`](evidence-examples.yaml).

## Source classes and access levels

| Source class | Minimum identity | Allowed evidence boundary |
| --- | --- | --- |
| `primary_scientific_source` | DOI or publisher URL, title, authors, year | Methods/results only when the cited full text was accessed |
| `preprint` | Stable preprint identifier and version | Claims must be labelled non-peer-reviewed |
| `review` | Publisher/DOI and review scope | Synthesis/context; do not attribute primary measurements to it |
| `official_programme_page` | Official programme URL and organisation | Current programme existence/scope; eligibility/deadline needs current verification |
| `official_documentation` | Maintainer/publisher URL and version | Documented behavior for the cited version |
| `repository_artifact` | Repository path/commit or release | Exact artifact behavior; do not infer deployment or physical success |
| `telemetry` | Synthetic/public-safe record identity, UTC timestamp, units | Measured values within the record's quality boundary |
| `direct_observation` | Observer or observation process, timestamp, context | Observed facts only; no unrecorded causal explanation |
| `inference` | Referenced inputs and documented method | Derived claim, explicitly marked as inferred |

Access is one of `metadata`, `abstract`, `full_text`, or `full_call_document`. Abstract-only access
supports bibliographic context and abstract-level claims only; it cannot support methodology,
results beyond the abstract, limitations, or replication claims.

## Freshness and verification

- All timestamps are UTC ISO-8601 at interchange/storage boundaries.
- Every record has `last_verified_at`; use `null` only for a deliberately unverified lead and never
  use that record for a current recommendation.
- Grant eligibility and deadline claims require an official programme source, the exact call or
  official call document where available, and a current `last_verified_at`.
- Current claims must be rechecked before publication or decision use. A date records verification;
  it does not guarantee that a source remains current.
- Record source version, call identifier, DOI, commit, or observation identity when available.

## Claims, confidence, and citation

Claims use the shared vocabulary `measured`, `observed`, `inferred`, or `speculative` from
[`../content/CLAIMS_POLICY.md`](../content/CLAIMS_POLICY.md). Confidence is `high`, `medium`, `low`,
or `unknown`; uncertainty must state what is missing, variable, or not validated.

Use this citation shape:

`[source_id] Title — Publisher/organisation, year or version. URL/identifier. Accessed YYYY-MM-DD.`

Repository artifacts additionally include the repository-relative path and commit/ref. Telemetry
and direct observations use the record identity and timestamp instead of inventing a public URL.
Never cite a hidden prompt, private correspondence, raw private dataset, or an unredacted local path.

## Conflicts and precedence

1. Check identity, version, date, access level, and whether the sources actually address the claim.
2. Prefer the most direct and current source: full primary/official call document, then official
   page/documentation, then versioned repository artifact, then review/preprint, then secondary
   summary. A direct measured record supports its own measurement but not an external causal claim.
3. If equally authoritative sources conflict, preserve both references, describe the conflict, lower
   confidence to `low` or `unknown`, and do not present a single resolution as fact.
4. Resolve only by a newer authoritative correction, a documented version change, or a new
   measurement/method; never by majority vote or model preference.

## Private material, screenshots, and photos

- Screenshots and photos are observations or evidence of a view, not proof of the underlying source.
  Record source URL, captured UTC time, visible version/date, and what was actually visible.
- Redact names, exact location, addresses, credentials, internal IPs, private correspondence,
  unpublished sensitive content, metadata, and private background details before repository storage.
- Private or sensitive records stay in the approved private storage boundary and are represented in
  public notes only by a redacted reference and bounded claim.
- Do not copy raw private telemetry, photos, prompts, or model reasoning into public context files.

## AI and downstream workflow boundary

LLM-generated summaries, extracted citations, rankings, and drafts are analyst output. They must be
checked against the cited source and may not be used as a source, evidence substitute, safety
decision, grant eligibility proof, or direct actuator input.

Every downstream workflow should preserve the evidence record, claim label, source reference,
access level, verification date, confidence, uncertainty, and public/private decision when passing
material to another workflow.

## Maintenance

The research/content owner reviews this policy at season boundaries and whenever a source class,
publication rule, privacy boundary, or downstream workflow changes. Changes are additive and
versioned; transient source status belongs in evidence records, not this stable policy.
