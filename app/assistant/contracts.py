from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.assistant.context_types import AssistantContext


class AssistantModality(StrEnum):
    TEXT = "text"
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"


class AssistantTransportCapability(StrEnum):
    HTTP = "http"
    WEBRTC = "webrtc"
    WEBSOCKET = "websocket"


class AssistantErrorCode(StrEnum):
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CONFIGURATION = "configuration"
    EXPIRED_SESSION = "expired_session"


class AssistantProviderError(RuntimeError):
    """Stable provider failure that is safe for API orchestration to inspect."""

    def __init__(self, code: AssistantErrorCode, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class AssistantCapabilities:
    provider: str
    modalities: tuple[AssistantModality, ...]
    transports: tuple[AssistantTransportCapability, ...]
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class AssistantToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False}
    )


@dataclass(frozen=True)
class AssistantSessionRequest:
    node_id: str


@dataclass(frozen=True)
class AssistantSessionBootstrap:
    provider: str
    session_id: str
    expires_at: datetime
    transport: AssistantTransportCapability
    bootstrap: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AssistantProvider(Protocol):
    """Provider port. Provider-specific models and failures stop at this boundary."""

    @property
    def name(self) -> str: ...

    def capabilities(self) -> AssistantCapabilities: ...

    async def create_session(
        self,
        request: AssistantSessionRequest,
        context: AssistantContext,
        tools: tuple[AssistantToolDefinition, ...],
    ) -> AssistantSessionBootstrap: ...
