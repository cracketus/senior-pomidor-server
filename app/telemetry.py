from typing import Any

from app.validation import KNOWN_METRICS


def iter_pods(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pods = payload.get("pods") or payload.get("pod_readings") or []
    if isinstance(pods, dict):
        return [dict(value, pod_key=key) if isinstance(value, dict) else {"pod_key": key} for key, value in pods.items()]
    if isinstance(pods, list):
        return [pod for pod in pods if isinstance(pod, dict)]
    return []


def pod_key(pod: dict[str, Any], index: int) -> str:
    value = pod.get("pod_key") or pod.get("pod") or pod.get("key") or pod.get("id") or f"pod_{index + 1}"
    return str(value)


def pod_enabled(pod: dict[str, Any]) -> bool:
    value = pod.get("enabled")
    return bool(value) if value is not None else True


def pod_metrics(pod: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, float]]:
    metrics = pod.get("metrics") if isinstance(pod.get("metrics"), dict) else pod
    known: dict[str, float | None] = {metric: None for metric in KNOWN_METRICS}
    unknown: dict[str, float] = {}
    for key, value in metrics.items():
        if key in {"pod_key", "pod", "key", "id", "enabled", "metrics", "errors"}:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if key in KNOWN_METRICS:
            known[key] = float(value)
        else:
            unknown[key] = float(value)
    return known, unknown


def iter_pod_errors(payload: dict[str, Any], pod: dict[str, Any], pod_key_value: str) -> list[dict[str, str | None]]:
    errors = pod.get("errors") if isinstance(pod.get("errors"), list) else []
    result: list[dict[str, str | None]] = []
    for error in errors:
        if isinstance(error, str):
            result.append({"pod_key": pod_key_value, "sensor": None, "message": error})
        elif isinstance(error, dict):
            message = error.get("message") or error.get("error")
            if message:
                result.append(
                    {
                        "pod_key": str(error.get("pod_key") or pod_key_value),
                        "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
                        "message": str(message),
                    }
                )

    root_errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    for error in root_errors:
        if not isinstance(error, dict):
            continue
        error_pod_key = str(error.get("pod_key") or error.get("pod") or "")
        if error_pod_key != pod_key_value:
            continue
        message = error.get("message") or error.get("error")
        if message:
            result.append(
                {
                    "pod_key": pod_key_value,
                    "sensor": str(error["sensor"]) if error.get("sensor") is not None else None,
                    "message": str(message),
                }
            )
    return result
