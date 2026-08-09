# Reviewer evaluation results

Status: `PASS`

Published run: [`20260809-9302afb-oracle-blind-09`](runs/20260809-9302afb-oracle-blind-09/)

| Gate | Result | Requirement |
| --- | ---: | ---: |
| BLOCKER recall | 100% | 100% |
| HIGH recall | 100% | at least 85% |
| False-positive rate | 5% | at most 20% |
| Severity agreement | 94.74% | at least 80% |
| Actionable quality | 90% | at least 90% |
| Critical ordering | PASS | PASS |
| Missing manual evidence detection | PASS | PASS |

The run used four hash-pinned historical dependency updates and six unchanged seeded safety,
contract, security, model-boundary and portability mutations. The historical packet ran at medium
tier; every risk-bearing seeded case ran at strong tier. Both fresh contexts were denied the oracle,
case registry, earlier reports, mappings, results, evaluator tests and implementer rationale. Raw JSON
was frozen before human one-to-one mapping.

All 19 oracle root causes were detected. One separate RV-06 automated-evidence restatement remains
unmapped, producing the 5% false-positive rate. One raw-model finding was reported as `BLOCKER` while
the oracle records `HIGH`; this is the sole severity disagreement. No raw report contains oracle IDs.

Earlier exploratory/calibration runs remain preserved as invalid or failed evidence and are not part
of this result. This 10-case static corpus calibrates Reviewer behavior; it does not replace human
review, production rehearsal, real hardware checks or verification of evidence unavailable to the
repository.
