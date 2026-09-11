from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.operator_tui.app import OperatorConsole
from app.operator_tui.client import DemoOperatorSource, PomidorCtlOperatorSource
from app.pomidorctl.config import Config, build_config


def launch(config: Config, *, refresh_seconds: float = 60.0, demo: bool = False) -> None:
    source = DemoOperatorSource() if demo else PomidorCtlOperatorSource(config)
    OperatorConsole(source, refresh_seconds=refresh_seconds).run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Senior Pomidor read-only operator TUI")
    parser.add_argument("--server-url")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--token-file")
    parser.add_argument("--refresh-seconds", type=float, default=60.0)
    parser.add_argument("--demo", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = build_config(
        server_url=args.server_url,
        timeout_seconds=args.timeout_seconds,
        token_file=args.token_file,
    )
    launch(config, refresh_seconds=args.refresh_seconds, demo=args.demo)


if __name__ == "__main__":
    main()
