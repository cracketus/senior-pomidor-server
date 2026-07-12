import asyncio
import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.assistant.api import (
    assistant_rate_limiter,
    assistant_session_store,
    get_realtime_http_client,
)
from app.assistant.context_types import AssistantContext
from app.assistant.contracts import (
    AssistantErrorCode,
    AssistantProviderError,
    AssistantSessionRequest,
    AssistantToolDefinition,
)
from app.assistant.openai_realtime import (
    OpenAIRealtimeProvider,
    RealtimeHTTPResponse,
)
from app.main import app
from app.validation import TELEMETRY_SCHEMA


@pytest.fixture(autouse=True)
def reset_assistant_runtime() -> Generator[None, None, None]:
    assistant_session_store.clear()
    assistant_rate_limiter.clear()
    yield
    assistant_session_store.clear()
    assistant_rate_limiter.clear()
    app.dependency_overrides.pop(get_realtime_http_client, None)


class FakeRealtimeHTTPClient:
    def __init__(self, *, status_code: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[dict[str, Any]] = []

    async def post_json(self, url, *, headers, payload, timeout_seconds) -> RealtimeHTTPResponse:
        self.requests.append({"url": url, "headers": headers, "payload": payload, "timeout_seconds": timeout_seconds})
        body = self.body or {
            "value": "ek_browser_only",
            "expires_at": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            "session": {"id": "sess_provider_123"},
        }
        return RealtimeHTTPResponse(self.status_code, body)


class TimeoutRealtimeHTTPClient(FakeRealtimeHTTPClient):
    async def post_json(self, url, *, headers, payload, timeout_seconds) -> RealtimeHTTPResponse:
        raise TimeoutError


def _telemetry(node_id: str, *, temperature: float) -> dict[str, Any]:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": node_id,
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pods": {"pod-1": {"enabled": True, "air_temperature_c": temperature}},
    }


def _assistant_client(client_factory, fake_http: FakeRealtimeHTTPClient, **settings):
    client = client_factory(
        assistant_provider="planttalk_openai",
        openai_api_key="sk-permanent-server-key",
        **settings,
    )
    app.dependency_overrides[get_realtime_http_client] = lambda: fake_http
    return client


def test_capabilities_are_secret_free_when_enabled(client_factory) -> None:
    client = _assistant_client(client_factory, FakeRealtimeHTTPClient())

    response = client.get("/api/v1/assistant/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "planttalk_openai",
        "modalities": ["text", "audio_input", "audio_output"],
        "transports": ["webrtc"],
        "available": True,
        "unavailable_reason": None,
    }
    assert "sk-permanent-server-key" not in response.text


def test_capabilities_report_disabled_without_provider_credentials(client_factory) -> None:
    client = client_factory(assistant_provider="planttalk_openai", openai_api_key=None)

    response = client.get("/api/v1/assistant/capabilities")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "key" not in response.text.casefold()


def test_session_creation_fails_stably_when_provider_is_disabled(client_factory) -> None:
    client = client_factory(assistant_provider=None, openai_api_key=None)
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-001", temperature=24.0)).status_code == 202

    response = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-001"})

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "configuration",
        "message": "assistant provider is not configured",
        "retryable": False,
    }


def test_session_mints_ephemeral_secret_with_shared_context_and_tools(client_factory) -> None:
    fake_http = FakeRealtimeHTTPClient()
    client = _assistant_client(
        client_factory,
        fake_http,
        assistant_realtime_model="gpt-realtime-test",
        assistant_realtime_voice="cedar",
        assistant_session_ttl_seconds=120,
    )
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-001", temperature=27.5)).status_code == 202

    response = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-001"})

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "planttalk_openai"
    assert body["transport"] == "webrtc"
    assert body["bootstrap"] == {
        "client_secret": "ek_browser_only",
        "realtime_url": "https://api.openai.com/v1/realtime/calls",
        "model": "gpt-realtime-test",
    }
    assert body["session_id"] != "sess_provider_123"
    assert "sk-permanent-server-key" not in response.text

    request = fake_http.requests[0]
    assert request["url"] == "https://api.openai.com/v1/realtime/client_secrets"
    assert request["headers"]["Authorization"] == "Bearer sk-permanent-server-key"
    assert request["headers"]["OpenAI-Safety-Identifier"] != "pi-001"
    session = request["payload"]["session"]
    assert request["payload"]["expires_after"]["seconds"] == 120
    assert session["model"] == "gpt-realtime-test"
    assert session["audio"]["output"]["voice"] == "cedar"
    assert session["tracing"] is None
    assert "pi-001" in session["instructions"]
    assert "27.5" in session["instructions"]
    assert [tool["name"] for tool in session["tools"]] == [
        "get_current_state",
        "get_recent_history",
        "get_active_anomalies",
        "get_sensor_health",
        "get_recent_photos",
    ]


