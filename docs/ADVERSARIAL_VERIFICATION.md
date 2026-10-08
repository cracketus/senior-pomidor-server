# Bounded adversarial verification (#96)

`python -m pytest -q tests/test_openapi_fuzz.py` runs reproducible Hypothesis cases
through local FastAPI TestClient/SQLite. GET routes and parameter names come from
actual OpenAPI, including CLI/TUI operator reads. Inputs exercise bounded malformed
identifiers/query values and recursively generated telemetry JSON. Successful JSON
responses are validated against their documented schema, including local component
references. Any unhandled exception or unexpected HTTP 5xx fails. Disabled Map routes must
return exactly503/MAP_DISABLED; enabled Map behavior has its own existing suite. Error statuses remain subject
to existing example tests: many current routes do not describe every error in OpenAPI.
This is an explicitly bounded OpenAPI-guided suite, not exhaustive schema generation
or proof of every upload/replay route. Failures include minimized examples/replay blobs.
The short suite runs in normal PR CI; no production URL or external network is used.

`python -m tools.mutation_check --output verification-artifacts/mutation.json`
copies only Git-tracked files to a temporary directory and invokes a fixed pytest
suite. Six stable high-value functions cover identifier validation, timestamp parsing,
hard sensor ranges and confidence. Each mutant negates the first condition of one
function, independently. This small catalogue is a starting strength gate, not a
whole-project mutation coverage score.

The baseline must pass before mutation. Results distinguish KILLED, SURVIVED,
TIMEOUT and ERROR; missing candidates, baseline failure, survivors, errors or timeouts
exit nonzero. Default timeout is 60 seconds per baseline/mutant (configurable5–120),
so seven subprocesses bound the normal run to about seven minutes plus copying.
Timeouts do not count as killed. Each result names path/function/line/operator; fix
survivors with a regression test or review the catalogue if a transformation becomes
equivalent. Never suppress a survivor by relabelling it killed.

The runner does not mutate the source checkout, copy ignored environments/secrets,
or inherit database/cloud settings. Run from a clean committed checkout for exact
revision attribution. Temporary resources close before cleanup, including Windows.
The weekly/manual workflow retains reports on failure and runs on changes to the
mutation/fuzz harness itself. Production data and runtime code are unchanged.
