from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from app.ollama import OllamaClient, OllamaError


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"response": '{"story":"hello"}', "done": True}).encode()


def test_generate_sends_think_as_top_level_request_field() -> None:
    client = OllamaClient(host="http://ollama.test")

    with patch("app.ollama.urllib.request.urlopen", return_value=FakeResponse()) as open_request:
        client.generate(
            model="test-model",
            prompt="prompt",
            options={"temperature": 0.4},
            think=False,
        )

    request = open_request.call_args.args[0]
    payload = json.loads(request.data)
    assert payload["think"] is False
    assert payload["options"] == {"temperature": 0.4}
    assert "think" not in payload["options"]


def runner_crash() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://ollama.test/api/generate",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=BytesIO(b'{"error":"llama-server process has terminated: GGML_ASSERT"}'),
    )


def test_gemma4_runner_crash_retries_once_on_cpu_without_mutating_options() -> None:
    client = OllamaClient(host="http://ollama.test")
    options = {"num_ctx": 8192}

    with patch("app.ollama.urllib.request.urlopen", side_effect=[runner_crash(), FakeResponse()]) as open_request:
        response = client.generate(model="gemma4:latest", prompt="prompt", options=options)

    assert open_request.call_count == 2
    first_payload = json.loads(open_request.call_args_list[0].args[0].data)
    fallback_payload = json.loads(open_request.call_args_list[1].args[0].data)
    assert first_payload["options"] == {"num_ctx": 8192}
    assert fallback_payload["options"] == {"num_ctx": 8192, "num_gpu": 0}
    assert options == {"num_ctx": 8192}
    assert response.metrics["cpu_fallback"] is True


def test_runner_crash_does_not_change_other_models() -> None:
    client = OllamaClient(host="http://ollama.test")

    with (
        patch("app.ollama.urllib.request.urlopen", side_effect=runner_crash()) as open_request,
        pytest.raises(OllamaError, match="llama-server process has terminated"),
    ):
        client.generate(model="deepseek-r1:14b", prompt="prompt")

    assert open_request.call_count == 1


def test_gemma4_explicit_gpu_setting_is_respected() -> None:
    client = OllamaClient(host="http://ollama.test")

    with (
        patch("app.ollama.urllib.request.urlopen", side_effect=runner_crash()) as open_request,
        pytest.raises(OllamaError, match="llama-server process has terminated"),
    ):
        client.generate(model="gemma4:latest", prompt="prompt", options={"num_gpu": 10})

    assert open_request.call_count == 1
