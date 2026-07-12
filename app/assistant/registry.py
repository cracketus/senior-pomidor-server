from __future__ import annotations

from app.assistant.context import AssistantContextProvider
from app.assistant.contracts import (
    AssistantErrorCode,
    AssistantProvider,
    AssistantProviderError,
    AssistantSessionBootstrap,
    AssistantSessionRequest,
)
from app.assistant.tools import AssistantToolRegistry


class AssistantProviderRegistry:
    def __init__(self, providers: tuple[AssistantProvider, ...], *, active_provider: str | None) -> None:
        self._providers = {provider.name: provider for provider in providers}
        if len(self._providers) != len(providers):
            raise ValueError("assistant provider names must be unique")
        self.active_provider = active_provider

    def get_active(self) -> AssistantProvider:
        if not self.active_provider:
            raise AssistantProviderError(
                AssistantErrorCode.CONFIGURATION,
                "assistant provider is not configured",
                retryable=False,
            )
        provider = self._providers.get(self.active_provider)
        if provider is None:
            raise AssistantProviderError(
                AssistantErrorCode.CONFIGURATION,
                "configured assistant provider is not registered",
                retryable=False,
            )
        return provider


class AssistantService:
    """Provider-independent session orchestration used by the future HTTP API."""

    def __init__(
        self,
        *,
        providers: AssistantProviderRegistry,
        context_provider: AssistantContextProvider,
        tools: AssistantToolRegistry,
    ) -> None:
        self._providers = providers
        self._context_provider = context_provider
        self._tools = tools

    async def create_session(self, request: AssistantSessionRequest) -> AssistantSessionBootstrap:
        provider = self._providers.get_active()
        context = self._context_provider.build_context(request.node_id)
        return await provider.create_session(request, context, self._tools.definitions)

    def execute_tool(self, name: str, *, context_node_id: str, arguments: dict | None = None) -> object:
        context = self._context_provider.build_context(context_node_id)
        return self._tools.execute(name, context, arguments)
