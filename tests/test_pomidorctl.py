from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.operator_summary import DecisionsResponse
from app.pomidorctl.cli import main
from app.pomidorctl.client import OperatorClient
from app.pomidorctl.config import Config, ConfigError, build_config
from app.pomidorctl.errors import CLIError
from app.pomidorctl.render import render_human


def test_config_rejects_multiple_token_sources(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("synthetic-token", encoding="utf-8")
    with pytest.raises(ConfigError, match="multiple"):
        build_config(
            token_file=str(token_file), server_url=None, timeout_seconds=None, environ={"POMIDORCTL_TOKEN": "other"}
        )


def test_config_bounds_environment_token() -> None:
    with pytest.raises(ConfigError, match="too large"):
        build_config(
            token_file=None,
            server_url=None,
            timeout_seconds=None,
            environ={"POMIDORCTL_TOKEN": "x" * 8193},
        )


def test_cli_converts_malformed_url_to_bounded_configuration_error(capsys) -> None:
    result = main(["--server-url", "http://[::1", "status"])
    captured = capsys.readouterr()
    assert result == 4
    assert captured.out == ""
    assert "configuration_error: invalid server URL" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("url", ["http://host:bad", "http://host:65536"])
def test_cli_rejects_malformed_url_port(capsys, url) -> None:
    result = main(["--server-url", url, "status"])
    captured = capsys.readouterr()
    assert result == 4
    assert captured.out == ""
    assert captured.err == "configuration_error: invalid server URL\n"


def test_human_decisions_renderer_handles_non_collection_data() -> None:
    response = DecisionsResponse(
        view="decisions",
        request_id="request-206",
        generated_at_utc=datetime.now(UTC),
        status="UNKNOWN",
        availability="NOT_IMPLEMENTED",
        freshness="NOT_APPLICABLE",
        completeness="COMPLETE",
        data={"items": []},
    )
    rendered = render_human(response)
    assert "decisions: status=UNKNOWN" in rendered
    assert "items: 0" in rendered


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["plants", "--limit", "bad"]])
def test_cli_argument_errors_use_stable_usage_contract(arguments, capsys) -> None:
    result = main(arguments)
    captured = capsys.readouterr()
    assert result == 4
    assert captured.out == ""
    assert captured.err == "configuration_error: invalid command-line arguments\n"


def test_cli_argument_errors_support_json_output(capsys) -> None:
    result = main(["--json", "plants", "--limit", "bad"])
    captured = capsys.readouterr()
    assert result == 4
    assert captured.err == ""
    assert '"schema_version":"senior-pomidor.pomidorctl-error.v1"' in captured.out
    assert '"error_code":"configuration_error"' in captured.out


def test_client_validates_contract_and_maps_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/operator/decisions"
        return httpx.Response(401, headers={"content-type": "application/json"}, json={"detail": "secret"})

    client = OperatorClient(
        Config("http://127.0.0.1:8000", 5, "synthetic-token"), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(CLIError) as caught:
        client.request("decisions")
    assert caught.value.exit_code == 5
    assert "synthetic-token" not in json.dumps(caught.value.payload.model_dump())
    assert "secret" not in json.dumps(caught.value.payload.model_dump())


def test_client_rejects_extra_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"schema_version": "wrong"})

    client = OperatorClient(Config("http://127.0.0.1:8000", 5, None), transport=httpx.MockTransport(handler))
    with pytest.raises(CLIError) as caught:
        client.request("status")
    assert caught.value.exit_code == 7
    assert caught.value.payload.error_code == "contract_mismatch"


def test_client_rejects_naive_operator_timestamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "schema_version": "senior-pomidor.operator.v1",
                "view": "plants",
                "request_id": "request-206",
                "generated_at_utc": "2026-09-11T12:00:00",
                "status": "OK",
                "availability": "UNAVAILABLE",
                "freshness": "UNKNOWN",
                "completeness": "COMPLETE",
                "reasons": [],
                "data": {"items": [], "returned_count": 0, "has_more": False},
            },
        )

    client = OperatorClient(Config("http://127.0.0.1:8000", 5, None), transport=httpx.MockTransport(handler))
    with pytest.raises(CLIError) as caught:
        client.request("plants")
    assert caught.value.exit_code == 7
    assert caught.value.payload.error_code == "contract_mismatch"


def test_fastapi_operator_boundary_round_trips_through_client(client_factory) -> None:
    api_client = client_factory()

    class FastAPIBridge(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            response = api_client.request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=request.content,
            )
            return httpx.Response(
                response.status_code,
                headers=dict(response.headers),
                content=response.content,
                request=request,
            )

    with OperatorClient(Config("http://operator.test", 5, None), transport=FastAPIBridge()) as operator:
        response = operator.request("decisions")

    assert isinstance(response, DecisionsResponse)
    assert response.model_dump(mode="json")["schema_version"] == "senior-pomidor.operator.v1"
