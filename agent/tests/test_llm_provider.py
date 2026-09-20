"""OpenAICompatProvider 单元测试：基于 openai SDK + httpx.MockTransport。"""

import json

import httpx
import pytest

from domain.thesis import InvestmentThesis
from limits import LLM_MAX_TOKENS
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

    def test_max_tokens_cap_sent(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{}"}}]},
            )

        _provider(handler).generate([Message("user", "hi")])
        assert seen["payload"]["max_tokens"] == LLM_MAX_TOKENS

    def test_truncated_output_raises_llm_error_with_partial_content(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"summary":'}, "finish_reason": "length"}
                    ],
                    "usage": {"prompt_tokens": 4500, "completion_tokens": 4000},
                },
            )

        with pytest.raises(LLMError, match="truncated") as exc_info:
            _provider(handler).generate([Message("user", "hi")])
        # 部分原始输出与实际用量随异常透出（运行记录留存诊断用）
        assert exc_info.value.content == '{"summary":'
        assert exc_info.value.input_tokens == 4500
        assert exc_info.value.output_tokens == 4000

    def test_http_error_wrapped_as_llm_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "bad key"}})

        with pytest.raises(LLMError):
            _provider(handler).generate([Message("user", "hi")])
