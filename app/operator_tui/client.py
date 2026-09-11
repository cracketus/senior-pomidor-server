from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx

from app.pomidorctl.client import OperatorClient
from app.pomidorctl.config import Config
from app.pomidorctl.errors import CLIError

ViewName = Literal["status", "plants", "edge", "decisions", "anomalies", "photos"]
VIEWS: tuple[ViewName, ...] = ("status", "plants", "edge", "decisions", "anomalies", "photos")


@dataclass(frozen=True)
class ViewResult:
    view: ViewName
    payload: dict[str, Any] | None
    error: str | None
    fetched_at_utc: datetime
    last_success_at_utc: datetime | None = None

    @property
    def is_last_known(self) -> bool:
        return self.error is not None and self.payload is not None


@dataclass(frozen=True)
class OperatorSnapshot:
    views: dict[ViewName, ViewResult] = field(default_factory=dict)

    def result(self, view: ViewName) -> ViewResult | None:
        return self.views.get(view)

    def merge(self, incoming: OperatorSnapshot) -> OperatorSnapshot:
        merged: dict[ViewName, ViewResult] = {}
        for view in VIEWS:
            new = incoming.result(view)
            old = self.result(view)
            if new is None:
                if old is not None:
                    merged[view] = old
                continue
            if new.payload is None and new.error is not None and old is not None and old.payload is not None:
                merged[view] = ViewResult(
                    view=view,
                    payload=old.payload,
                    error=new.error,
                    fetched_at_utc=new.fetched_at_utc,
                    last_success_at_utc=old.last_success_at_utc or old.fetched_at_utc,
                )
            else:
                merged[view] = new
        return OperatorSnapshot(merged)

    @classmethod
    def failed(cls, error: str) -> OperatorSnapshot:
        now = datetime.now(UTC)
        return cls({view: ViewResult(view, None, error, now) for view in VIEWS})


class OperatorDataSource(Protocol):
    async def fetch_all(self) -> OperatorSnapshot: ...

    async def aclose(self) -> None: ...


