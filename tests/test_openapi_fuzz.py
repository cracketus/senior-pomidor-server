"""OpenAPI-guided, reproducible fuzzing through actual in-process HTTP routes."""

import json
from urllib.parse import quote

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from app.main import app

SPEC = app.openapi()
GET_ROUTES = [
    (path, operation)
    for path, methods in SPEC["paths"].items()
    for method, operation in methods.items()
    if method == "get" and path.startswith("/api/v1/")
]
FUZZ = settings(
    max_examples=12,
    derandomize=True,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
VALUE = st.one_of(
    st.sampled_from(["", "..", "invalid", "0", "-1", "1000000", "2026-09-01T00:00:00Z"]),
    st.text(alphabet="abcXYZ0123-_:.", max_size=40),
)
JSON_VALUE = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-1000, max_value=1000) | st.text(max_size=30),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=15), children, max_size=4),
    max_leaves=12,
)


def assert_response(response, operation):
    assert response.status_code < 500, response.text[:1000]
    if response.status_code < 300:
        contract = operation["responses"].get(str(response.status_code))
        assert contract is not None, "successful status missing from OpenAPI"
        schema = contract.get("content", {}).get("application/json", {}).get("schema")
        if schema is not None:
            Draft202012Validator({**schema, "components": SPEC.get("components", {})}).validate(response.json())


@pytest.mark.parametrize(("path", "operation"), GET_ROUTES, ids=[path for path, _ in GET_ROUTES])
@FUZZ
@given(data=st.data())
def test_documented_get_routes_never_crash(client, path, operation, data):
    query = {}
    for parameter in operation.get("parameters", []):
        value = data.draw(VALUE, label=parameter["name"])
        if parameter["in"] == "path":
            # An empty identifier changes route matching; still exercise bounded
            # malformed identifiers without escaping the local route.
            path = path.replace("{" + parameter["name"] + "}", quote(value or "missing", safe="").replace(".", "%2E"))
        elif parameter["in"] == "query":
            query[parameter["name"]] = value
    response = client.get(path, params=query)
    if path.startswith("/api/v1/map/") and response.status_code == 503:
        # This deployment intentionally disables Map; distinguish its documented
        # fail-closed response from an unexpected server failure.
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MAP_DISABLED"
    else:
        assert_response(response, operation)


@FUZZ
@given(payload=JSON_VALUE)
def test_telemetry_arbitrary_json_never_crashes(client, payload):
    operation = SPEC["paths"]["/api/v1/edge/telemetry"]["post"]
    response = client.post(
        "/api/v1/edge/telemetry", content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )
    assert_response(response, operation)