def test_tool_dispatch_is_bound_to_session_node(client_factory) -> None:
    fake_http = FakeRealtimeHTTPClient()
    client = _assistant_client(client_factory, fake_http)
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-001", temperature=24.0)).status_code == 202
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-002", temperature=99.0)).status_code == 202
    session = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-001"}).json()

    response = client.post(
        "/api/v1/assistant/tools/get_recent_history",
        json={"session_id": session["session_id"], "arguments": {}},
    )

    assert response.status_code == 200
    serialized = json.dumps(response.json())
    assert response.json()["data"]["node_id"] == "pi-001"
    assert "24.0" in serialized
    assert "99.0" not in serialized
    assert "pi-002" not in serialized

    override = client.post(
        "/api/v1/assistant/tools/get_recent_history",
        json={"session_id": session["session_id"], "arguments": {"node_id": "pi-002"}},
    )
    assert override.status_code == 404
    assert override.json()["error"]["code"] == "tool_not_allowed"


def test_invalid_node_and_unknown_tool_return_stable_errors(client_factory) -> None:
    fake_http = FakeRealtimeHTTPClient()
    client = _assistant_client(client_factory, fake_http)

    invalid = client.post("/api/v1/assistant/sessions", json={"node_id": "../pi-001"})
    missing = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-404"})

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_node"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "node_not_found"
    assert fake_http.requests == []


def test_authentication_and_rate_limiting_are_stable(client_factory) -> None:
    client = _assistant_client(
        client_factory,
        FakeRealtimeHTTPClient(),
        assistant_bearer_token="lan-secret",
        assistant_rate_limit_requests=1,
    )

    unauthorized = client.get("/api/v1/assistant/capabilities")
    first = client.get("/api/v1/assistant/capabilities", headers={"Authorization": "Bearer lan-secret"})
    limited = client.get("/api/v1/assistant/capabilities", headers={"Authorization": "Bearer lan-secret"})

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"] == {
        "code": "unauthorized",
        "message": "invalid assistant token",
        "retryable": False,
    }
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert limited.json()["error"]["retryable"] is True


def test_expired_and_unknown_sessions_return_stable_errors(client_factory) -> None:
    client = _assistant_client(client_factory, FakeRealtimeHTTPClient())
    expired = assistant_session_store.create(
        provider="planttalk_openai",
        provider_session_id="sess_expired",
        node_id="pi-001",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    expired_response = client.post(
        "/api/v1/assistant/tools/get_current_state",
        json={"session_id": expired.session_id},
    )
    missing_response = client.post(
        "/api/v1/assistant/tools/get_current_state",
        json={"session_id": "unknown-session-id"},
    )

    assert expired_response.status_code == 410
    assert expired_response.json()["error"]["code"] == "expired_session"
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_code"),
    [
        (401, 503, "configuration"),
        (429, 429, "rate_limited"),
        (500, 503, "unavailable"),
        (504, 504, "timeout"),
    ],
)
def test_provider_http_failures_are_normalized(
    client_factory,
    status_code: int,
    expected_status: int,
    expected_code: str,
) -> None:
    fake_http = FakeRealtimeHTTPClient(status_code=status_code, body={"error": {"message": "do not expose me"}})
    client = _assistant_client(client_factory, fake_http)
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-001", temperature=24.0)).status_code == 202

    response = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-001"})

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "do not expose me" not in response.text


def test_provider_timeout_is_normalized(client_factory) -> None:
    client = _assistant_client(client_factory, TimeoutRealtimeHTTPClient())
    assert client.post("/api/v1/edge/telemetry", json=_telemetry("pi-001", temperature=24.0)).status_code == 202

    response = client.post("/api/v1/assistant/sessions", json={"node_id": "pi-001"})

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "timeout",
        "message": "OpenAI Realtime request timed out",
        "retryable": True,
    }


def test_adapter_rejects_malformed_success_response() -> None:
    provider = OpenAIRealtimeProvider(
        api_key="sk-test",
        model="gpt-realtime",
        voice="marin",
        session_ttl_seconds=60,
        timeout_seconds=1,
        http_client=FakeRealtimeHTTPClient(body={"value": "missing-session"}),
    )
    context = AssistantContext("pi-001", datetime.now(UTC), None, (), (), None, ())

    with pytest.raises(AssistantProviderError) as caught:
        asyncio.run(
            provider.create_session(
                AssistantSessionRequest("pi-001"),
                context,
                (AssistantToolDefinition("get_current_state", "Read state"),),
            )
        )

    assert caught.value.code is AssistantErrorCode.UNAVAILABLE
