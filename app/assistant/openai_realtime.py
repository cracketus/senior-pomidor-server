from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.assistant.context_types import AssistantContext
from app.assistant.contracts import (
    AssistantCapabilities,
    AssistantErrorCode,
    AssistantModality,
    AssistantProviderError,
    AssistantSessionBootstrap,
    AssistantSessionRequest,
    AssistantToolDefinition,
    AssistantTransportCapability,
)

PLANTTALK_OPENAI_PROVIDER = "planttalk_openai"


@dataclass(frozen=True)
class RealtimeHTTPResponse:
    status_code: int
    body: dict[str, Any]


class RealtimeHTTPClient(Protocol):
    async def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> RealtimeHTTPResponse: ...


class UrllibRealtimeHTTPClient:
    async def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> RealtimeHTTPResponse:
        return await asyncio.to_thread(
            self._post_json,
            url,
            headers=headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _post_json(
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> RealtimeHTTPResponse:
        request = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310  # nosec B310
                return RealtimeHTTPResponse(response.status, _decode_json(response.read()))
        except urllib.error.HTTPError as exc:
            return RealtimeHTTPResponse(exc.code, _decode_json(exc.read()))
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError from exc
            raise OSError("OpenAI Realtime request failed") from exc


class OpenAIRealtimeProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        voice: str,
        session_ttl_seconds: int,
        timeout_seconds: float,
        http_client: RealtimeHTTPClient,
        api_base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.voice = voice
        self.session_ttl_seconds = session_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self.api_base_url = api_base_url.rstrip("/")
        parsed = urllib.parse.urlparse(self.api_base_url)
        if parsed.scheme != "https" or parsed.hostname != "api.openai.com":
            raise ValueError("OpenAI API base URL must use https://api.openai.com")

    @property
    def name(self) -> str:
        return PLANTTALK_OPENAI_PROVIDER

    def capabilities(self) -> AssistantCapabilities:
        configured = bool(self._api_key and self.model and self.voice)
        return AssistantCapabilities(
            provider=self.name,
            modalities=(AssistantModality.TEXT, AssistantModality.AUDIO_INPUT, AssistantModality.AUDIO_OUTPUT),
            transports=(AssistantTransportCapability.WEBRTC,),
            available=configured,
            unavailable_reason=None if configured else "provider is not configured",
        )

    async def create_session(
        self,
        request: AssistantSessionRequest,
        context: AssistantContext,
        tools: tuple[AssistantToolDefinition, ...],
    ) -> AssistantSessionBootstrap:
        if not self._api_key or not self.model or not self.voice:
            raise AssistantProviderError(
                AssistantErrorCode.CONFIGURATION,
                "OpenAI Realtime provider is not configured",
                retryable=False,
            )
        payload = {
            "expires_after": {"anchor": "created_at", "seconds": self.session_ttl_seconds},
            "session": {
                "type": "realtime",
                "model": self.model,
                "instructions": build_planttalk_instructions(context),
                "output_modalities": ["audio"],
                "audio": {"output": {"voice": self.voice}},
                "tools": [_openai_tool(tool) for tool in tools],
                "tool_choice": "auto",
                "tracing": None,
            },
        }
        try:
            response = await self._http_client.post_json(
                f"{self.api_base_url}/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Safety-Identifier": hashlib.sha256(request.node_id.encode()).hexdigest(),
                },
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise AssistantProviderError(
                AssistantErrorCode.TIMEOUT, "OpenAI Realtime request timed out", retryable=True
            ) from exc
        except OSError as exc:
            raise AssistantProviderError(
                AssistantErrorCode.UNAVAILABLE, "OpenAI Realtime is unavailable", retryable=True
            ) from exc

        _raise_for_status(response.status_code)
        secret = response.body.get("value")
        expires_at = response.body.get("expires_at")
        session = response.body.get("session")
        session_id = session.get("id") if isinstance(session, dict) else None
        if not isinstance(secret, str) or not isinstance(expires_at, int | float) or not isinstance(session_id, str):
            raise AssistantProviderError(
                AssistantErrorCode.UNAVAILABLE,
                "OpenAI Realtime returned an invalid session",
                retryable=True,
            )
        expiry = datetime.fromtimestamp(expires_at, tz=UTC)
        return AssistantSessionBootstrap(
            provider=self.name,
            session_id=session_id,
            expires_at=expiry,
            transport=AssistantTransportCapability.WEBRTC,
            bootstrap={
                "client_secret": secret,
                "realtime_url": f"{self.api_base_url}/realtime/calls",
                "model": self.model,
            },
        )


def build_planttalk_instructions(context: AssistantContext) -> str:
    context_json = json.dumps(context.as_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (
        "You are PlantTalk, the Senior Pomidor plant assistant. Be concise, practical, and transparent about "
        "uncertainty. Ground every plant-specific claim in the selected node context or a read-only tool result. "
        "Never claim to change watering, hardware, configuration, or stored data. Never request or reveal secrets, "
        "credentials, private paths, or data from another node. If evidence is missing or stale, say so. Voice and "
        "typed turns use this same persona and context.\n\nSelected node context:\n"
        f"{context_json}"
    )


def _openai_tool(tool: AssistantToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


def _decode_json(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _raise_for_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 429:
        raise AssistantProviderError(
            AssistantErrorCode.RATE_LIMITED,
            "OpenAI Realtime rate limit reached",
            retryable=True,
        )
    if status_code in {408, 504}:
        raise AssistantProviderError(AssistantErrorCode.TIMEOUT, "OpenAI Realtime request timed out", retryable=True)
    if status_code in {400, 401, 403, 404, 422}:
        raise AssistantProviderError(
            AssistantErrorCode.CONFIGURATION,
            "OpenAI Realtime rejected the configured session",
            retryable=False,
        )
    raise AssistantProviderError(AssistantErrorCode.UNAVAILABLE, "OpenAI Realtime is unavailable", retryable=True)
