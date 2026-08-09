# Adjudication: 20260809-1e86669-oracle-blind-04

Verdict: `FAILED_RERUN_REQUIRED`

The frozen one-to-one mapping preserves distinct semantics. Combined findings were mapped to only one
oracle finding; related but substantively different findings were not used to inflate recall.

BLOCKER recall remained complete. HIGH recall is below 85% because the reports missed the built-in
database URL fallback, the reasoning-before-marker validation defect, persisted/public-story risk
classification, and one of the two independently expected secret-fixture concerns. The run also
exceeded the 20% false-positive ceiling. The sensor-health finding was detected but under-severed.

The oracle is unchanged. Reviewer guidance may be clarified only in general risk-pass terms, followed
by a completely new oracle-blind run with a new Reviewer hash and manifest. This run must not be used
as the published result.
