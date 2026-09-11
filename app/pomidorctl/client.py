from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.operator_summary import (
    AnomaliesResponse,
    DecisionsResponse,
    EdgesResponse,
    PhotosResponse,
    PlantsResponse,
    StatusResponse,
)
from app.pomidorctl.config import Config
from app.pomidorctl.errors import CLIError

MAX_RESPONSE_BYTES = 1024 * 1024
MODELS: dict[str, type[BaseModel]] = {
    "status": StatusResponse,
    "plants": PlantsResponse,
    "edge": EdgesResponse,
    "anomalies": AnomaliesResponse,
    "decisions": DecisionsResponse,
    "photos": PhotosResponse,
}
PATHS = {
    "status": "status",
    "plants": "plants",
    "edge": "edges",
    "anomalies": "anomalies",
    "decisions": "decisions",
    "photos": "photos",
}


class OperatorClient:
    def __init__(self, config: Config, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.Client(timeout=config.timeout_seconds, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OperatorClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _read_bounded(self, response: httpx.Response, command: str) -> bytes:
        body = bytearray()
        try:
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise CLIError(command, "response_too_large", "API response exceeds the size limit", 7)
        except CLIError:
            raise
        except httpx.HTTPError as exc:
            raise CLIError(command, "protocol_error", "API response could not be read", 7) from exc
        return bytes(body)

    def get(self, command: str, *, params: dict[str, Any] | None = None) -> BaseModel:
        if command not in PATHS:
            raise CLIError(command, "configuration_error", "unknown command", 4)
        headers = {"Accept": "application/json"}
        if self.config.token is not None:
            headers["Authorization"] = "Bearer " + self.config.token
        try:
            with self._client.stream(
                "GET", f"{self.config.server_url}/api/v1/operator/{PATHS[command]}", params=params, headers=headers
            ) as response:
                if response.status_code in {401, 403}:
                    raise CLIError(command, "authentication_failed", "API authentication failed", 5)
                if response.status_code >= 500:
                    raise CLIError(command, "api_unavailable", "API is unavailable", 6)
                if response.status_code != 200:
                    raise CLIError(command, "protocol_error", "API returned an unexpected response", 7)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise CLIError(command, "protocol_error", "API returned a non-JSON response", 7)
                body = self._read_bounded(response, command)
        except CLIError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise CLIError(command, "api_unavailable", "API is unavailable", 6) from exc
        except httpx.HTTPError as exc:
            raise CLIError(command, "protocol_error", "API request failed", 7) from exc
        try:
            return MODELS[command].model_validate(json.loads(body))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise CLIError(
                command, "contract_mismatch", "API response does not match the operator contract", 7
            ) from exc

    def request(self, command: str, *, params: dict[str, Any] | None = None) -> BaseModel:
        return self.get(command, params=params)
