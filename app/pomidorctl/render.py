from __future__ import annotations

from typing import Any

from app.pomidorctl.errors import CLIErrorPayload


def exit_code(response: Any) -> int:
    return {"OK": 0, "WARN": 1, "ALERT": 2, "UNKNOWN": 3}[response.status.value]


def render_json(response: Any) -> str:
    return response.model_dump_json()


def render_human(response: Any, *, verbose: bool = False) -> str:
    lines = [
        f"{response.view}: status={response.status.value} availability={response.availability.value} "
        f"freshness={response.freshness.value} completeness={response.completeness.value}"
    ]
    data = response.data.model_dump(mode="json")
    if response.view == "status":
        lines.append(
            f"nodes: {len(data['nodes'])}; edge: {len(data['edge'])}; state: {'present' if data['state'] else '-'}"
        )
    elif response.view == "decisions":
        lines.append(f"items: {len(data['items'])}")
    elif "items" in data:
        lines.append(f"items: {data['returned_count']} (has_more={data['has_more']})")
        for item in data["items"]:
            identifier = item.get("node_id", item.get("device_id", item.get("photo_id", item.get("anomaly_id", "-"))))
            lines.append(f"- {identifier}")
    if verbose and response.reasons:
        lines.extend(f"reason {reason.code}: {reason.message}" for reason in response.reasons)
    return "\n".join(lines)


def render_error(error: CLIErrorPayload) -> str:
    return error.model_dump_json()
