# Adjudication: 20260809-3bcf285-oracle-blind-05

Verdict: `FAILED_RERUN_REQUIRED`

The frozen one-to-one mapping does not merge independent findings or map duplicate restatements.
BLOCKER recall is complete and the false-positive ceiling is met, but HIGH recall remains below 85%.
The medium historical Reviewer missed an out-of-scope runtime cadence change, the backup privilege
boundary, persisted/public-story risk classification, an edited applied migration and the public-story
privacy boundary.

Run 05 also independently identified distinct missing evidence for the shared-database security audit,
physical failure-path suite, contract consumer replay, Compose negative paths and the real credential
parser. Those supported findings require a new oracle version; the combined scanner/parser entry must
be split to preserve one-to-one mapping. The v4 oracle and this raw run remain unchanged.

The next blind run escalates disputed/high-risk historical cases to the strong tier. Only the neutral
dependency case remains at medium tier.
