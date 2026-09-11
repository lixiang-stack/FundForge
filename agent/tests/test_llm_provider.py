"""OpenAICompatProvider 单元测试：基于 openai SDK + httpx.MockTransport。"""

import json

import httpx
import pytest

from domain.thesis import InvestmentThesis
from llm.base import LLMError, Message
from llm.openai_compat import OpenAICompatProvider


def _provider(handler) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="http://llm.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestOpenAICompatProvider:
    def test_generate_parses_content_and_usage(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                },
            )

        resp = _provider(handler).generate([Message("user", "hi")])
        assert resp.content == '{"ok": true}'
        assert resp.input_tokens == 11
        assert resp.output_tokens == 7

    def test_json_mode_requested_for_structured_output(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{}"}}]},
            )

        provider = _provider(handler)
        provider.generate([Message("user", "hi")], structured_output=InvestmentThesis)
        assert seen["payload"]["response_format"] == {"type": "json_object"}
        assert seen["payload"]["model"] == "test-model"

        provider.generate([Message("user", "hi")])
        assert "response_format" not in seen["payload"]

    def test_http_error_wrapped_as_llm_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "bad key"}})

        with pytest.raises(LLMError):
            _provider(handler).generate([Message("user", "hi")])
