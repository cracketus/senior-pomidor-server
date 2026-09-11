from __future__ import annotations

from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, Footer, Header, Static

from app.operator_tui.client import OperatorDataSource, OperatorSnapshot
from app.operator_tui.presenter import RENDERERS, connection_summary, render_view


class OperatorConsole(App[None]):
    """Read-only SSH-friendly operator console."""

    TITLE = "Senior Pomidor"
    SUB_TITLE = "read-only operator console"

    CSS = """
    #connection-banner {
        height: 3;
        padding: 1 2;
        text-style: bold;
    }
    #views {
        height: 1fr;
    }
    .operator-view {
        padding: 1 2;
        scrollbar-size: 1 1;
    }
    .view-body {
        width: 1fr;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("1", "show_overview", "Overview", show=True),
        Binding("2", "show_plants", "Plant", show=True),
        Binding("3", "show_edge", "Edge", show=True),
        Binding("4", "show_decisions", "Decisions", show=True),
        Binding("5", "show_anomalies", "Events", show=True),
        Binding("6", "show_camera", "Camera", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, source: OperatorDataSource, *, refresh_seconds: float = 60.0) -> None:
        super().__init__()
        self.source = source
        self.refresh_seconds = max(5.0, refresh_seconds)
        self.snapshot = OperatorSnapshot()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("LOADING — no operator snapshot yet", id="connection-banner", markup=False)
        with ContentSwitcher(initial="overview", id="views"):
            for view in RENDERERS:
                with VerticalScroll(id=view, classes="operator-view"):
                    yield Static("Loading…", id=f"{view}-body", classes="view-body", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(self.refresh_seconds, self.refresh_data)

    async def on_unmount(self) -> None:
        await self.source.aclose()

    @work(group="operator-refresh", exclusive=True, exit_on_error=False)
    async def refresh_data(self) -> None:
        banner = self.query_one("#connection-banner", Static)
        banner.update("REFRESHING — current screen remains read-only")
        try:
            incoming = await self.source.fetch_all()
        except Exception:
            incoming = OperatorSnapshot.failed("unexpected client failure")
        self.snapshot = self.snapshot.merge(incoming)
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        self.query_one("#connection-banner", Static).update(connection_summary(self.snapshot))
        for view in RENDERERS:
            self.query_one(f"#{view}-body", Static).update(render_view(view, self.snapshot))

    def _show(self, view: str) -> None:
        self.query_one("#views", ContentSwitcher).current = view

    def action_show_overview(self) -> None:
        self._show("overview")

    def action_show_plants(self) -> None:
        self._show("plants")

    def action_show_edge(self) -> None:
        self._show("edge")

    def action_show_decisions(self) -> None:
        self._show("decisions")

    def action_show_anomalies(self) -> None:
        self._show("anomalies")

    def action_show_camera(self) -> None:
        self._show("camera")

    def action_refresh(self) -> None:
        self.refresh_data()
