from __future__ import annotations


def sensor_confidence(status: str, *, required: bool = False) -> float:
    if status == "OK":
        return 0.9
    if status in {"WARN", "JUMP"}:
        return 0.55
    if status == "UNCALIBRATED":
        return 0.3
    if status == "NOT_PRESENT" and not required:
        return 0.0
    return 0.0


def quality_level(confidence: float) -> str:
    if confidence >= 0.85:
        return "GOOD"
    if confidence >= 0.65:
        return "DEGRADED"
    if confidence >= 0.40:
        return "LOW_CONFIDENCE"
    return "UNSAFE_FOR_AUTONOMY"
