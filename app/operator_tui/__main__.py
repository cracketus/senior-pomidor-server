from __future__ import annotations

import sys
from collections.abc import Sequence

from app.operator_tui.app import OperatorConsole
from app.operator_tui.client import DemoOperatorSource, PomidorCtlOperatorSource
from app.pomidorctl.config import Config


def launch(config: Config, *, refresh_seconds: float = 60.0, demo: bool = False) -> None:
    source = DemoOperatorSource() if demo else PomidorCtlOperatorSource(config)
    OperatorConsole(source, refresh_seconds=refresh_seconds).run()


def main(argv: Sequence[str] | None = None) -> int:
    from app.pomidorctl.cli import main as cli_main

    return cli_main(["tui", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    sys.exit(main())