class PomidorCtlOperatorSource:
    """Async adapter over the canonical read-only pomidorctl client."""

    def __init__(self, config: Config, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport

    def _fetch_sync(self) -> OperatorSnapshot:
        now = datetime.now(UTC)
        results: dict[ViewName, ViewResult] = {}
        with OperatorClient(self.config, transport=self.transport) as client:
            for view in VIEWS:
                fetched = datetime.now(UTC)
                try:
                    response = client.request(view)
                    results[view] = ViewResult(
                        view=view,
                        payload=response.model_dump(mode="json"),
                        error=None,
                        fetched_at_utc=fetched,
                        last_success_at_utc=fetched,
                    )
                except CLIError as exc:
                    results[view] = ViewResult(
                        view=view,
                        payload=None,
                        error=f"{exc.payload.error_code}: {exc.payload.message}",
                        fetched_at_utc=fetched,
                    )
        return OperatorSnapshot(results or {view: ViewResult(view, None, "no data", now) for view in VIEWS})

    async def fetch_all(self) -> OperatorSnapshot:
        return await asyncio.to_thread(self._fetch_sync)

    async def aclose(self) -> None:
        return None


class DemoOperatorSource:
    """Secret-free synthetic source for tests, docs, and public captures."""

    async def fetch_all(self) -> OperatorSnapshot:
        await asyncio.sleep(0)
        now = datetime.now(UTC)
        ts = now.isoformat().replace("+00:00", "Z")

        def envelope(view: str, data: dict[str, Any], **overrides: Any) -> dict[str, Any]:
            payload = {
                "schema_version": "senior-pomidor.operator.v1",
                "view": view,
                "request_id": f"demo-{view}",
                "generated_at_utc": ts,
                "status": "WARN",
                "availability": "AVAILABLE",
                "freshness": "FRESH",
                "completeness": "COMPLETE",
                "reasons": [],
                "data": data,
            }
            payload.update(overrides)
            return payload

        state = {
            "state_id": "demo-state-001",
            "node_id": "demo-balcony-node",
            "observed_at_utc": ts,
            "status": "WARN",
            "confidence": 0.92,
            "env": {"air_temp_c": 28.2, "rh_pct": 54.0, "vpd_kpa": 1.72, "lux": 32100.0},
            "soil": {
                "temp_c": 22.1,
                "probes": [
                    {
                        "id": "P1",
                        "position": "top",
                        "moisture_pct": 31.2,
                        "dry_threshold_pct": 24.0,
                        "confidence": 0.94,
                        "status": "OK",
                    }
                ],
            },
            "plant": {"leaf_temp_c": 27.4},
        }
        node = {
            "node_id": "demo-balcony-node",
            "observed_at_utc": ts,
            "state_id": "demo-state-001",
            "pods": [
                {
                    "pod_key": "pod-a",
                    "plant_id": None,
                    "plant_identity_status": "UNKNOWN",
                    "enabled": True,
                    "observed_at_utc": ts,
                    "metrics": {
                        "soil_moisture_percent": 36.4,
                        "soil_temperature_c": 22.1,
                        "air_temperature_c": 28.2,
                        "air_humidity_percent": 54.0,
                        "air_vpd_kpa": 1.72,
                        "light_lux": 32100.0,
                    },
                }
            ],
        }
        edge = {
            "device_id": "demo-edge-01",
            "status": "WARN",
            "freshness": {"status": "FRESH", "age_seconds": 4.0},
            "application": {"status": "OK", "process_running": True, "process_uptime_seconds": 86400},
            "watchdog": {"status": "OK", "restart_count": 0, "reboot_count": 0},
            "spool": {
                "status": "WARN",
                "pending_count": 3,
                "backlog_count": 3,
                "dead_letter_count": 0,
                "oldest_pending_age_seconds": 87,
                "disk_usage_percent": 41.0,
            },
            "reasons": [{"status": "WARN", "code": "demo_backlog", "message": "Synthetic queued telemetry"}],
        }
        anomaly = {
            "anomaly_id": "demo-anomaly-001",
            "node_id": "demo-balcony-node",
            "type": "HIGH_VPD",
            "status": "ACTIVE",
            "severity": "WARN",
            "observed_at_utc": ts,
            "state_id": "demo-state-001",
        }
        photo = {
            "photo_id": "demo-photo-001",
            "node_id": "demo-balcony-node",
            "captured_at_utc": ts,
            "content_type": "image/jpeg",
            "file_size_bytes": 184223,
            "sha256": "0" * 64,
            "sharpness_score": 0.84,
        }
        payloads: dict[ViewName, dict[str, Any]] = {
            "status": envelope(
                "status",
                {
                    "host": {"status": "UNKNOWN", "availability": "UNAVAILABLE", "freshness": "UNKNOWN"},
                    "nodes": [node],
                    "state": state,
                    "edge": [edge],
                    "decisions": "NOT_IMPLEMENTED",
                },
            ),
            "plants": envelope("plants", {"items": [node], "returned_count": 1, "has_more": False}),
            "edge": envelope("edges", {"items": [edge], "returned_count": 1, "has_more": False}),
            "decisions": envelope(
                "decisions",
                {"items": []},
                status="UNKNOWN",
                availability="NOT_IMPLEMENTED",
                freshness="NOT_APPLICABLE",
            ),
            "anomalies": envelope("anomalies", {"items": [anomaly], "returned_count": 1, "has_more": False}),
            "photos": envelope(
                "photos",
                {"items": [photo], "returned_count": 1, "has_more": False},
                status="OK",
            ),
        }
        return OperatorSnapshot(
            {
                view: ViewResult(view, payload, None, now, now)
                for view, payload in payloads.items()
            }
        )

    async def aclose(self) -> None:
        return None
