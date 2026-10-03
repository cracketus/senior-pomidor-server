# Integration and performance guardrails (#91)

Run `python -m pytest -q tests/test_query_budgets.py` for fast HTTP query-count and
storage-failure checks. The latest-across-devices endpoint uses one correlated indexed query
plus batched reading/error loads instead of three additional queries per device.
Tests compare one and twenty devices; SQLAlchemy batches relationships beyond 500
rows, so this is a bounded workload budget, not an unlimited three-query promise.
Lifecycle exclusions and response fields remain unchanged.

Run `RUN_DOCKER_E2E=1 python -m pytest -q tests/test_docker_e2e.py -p no:cacheprovider`
on a disposable Linux Docker host. The existing harness creates synthetic state,
checks local Docker/isolation, and cleans its own stack. Do not supply production
environment, databases or credentials. Compose is reused instead of introducing
an overlapping Testcontainers stack. CI executes this same command.

The performance phase runs after existing functional/alert checks:

- PostgreSQL production persistence fails during pod insertion: device/event/pod/error
  counts remain zero, then retry is accepted.
- Forty HTTP records with four concurrent requests: all ACKs and readback identities/
  observation times agree. Total time must be below 60 seconds and nearest-rank p95
  below 5 seconds. These deliberately broad budgets catch stalls, not small CPU noise.
- Forty MQTT identities published twice with QoS 1: eighty deliveries produce forty
  observations with original timestamps within 60 seconds. This measures Core ingestion,
  not the actual Edge sender's known publish wait or spool throughput.
- Ten thousand synthetic rows are seeded in a rolled-back PostgreSQL transaction.
  EXPLAIN runs on captured production all-device/single-device latest/history SELECTs: selective reads must use
  an index without a sequential scan. Planner statistics are refreshed; no index is forced.

`verification-artifacts/performance-smoke.json` contains bounded timings, counts and
check status, uploaded even on failure under a commit-named CI artifact. Missing reports
mean the performance phase did not finish/start; they are not PASS. Workflow identity
binds results to the tested commit. Compare p95/throughput only for equivalent workload,
runner class, PostgreSQL/Python versions and repeated runs; a single shared-runner result
is not production capacity evidence. Correctness/query-count budgets remain hard gates.
Existing real Edge spool/recovery qualification stays in `CROSS_REPO_VERIFICATION.md`.

Rollback: revert the change; no migration or deployment is performed by these checks.
