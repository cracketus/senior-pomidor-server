from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class OllamaError(RuntimeError):
    """A bounded, user-safe description of an Ollama request failure."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    metrics: dict[str, Any]


def _should_retry_gemma4_on_cpu(
    *, model: str, options: dict[str, Any] | None, status_code: int, response_body: str
) -> bool:
    model_name = model.rsplit("/", 1)[-1].lower()
    if not model_name.startswith("gemma4") or status_code < 500 or (options is not None and "num_gpu" in options):
        return False
    return any(
        marker in response_body
        for marker in (
            "GGML_SCHED_MAX_SPLIT_INPUTS",
            "GGML_ASSERT",
            "llama-server process has terminated",
        )
    )


class OllamaClient:
    def __init__(self, *, host: str, timeout_seconds: float = 120.0) -> None:
        self.host = host.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urllib.parse.urlparse(self.host)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise OllamaError("Ollama host must be an HTTP or HTTPS URL")
        if timeout_seconds <= 0:
            raise OllamaError("Ollama timeout must be positive")

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        format_schema: dict[str, Any] | str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | int | None = None,
        images: list[str] | None = None,
        think: bool | str | None = None,
    ) -> OllamaResponse:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system is not None:
            payload["system"] = system
        if format_schema is not None:
            payload["format"] = format_schema
        if options is not None:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if images is not None:
            payload["images"] = images
        if think is not None:
            payload["think"] = think
        request_payload = payload
        used_cpu_fallback = False
        while True:
            request = urllib.request.Request(  # noqa: S310
                f"{self.host}/api/generate",
                data=json.dumps(request_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(  # noqa: S310  # nosec B310
                    request, timeout=self.timeout_seconds
                ) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                if not used_cpu_fallback and _should_retry_gemma4_on_cpu(
                    model=model,
                    options=options,
                    status_code=exc.code,
                    response_body=body,
                ):
                    fallback_options = dict(options or {})
                    fallback_options["num_gpu"] = 0
                    request_payload = {**payload, "options": fallback_options}
                    used_cpu_fallback = True
                    continue
                raise OllamaError(
                    f"Ollama HTTP {exc.code}: {body}",
                    retryable=exc.code in {408, 409, 425, 429} or exc.code >= 500,
                ) from exc
            except urllib.error.URLError as exc:
                raise OllamaError(f"Ollama request failed: {exc.reason}", retryable=True) from exc
            except TimeoutError as exc:
                raise OllamaError("Ollama request timed out", retryable=True) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaError("Ollama returned malformed JSON", retryable=True) from exc
        if not isinstance(decoded, dict):
            raise OllamaError("Ollama returned an invalid response", retryable=True)
        text = decoded.get("response")
        if not isinstance(text, str):
            raise OllamaError("Ollama response did not include a text response", retryable=True)
        metrics = {
            key: decoded[key]
            for key in (
                "done",
                "done_reason",
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            )
            if key in decoded
        }
        if used_cpu_fallback:
            metrics["cpu_fallback"] = True
        return OllamaResponse(text=text, metrics=metrics)
