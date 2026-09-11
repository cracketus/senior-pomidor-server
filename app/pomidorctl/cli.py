from __future__ import annotations

import argparse
import sys
from typing import Any, NoReturn

from app.pomidorctl.client import OperatorClient
from app.pomidorctl.config import ConfigError, build_config
from app.pomidorctl.errors import CLIError
from app.pomidorctl.render import exit_code, render_error, render_human, render_json


class CLIArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CLIError("cli", "configuration_error", "invalid command-line arguments", 4)


def _parser() -> argparse.ArgumentParser:
    parser = CLIArgumentParser(prog="pomidorctl", description="Read-only Senior Pomidor operator client")

    def add_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--server-url", default=argparse.SUPPRESS)
        target.add_argument("--timeout-seconds", type=float, default=argparse.SUPPRESS)
        target.add_argument("--token-file", default=argparse.SUPPRESS)
        target.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        target.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)

    add_options(parser)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=CLIArgumentParser)
    for command in ("status", "plants", "edge", "anomalies", "decisions", "photos"):
        child = sub.add_parser(command)
        add_options(child)
        if command in {"plants", "edge"}:
            child.add_argument("--limit", type=int, default=100)
        elif command in {"anomalies", "photos"}:
            child.add_argument("--node-id")
            child.add_argument("--since-hours", type=int, default=24)
            child.add_argument("--limit", type=int, default=100 if command == "anomalies" else 25)
    tui = sub.add_parser("tui")
    tui.add_argument("--server-url", default=argparse.SUPPRESS)
    tui.add_argument("--timeout-seconds", type=float, default=argparse.SUPPRESS)
    tui.add_argument("--token-file", default=argparse.SUPPRESS)
    tui.add_argument("--refresh-seconds", type=float, default=60.0)
    tui.add_argument("--demo", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    args: dict[str, Any] = {}
    command = "cli"
    try:
        args = vars(_parser().parse_args(raw_argv))
        command = str(args["command"])
        if args.get("json") and args.get("verbose"):
            raise ConfigError("--json and --verbose cannot be used together")
        for key, low, high in (("limit", 1, 100), ("since_hours", 0, 168)):
            if key in args and args[key] is not None and not low <= args[key] <= high:
                raise ConfigError(f"{key} is out of range")
        config = build_config(
            server_url=args.get("server_url"),
            timeout_seconds=args.get("timeout_seconds"),
            token_file=args.get("token_file"),
        )
        if command == "tui":
            if not 5.0 <= args["refresh_seconds"] <= 3600.0:
                raise ConfigError("refresh_seconds must be between 5 and 3600 seconds")
            try:
                from app.operator_tui.__main__ import launch
            except ImportError as exc:
                raise ConfigError("TUI support is not installed; install senior-pomidor-server[tui]") from exc
            launch(config, refresh_seconds=args["refresh_seconds"], demo=bool(args.get("demo")))
            return 0
        params: dict[str, Any] = {
            key: args[key] for key in ("node_id", "since_hours", "limit") if key in args and args[key] is not None
        }
        with OperatorClient(config) as client:
            response = client.request(command, params=params or None)
        print(render_json(response) if args.get("json") else render_human(response, verbose=args.get("verbose", False)))
        return exit_code(response)
    except ConfigError as exc:
        error = CLIError(command, "configuration_error", str(exc), 4)
    except CLIError as exc:
        error = exc
    if args.get("json") or "--json" in raw_argv:
        print(render_error(error.payload))
    else:
        print(f"{error.payload.error_code}: {error.payload.message}", file=sys.stderr)
    return error.exit_code
