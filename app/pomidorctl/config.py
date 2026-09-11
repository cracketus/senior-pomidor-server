from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
MAX_TOKEN_BYTES = 8192


class ConfigError(ValueError):
    pass


def _one_line(value: str, label: str) -> str:
    if not value or not value.strip() or "\n" in value or "\r" in value:
        raise ConfigError(f"invalid {label}")
    if len(value.encode("utf-8")) > MAX_TOKEN_BYTES:
        raise ConfigError(f"{label} is too large")
    return value.strip()


def validate_url(value: str) -> str:
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise ConfigError("invalid server URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ConfigError("invalid server URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("invalid server URL") from exc
    if port is not None and not 0 <= port <= 65535:
        raise ConfigError("invalid server URL")
    if parsed.query or parsed.fragment:
        raise ConfigError("invalid server URL")
    return value.rstrip("/")


def read_token_file(path_value: str) -> str:
    try:
        raw = Path(path_value).read_bytes()
    except (OSError, ValueError) as exc:
        raise ConfigError("cannot read token file") from exc
    if len(raw) > MAX_TOKEN_BYTES:
        raise ConfigError("token file is too large")
    try:
        return _one_line(raw.decode("utf-8"), "token")
    except UnicodeDecodeError as exc:
        raise ConfigError("invalid token file") from exc


@dataclass(frozen=True)
class Config:
    server_url: str
    timeout_seconds: float
    token: str | None


def build_config(
    *,
    server_url: str | None,
    timeout_seconds: float | None,
    token_file: str | None,
    environ: dict[str, str] | None = None,
) -> Config:
    env = os.environ if environ is None else environ
    url = validate_url(server_url or env.get("POMIDORCTL_SERVER_URL", DEFAULT_SERVER_URL))
    timeout_text = env.get("POMIDORCTL_TIMEOUT_SECONDS", "5") if timeout_seconds is None else str(timeout_seconds)
    try:
        timeout = float(timeout_text)
    except ValueError as exc:
        raise ConfigError("invalid timeout") from exc
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 60:
        raise ConfigError("timeout must be between 0.1 and 60 seconds")
    env_file = env.get("POMIDORCTL_TOKEN_FILE")
    env_token = env.get("POMIDORCTL_TOKEN")
    if sum(value is not None for value in (token_file, env_file, env_token)) > 1:
        raise ConfigError("multiple token sources configured")
    token_path = token_file or env_file
    token = read_token_file(token_path) if token_path is not None else None
    if env_token is not None:
        token = _one_line(env_token, "token")
    return Config(server_url=url, timeout_seconds=timeout, token=token)
