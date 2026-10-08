"""Validate bounded offline JSONL telemetry readback without publishing raw rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.validation import ValidationError, parse_utc_z, validate_device_id, validate_record_id

# Scientific plausibility bounds in the stored API's explicit units. Not calibration.
RANGES = {
    "air_temperature_c": (-20, 60),
    "air_humidity_percent": (0, 100),
    "soil_moisture_percent": (0, 100),
    "soil_temperature_c": (-10, 50),
    "leaf_temp_c": (-20, 70),
    "light_lux": (0, 150000),
    "air_vpd_kpa": (0, 20),
    "leaf_vpd_kpa": (-20, 20),
}
MAX_ROWS = 10000
MAX_LINE = 262144


def inspect_rows(rows: list[Any], *, expected_interval_seconds: int | None = None) -> dict:
    if len(rows) > MAX_ROWS:
        raise ValueError("row_limit")
    if expected_interval_seconds is not None and not 1 <= expected_interval_seconds <= 86400:
        raise ValueError("invalid_cadence")
    findings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    records: set[str] = set()
    observations: set[tuple] = set()
    previous: dict[str, datetime] = {}
    timeline: dict[str, set[datetime]] = {}

    def flag(row: int, code: str) -> None:
        counts[code] += 1
        if len(findings) < 500:
            findings.append({"row": row, "code": code})

    if not rows:
        flag(0, "empty_input")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            flag(index, "invalid_row")
            continue
        try:
            device = validate_device_id(row.get("device_id"))
            observed = parse_utc_z(row.get("timestamp_utc", ""))
            received = parse_utc_z(row.get("received_at", ""))
        except (ValidationError, TypeError, OverflowError):
            flag(index, "invalid_identity_or_time")
            continue
        record = row.get("record_id")
        if record is not None:
            try:
                record = validate_record_id(record)
            except ValidationError:
                flag(index, "invalid_record_id")
                continue
            if record in records:
                flag(index, "duplicate_record_id")
            records.add(record)
        else:
            counts["legacy_without_record_id"] += 1
        schema = row.get("schema_version")
        if not isinstance(schema, str) or schema not in {
            "senior-pomidor.edge.telemetry.v1",
            "senior-pomidor.edge.telemetry.v2",
        }:
            flag(index, "unsupported_schema")
            continue
        identity = (device, observed, schema)
        if identity in observations:
            flag(index, "duplicate_observation")
        observations.add(identity)
        if observed > received:
            flag(index, "observation_after_receive")
        if device in previous and observed < previous[device]:
            flag(index, "out_of_order")
        previous[device] = observed
        timeline.setdefault(device, set()).add(observed)
        readings = row.get("readings")
        if not isinstance(readings, list):
            flag(index, "invalid_readings")
            continue
        for reading in readings:
            if not isinstance(reading, dict) or not isinstance(reading.get("metrics"), dict):
                flag(index, "invalid_readings")
                continue
            for name, (low, high) in RANGES.items():
                value = reading["metrics"].get(name)
                if value is None:
                    counts["missing_metric_values"] += 1
                elif (
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or (isinstance(value, float) and not math.isfinite(value))
                ):
                    flag(index, "invalid_metric_value")
                elif not low <= value <= high:
                    flag(index, "out_of_range_metric")
    gaps = None
    if expected_interval_seconds is not None:
        gaps = sum(
            max(0, math.ceil((right - left).total_seconds() / expected_interval_seconds) - 1)
            for times in timeline.values()
            for left, right in zip(sorted(times), sorted(times)[1:], strict=False)
        )
    return {
        "schema_version": "senior-pomidor.dataset-quality.v1",
        "status": "FAIL" if findings else "PASS",
        "row_count": len(rows),
        "counts": dict(sorted(counts.items())),
        "findings": findings,
        "findings_truncated": sum(
            v for k, v in counts.items() if k not in {"legacy_without_record_id", "missing_metric_values"}
        )
        > 500,
        "expected_interval_seconds": expected_interval_seconds,
        "estimated_missing_observations": gaps,
        "evidence_scope": "OFFLINE_INPUT_ONLY",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected-interval-seconds", type=int)
    args = parser.parse_args(argv)
    rows: list[Any] = []
    digest = hashlib.sha256()
    try:
        with args.input.open("rb") as source:
            while line := source.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE or len(rows) >= MAX_ROWS:
                    raise ValueError("input_limit")
                digest.update(line)
                rows.append(json.loads(line))
        report = inspect_rows(rows, expected_interval_seconds=args.expected_interval_seconds)
        report["input_sha256"] = digest.hexdigest()
    except (OSError, ValueError, UnicodeError, RecursionError):
        # Never print exception text, private path or raw malformed input.
        print(
            json.dumps(
                {
                    "schema_version": "senior-pomidor.dataset-quality-error.v1",
                    "status": "FAIL",
                    "code": "invalid_or_unavailable_input",
                }
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
