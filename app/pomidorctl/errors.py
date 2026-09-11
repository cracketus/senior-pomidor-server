from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CLIErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "senior-pomidor.pomidorctl-error.v1"
    command: str = Field(min_length=1, max_length=40)
    error_code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=200)


class CLIError(Exception):
    def __init__(self, command: str, error_code: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.payload = CLIErrorPayload(command=command, error_code=error_code, message=message)
        self.exit_code = exit_code
