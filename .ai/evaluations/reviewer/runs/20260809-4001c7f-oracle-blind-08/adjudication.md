# Adjudication: 20260809-4001c7f-oracle-blind-08

Verdict: `INVALID_OUTPUT_CONTRACT`

Corpus v2 produces the intended stable result: all oracle root causes are detected, the four neutral
historical cases have zero findings, and only two duplicate evidence findings remain unmapped.

This run is not scoreable because the direct packets abbreviated case identifiers, causing raw files
and `case_id` values such as `RV05` instead of the frozen `RV-05`. The scorer correctly treats the
required `RV-*.json` reports as missing. In addition, the compact seeded prompt abbreviated supplied
implementation-report evidence. Several raw `evidence_excerpt` values therefore refer to the prompt's
abbreviation rather than a contiguous fragment of the frozen case artifact, so actionable quality
would also fail the deterministic scorer. Raw output is unchanged and no metrics are published.

The oracle, corpus and Reviewer instruction remain unchanged. The next full blind run uses the exact
case evidence strings in its direct packet and explicitly requires excerpts to be copied verbatim from
the patch or those exact supplied strings.
