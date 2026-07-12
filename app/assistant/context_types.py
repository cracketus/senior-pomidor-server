from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AssistantContext:
    """A bounded, selected-node-only projection suitable for any assistant provider."""

    node_id: str
    generated_at: datetime
    current_state: dict[str, Any] | None
    recent_history: tuple[dict[str, Any], ...]
    active_anomalies: tuple[dict[str, Any], ...]
    sensor_health: dict[str, Any] | None
    recent_photos: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "current_state": self.current_state,
            "recent_history": list(self.recent_history),
            "active_anomalies": list(self.active_anomalies),
            "sensor_health": self.sensor_health,
            "recent_photos": list(self.recent_photos),
        }
