# Grafana runtime verification (#98)

The required Docker E2E job loads real checked-in dashboards, datasource and alert
provisioning into Grafana. Five Edge reliability rules already have scheduler-level
normal/firing/recovery and empty-data coverage. The additional matrix covers all
18 general telemetry/plant/state rules; an exact-title-set test fails when a new
rule has no runtime case.

Run `python -m pytest -q tests/test_grafana_provisioning.py` for static checks, and
`RUN_DOCKER_E2E=1 python -m pytest -q tests/test_docker_e2e.py -p no:cacheprovider`
on a disposable Docker host for actual scheduler evidence.

Before normal transport scenarios, the test pauses only its own estimator worker,
seeds synthetic source rows into its disposable PostgreSQL database, and observes:

1. Empty data is normal according to checked-in `noDataState: OK`.
2. A positive hold reaches Pending before firing.
3. All 18 expressions fire on their named failure/threshold cases.
4. Healthy values/resolved anomalies recover all 18 rules.
5. Revoked SELECT for the task-owned Grafana role causes actual datasource execution
   failure; `execErrState: Alerting` is checked through scheduler state/health.
6. Restored permission recovers the evaluator.

Cleanup removes only `alert-test-` fixture rows and restarts the task estimator.
No production database, dashboard or role is used. Existing Edge transport and
reliability scenarios then continue on the same isolated stack.

Only the copied test provisioning is accelerated: interval 10s, positive plant holds
30s, existing Edge holds 0s. Expressions, thresholds and production source files are
unchanged. This proves hold-state mechanics, not wall-clock execution of production
1–30 minute durations. Source duration/threshold/provisioning tests remain in place.
A CI run cannot establish operator notification delivery or production readiness.

Bounded phase evidence is written to `verification-artifacts/alert-runtime.json`
and retained by CI even on failure. Missing evidence or `FAIL` cannot qualify a release.
Revert this test/tooling change to roll back; no migration is involved.
