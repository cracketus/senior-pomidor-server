# Exploratory run adjudication

Verdict: `INVALIDATED`

The initial oracle was changed after the Reviewer result was inspected. The available
`observed-findings.json` is a normalized file containing `expected_id` values rather than the complete
raw Reviewer responses. No Reviewer-instruction, cases, oracle, patch or launch-parameter hashes were
recorded at run time. Consequently neither blindness nor reproducibility can be established.

The legacy oracle and normalized observations remain at their original paths to preserve exactly the
evidence that survived. Missing raw output is recorded as missing; it is not reconstructed or
fabricated. This run is intentionally rejected by the scorer and none of its percentages may appear as
final Reviewer results.

Any oracle correction requires `oracles/v2.json`, a rationale here or in the new run adjudication, and
a complete fresh-context rerun.
