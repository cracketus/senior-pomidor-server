# Implementation Report: #98 real Grafana rule verification

Run `20260928-issue-98`; audit `.ai/agent-runs/20260928-issue-98.json`.
Brief: `.ai/implementation-briefs/ISSUE-98-alert-runtime.md`.

Added scheduler-level cases for18 general rules, positive Pending hold, empty-data
baseline, real SQL permission error and recovery. Existing five Edge cases remain.
The first runtime exposed four production SQL projection defects: extra numeric
observed fields and timestamp fields made Grafana reject alert table results.
They now remain text labels, with exactly one numeric value; predicates unchanged.

The second runtime completed all new alert phases successfully, then exposed an
existing concurrent-estimator race in a raw-reader no-write assertion. The test now
pauses only its own estimator around that snapshot comparison and restarts in finally.

Local static provisioning8PASS; lint/types/security PASS. Independent reviewer found
no further implementation defect; final Docker CI remains required for handoff.
No production deployment. Source hold durations unchanged; accelerated tests prove
scheduler mechanics, not full production timing or notification delivery.
Rollback is revert; no schema migration. See docs/ALERT_VERIFICATION.md.

## Final source review and evidence

Independent source/merge review APPROVE; see ISSUE-98-review.md. Complete real Docker
and Grafana run36440017169 PASS, cross-repository36440016592 PASS. Final integration
includes #91 with both complete verification phases; PR#368 is stacked on PR#367.
Merge #367 first, then retarget #368 to main. Final PR checks are authoritative.
