# Real Edge/Core verification (#247)

The harness runs the actual Edge `main.run`, formatter, durable SQLite spool,
MQTT publisher and HTTP ACK delivery worker against actual Core HTTP/MQTT ingestion,
PostgreSQL, State Estimator and read APIs. Only sensor acquisition and its clock are
controlled by the test driver. There is no mock Core or mocked storage/transport.
The HTTP fault proxy drops responses **after** receiving Core's durable ACK.

## Run

Use Python 3.12, Docker Compose v2 and clean, committed Core/Edge checkouts.
Run from the Server harness checkout (which may be newer than the Core under test):

```bash
python -m pip install -e '.[dev]'
python -m tools.cross_repo --core-source ../core --edge-source ../edge --output ../verification-run-001
python -m tools.cross_repo.evidence --report ../verification-run-001/report.json --core-sha <exact-core-sha> --edge-sha <exact-edge-sha>
```

The output directory must not exist. Optional `--core-image` / `--edge-image`
accept only digest-pinned `ghcr.io/cracketus/...@sha256:...` images whose OCI revision
matches the selected checkout. Use these options for existing immutable releases.
Otherwise the runner builds from `git archive` of the exact commit (no untracked
files, credentials or local modifications) and records the actual local image ID.
A local image ID is **not** a registry manifest digest or a release-bundle checksum.

The runner is a bounded test command, not a general Compose CLI: only a fresh random
project, internal network, owned named volumes, ephemeral loopback ports, fixed
commands, fake sensors and no external exporter. Remote Docker contexts are rejected.
No production env file, host data mount, GPIO or Docker socket enters a container.
The test stops its project but deliberately preserves its volumes and evidence.
It never executes `down -v`; inspect/remove obsolete test resources separately.

## Scenarios and assertions

- Normal delivery: formatter/spool → transport → durable row → read API.
- MQTT-only persistence while HTTP is unavailable proves PUBACK does not complete spool;
  exact HTTP replay must return `duplicate`, then real delivery drains.
- Core ingestion outage grows backlog; pending rows survive an Edge container restart.
- A fresh sample is delivered while older backlog still exists; eventual full drain.
- Lost ACK: PostgreSQL/API contain the row while Edge still considers it pending;
  retry completes without a second scientific row.
- Delayed/out-of-order/future/stale time: timestamps preserved, delayed records do not
  replace latest, future/stale reliability stays UNKNOWN.
- High-VPD: real Edge derived metric, Core persistence and actual estimator invocation;
  state/sensor-health/anomaly/health reads must work. Physical or agronomic outcomes
  are not asserted.

Every checkpoint compares expected record identities with PostgreSQL and API identities,
counts duplicates/missing/unexpected rows and verifies observation timestamps. Pending
checkpoints allow accounted-for backlog; completed checkpoints require full reconciliation.
Any deadline, assertion, image/config mismatch or cleanup failure exits nonzero.
`report.json` is bounded public-safe software evidence; `services.log` contains bounded
synthetic test diagnostics and should still be reviewed before wider publication.

## Executable compatibility window

`.github/workflows/cross-repo.yml` executes these exact pairs on PR/main, weekly and manually:

| Pair | Core | Edge | Evidence |
|---|---|---|---|
| current/current | checked-out candidate commit | d14b9367b359ab260bdb62c6364ccd542fbbbd26 | full behavioral scenarios |
| previous Edge/current Core | checked-out candidate commit | 14d297ef1b18567d101876c143240d9354ddc860 | full behavioral scenarios |
| current Edge/rollback Core | v0.3.0, 549dc4d21897203c167749611416355f820d6372 | d14b9367b359ab260bdb62c6364ccd542fbbbd26 | existing released Core image, full scenarios |

This is an explicit **verification target window**, not a claim of PASS until the
matrix runs successfully. Unsupported older pairs are not silently included. Update
pins through review; a pin change starts new evidence. Legacy v1/v2 contract fixtures
remain covered by Core fixture/API tests and the existing Docker E2E suite.
Historical qualification v1's v0.2.4 rollback assertion is a different campaign;
this harness does not silently rewrite that older evidence contract.

## Properties and time

`tests/test_system_properties.py` uses bounded deterministic Hypothesis examples for
identity/dedup/order, serialization/unit preservation, missing/stale/future health and
Europe/Vienna DST gap/fold UTC round trips. Failing examples are minimized by Hypothesis;
retain the minimized counterexample as a named regression fixture when fixing a defect.
Run with `python -m pytest -q tests/test_system_properties.py`.

## Release integration and remaining gates

`senior-pomidor.cross-repo-e2e.v1` explicitly has `evidence_scope=CI` and exact Core/Edge
Git/image identities. Its fail-closed gate requires all scenarios and consistent counts.
The release qualification workflow checks this additional report for the **same pair**.
It still independently requires its existing staging/rehearsal/soak/canary evidence.
Never relabel this short CI run STAGING or turn absent 24h/canary evidence into PASS.
Future actuator invariants remain NOT_IMPLEMENTED.

Maintainers must configure required branch checks separately. #247's performance,
mutation/fuzzing, dataset protection and remaining alert work are outside this six-step
implementation; software tests cannot close physical or production acceptance.
