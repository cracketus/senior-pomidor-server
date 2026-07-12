from __future__ import annotations

import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.assistant.context import AssistantContextError, SqlAlchemyAssistantContextProvider
from app.assistant.contracts import AssistantErrorCode, AssistantProviderError, AssistantSessionRequest
from app.assistant.openai_realtime import (
    PLANTTALK_OPENAI_PROVIDER,
    OpenAIRealtimeProvider,
    RealtimeHTTPClient,
    UrllibRealtimeHTTPClient,
)
from app.assistant.registry import AssistantProviderRegistry, AssistantService
from app.assistant.session import (
    AssistantSessionExpiredError,
    AssistantSessionNotFoundError,
    AssistantSessionStore,
    FixedWindowRateLimiter,
)
from app.assistant.tools import AssistantToolError, build_default_tools
from app.config import Settings, get_settings
from app.db import get_db

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])
assistant_session_store = AssistantSessionStore()
assistant_rate_limiter = FixedWindowRateLimiter(clock=time.monotonic)
_default_http_client = UrllibRealtimeHTTPClient()


class AssistantAPIError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class CreateAssistantSessionRequest(BaseModel):
    node_id: str


class ExecuteAssistantToolRequest(BaseModel):
    session_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def get_realtime_http_client() -> RealtimeHTTPClient:
    return _default_http_client


@router.get("/capabilities")
def assistant_capabilities(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
    http_client: RealtimeHTTPClient = Depends(get_realtime_http_client),
) -> dict[str, Any]:
    _authorize_and_limit(request, authorization, settings)
    provider = _build_openai_provider(settings, http_client)
    if settings.assistant_provider != PLANTTALK_OPENAI_PROVIDER:
        return {
            "provider": settings.assistant_provider,
            "modalities": [],
            "transports": [],
            "available": False,
            "unavailable_reason": "assistant provider is not configured",
        }
    capabilities = provider.capabilities()
    return {
        "provider": capabilities.provider,
        "modalities": [item.value for item in capabilities.modalities],
        "transports": [item.value for item in capabilities.transports],
        "available": capabilities.available,
        "unavailable_reason": capabilities.unavailable_reason,
    }


@router.post("/sessions", status_code=201)
async def create_assistant_session(
    payload: CreateAssistantSessionRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    http_client: RealtimeHTTPClient = Depends(get_realtime_http_client),
) -> dict[str, Any]:
    _authorize_and_limit(request, authorization, settings)
    service = _build_service(db, settings, http_client)
    try:
        bootstrap = await service.create_session(AssistantSessionRequest(node_id=payload.node_id))
    except AssistantContextError as exc:
        message = str(exc)
        status_code = 404 if message == "device not found" else 400
        code = "node_not_found" if status_code == 404 else "invalid_node"
        raise AssistantAPIError(status_code, code, message) from exc
    except AssistantProviderError as exc:
        raise _provider_api_error(exc) from exc

    now = datetime.now(UTC)
    if bootstrap.expires_at <= now:
        raise AssistantAPIError(410, AssistantErrorCode.EXPIRED_SESSION.value, "assistant session expired")
    expires_at = min(bootstrap.expires_at, now + timedelta(seconds=settings.assistant_session_ttl_seconds))
    record = assistant_session_store.create(
        provider=bootstrap.provider,
        provider_session_id=bootstrap.session_id,
        node_id=payload.node_id,
        expires_at=expires_at,
    )
    return {
        "session_id": record.session_id,
        "provider": bootstrap.provider,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "transport": bootstrap.transport.value,
        "bootstrap": bootstrap.bootstrap,
    }


@router.post("/tools/{tool_name}")
def execute_assistant_tool(
    tool_name: str,
    payload: ExecuteAssistantToolRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _authorize_and_limit(request, authorization, settings)
    try:
        record = assistant_session_store.get(payload.session_id)
    except AssistantSessionExpiredError as exc:
        raise AssistantAPIError(410, AssistantErrorCode.EXPIRED_SESSION.value, str(exc)) from exc
    except AssistantSessionNotFoundError as exc:
        raise AssistantAPIError(404, "session_not_found", str(exc)) from exc
    context_provider = SqlAlchemyAssistantContextProvider(db)
    service = AssistantService(
        providers=AssistantProviderRegistry((), active_provider=None),
        context_provider=context_provider,
        tools=build_default_tools(),
    )
    try:
        result = service.execute_tool(tool_name, context_node_id=record.node_id, arguments=payload.arguments)
    except AssistantToolError as exc:
        raise AssistantAPIError(404, "tool_not_allowed", str(exc)) from exc
    except AssistantContextError as exc:
        raise AssistantAPIError(404, "node_not_found", str(exc)) from exc
    return {"session_id": record.session_id, "tool_name": tool_name, "data": result}


def _build_service(
    db: Session,
    settings: Settings,
    http_client: RealtimeHTTPClient,
) -> AssistantService:
    provider = _build_openai_provider(settings, http_client)
    providers = (provider,) if settings.assistant_provider == PLANTTALK_OPENAI_PROVIDER else ()
    return AssistantService(
        providers=AssistantProviderRegistry(providers, active_provider=settings.assistant_provider),
        context_provider=SqlAlchemyAssistantContextProvider(db),
        tools=build_default_tools(),
    )


def _build_openai_provider(settings: Settings, http_client: RealtimeHTTPClient) -> OpenAIRealtimeProvider:
    return OpenAIRealtimeProvider(
        api_key=settings.openai_api_key,
        model=settings.assistant_realtime_model,
        voice=settings.assistant_realtime_voice,
        session_ttl_seconds=settings.assistant_session_ttl_seconds,
        timeout_seconds=settings.assistant_provider_timeout_seconds,
        http_client=http_client,
    )


def _authorize_and_limit(request: Request, authorization: str | None, settings: Settings) -> None:
    expected = settings.assistant_bearer_token
    if expected:
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
            raise AssistantAPIError(401, "unauthorized", "invalid assistant token")
        if not hmac.compare_digest(authorization[len(prefix) :], expected):
            raise AssistantAPIError(401, "unauthorized", "invalid assistant token")
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    if not assistant_rate_limiter.allow(
        key,
        limit=settings.assistant_rate_limit_requests,
        window_seconds=settings.assistant_rate_limit_window_seconds,
    ):
        raise AssistantAPIError(429, "rate_limited", "assistant rate limit reached", retryable=True)


def _provider_api_error(error: AssistantProviderError) -> AssistantAPIError:
    status_codes = {
        AssistantErrorCode.CONFIGURATION: 503,
        AssistantErrorCode.UNAVAILABLE: 503,
        AssistantErrorCode.TIMEOUT: 504,
        AssistantErrorCode.RATE_LIMITED: 429,
        AssistantErrorCode.EXPIRED_SESSION: 410,
    }
    return AssistantAPIError(status_codes[error.code], error.code.value, str(error), retryable=error.retryable)
