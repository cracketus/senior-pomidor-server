from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import httpx
from textual.widgets import ContentSwitcher

from app.operator_tui.app import OperatorConsole
from app.operator_tui.client import DemoOperatorSource, OperatorSnapshot, PomidorCtlOperatorSource
from app.operator_tui.presenter import connection_summary, render_overview, render_plants
from app.pomidorctl.config import Config


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


def config() -> Config:
    return Config(server_url="http://example.test", timeout_seconds=1.0, token=None)


def test_pomidorctl_source_uses_only_get_and_preserves_errors() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(503, json={"detail": "synthetic outage"})

    source = PomidorCtlOperatorSource(config(), transport=httpx.MockTransport(handler))
    snapshot = run(source.fetch_all())
    status = snapshot.result("status")
    assert methods
    assert set(methods) == {"GET"}
    assert status is not None
    assert status.payload is None
    assert "api_unavailable" in (status.error or "")


def test_snapshot_retains_last_known_payload_but_marks_transport_stale() -> None:
    first = run(DemoOperatorSource().fetch_all())
    merged = first.merge(OperatorSnapshot.failed("connection error"))
    status = merged.result("status")
    assert status is not None
    assert status.payload is not None
    assert status.error == "connection error"
    assert status.is_last_known is True
    assert connection_summary(merged).startswith("DEGRADED TRANSPORT")
    assert "STALE LAST-KNOWN DATA" in render_overview(merged)


def test_all_failed_views_are_explicitly_disconnected() -> None:
    snapshot = OperatorSnapshot.failed("connection error")
    assert connection_summary(snapshot).startswith("DISCONNECTED")
    assert "TRANSPORT: DISCONNECTED" in render_overview(snapshot)


def test_server_partial_and_stale_semantics_are_rendered_without_reinterpretation() -> None:
    snapshot = run(DemoOperatorSource().fetch_all())
    result = snapshot.result("status")
    assert result is not None
    assert result.payload is not None
    result.payload["completeness"] = "PARTIAL"
    result.payload["freshness"] = "STALE"
    rendered = render_overview(snapshot)
    assert "freshness=STALE" in rendered
    assert "completeness=PARTIAL" in rendered


def test_plant_view_does_not_invent_missing_targets_or_leaf_vpd() -> None:
    snapshot = run(DemoOperatorSource().fetch_all())
    rendered = render_plants(snapshot)
    assert "Target/risk bands: UNAVAILABLE" in rendered
    assert "Leaf VPD: UNAVAILABLE" in rendered
    assert "36.4%" in rendered


def test_tui_keyboard_navigation_and_manual_refresh_at_80x24() -> None:
    async def scenario() -> None:
        app = OperatorConsole(DemoOperatorSource(), refresh_seconds=3600)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#views", ContentSwitcher).current == "overview"
            await pilot.press("2")
            assert app.query_one("#views", ContentSwitcher).current == "plants"
            await pilot.press("5")
            assert app.query_one("#views", ContentSwitcher).current == "anomalies"
            await pilot.press("r")
            await pilot.pause()
            assert app.snapshot.result("status") is not None

    run(scenario())


def test_tui_gracefully_runs_in_small_terminal() -> None:
    async def scenario() -> None:
        app = OperatorConsole(DemoOperatorSource(), refresh_seconds=3600)
        async with app.run_test(size=(60, 18)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            assert app.query_one("#views", ContentSwitcher).current == "edge"

    run(scenario())


def test_repeated_refresh_does_not_cancel_or_overlap_slow_fetch() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowSource(DemoOperatorSource):
            calls = 0
            cancelled = False

            async def fetch_all(self) -> OperatorSnapshot:
                self.calls += 1
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                return await super().fetch_all()

        source = SlowSource()
        app = OperatorConsole(source, refresh_seconds=3600)
        async with app.run_test() as pilot:
            await started.wait()
            for _ in range(4):
                app.refresh_data()
            await pilot.pause()
            assert source.calls == 1
            assert not source.cancelled
            release.set()
            await app.workers.wait_for_complete()
            assert app.snapshot.result("status") is not None
            app.refresh_data()
            await app.workers.wait_for_complete()
            assert source.calls == 2

    run(scenario())


def test_composite_views_mark_failed_dependencies_as_stale() -> None:
    from app.operator_tui.client import ViewResult

    first = run(DemoOperatorSource().fetch_all())
    failed = OperatorSnapshot.failed("synthetic outage")
    healthy_status = first.result("status")
    assert healthy_status is not None
    mixed = first.merge(OperatorSnapshot({**failed.views, "status": healthy_status}))
    overview = render_overview(mixed)
    for label in ("Anomalies", "Decisions", "Camera"):
        assert f"{label}: TRANSPORT: STALE LAST-KNOWN DATA" in overview
    failed_status = ViewResult("status", None, "synthetic outage", healthy_status.fetched_at_utc)
    plants = first.merge(OperatorSnapshot({"status": failed_status}))
    assert "Canonical current state\nTRANSPORT: STALE LAST-KNOWN DATA" in render_plants(plants)


def test_module_entrypoint_validates_refresh_interval(capsys) -> None:
    from app.operator_tui.__main__ import main

    assert main(["--demo", "--refresh-seconds", "nan"]) == 4
    assert "refresh_seconds must be between" in capsys.readouterr().err
