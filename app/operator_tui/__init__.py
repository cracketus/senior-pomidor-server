"""Read-only Textual operator console for Senior Pomidor."""

from app.operator_tui.app import OperatorConsole
from app.operator_tui.client import DemoOperatorSource, OperatorDataSource, PomidorCtlOperatorSource

__all__ = ["DemoOperatorSource", "OperatorConsole", "OperatorDataSource", "PomidorCtlOperatorSource"]
