from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.assistant.context_types import AssistantContext
from app.assistant.contracts import AssistantToolDefinition


class AssistantToolError(ValueError):
    pass


@runtime_checkable
class AssistantTool(Protocol):
    @property
    def definition(self) -> AssistantToolDefinition: ...

    def execute(self, context: AssistantContext, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ContextSliceTool:
    definition: AssistantToolDefinition
    context_attribute: str

    def execute(self, context: AssistantContext, arguments: dict[str, Any]) -> Any:
        if arguments:
            raise AssistantToolError(f"{self.definition.name} does not accept arguments")
        return {"node_id": context.node_id, "result": getattr(context, self.context_attribute)}


class AssistantToolRegistry:
    def __init__(self, tools: tuple[AssistantTool, ...]) -> None:
        self._tools = {tool.definition.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("assistant tool names must be unique")

    @property
    def definitions(self) -> tuple[AssistantToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def execute(self, name: str, context: AssistantContext, arguments: dict[str, Any] | None = None) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise AssistantToolError("assistant tool is not allow-listed")
        return tool.execute(context, arguments or {})


def build_default_tools() -> AssistantToolRegistry:
    specs = (
        ("get_current_state", "Fetch the latest stored canonical state for the selected node.", "current_state"),
        ("get_recent_history", "Fetch bounded recent telemetry for the selected node.", "recent_history"),
        ("get_active_anomalies", "Fetch active anomalies for the selected node.", "active_anomalies"),
        ("get_sensor_health", "Fetch the latest stored sensor-health snapshot for the selected node.", "sensor_health"),
        ("get_recent_photos", "Fetch bounded recent photo metadata for the selected node.", "recent_photos"),
    )
    return AssistantToolRegistry(
        tuple(
            ContextSliceTool(AssistantToolDefinition(name=name, description=description), attribute)
            for name, description, attribute in specs
        )
    )
