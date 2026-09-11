"""OpenAI 兼容协议 LLM Provider（基于 openai SDK）。

通过环境变量配置，兼容 DeepSeek / 智谱 GLM / Kimi / OpenAI 等：
- LLM_BASE_URL  例如 https://api.deepseek.com/v1
- LLM_API_KEY
- LLM_MODEL     例如 deepseek-chat / glm-4-flash / gpt-4o-mini
- LLM_TIMEOUT_S 超时秒数（默认 120）

采用 openai SDK 而非裸 HTTP：自动重试（连接错误 / 429 / 5xx，指数退避）、
错误分类（AuthenticationError / RateLimitError 等，统一包装为 LLMError）、
协议兼容性由 SDK 维护。

结构化输出：JSON Mode（response_format=json_object）+ 调用方 Pydantic 校验。
不使用 SDK 的 beta.parse：兼容厂商支持度不一，且 Evidence 绑定校验必须在节点层。
配置不完整时 make_default_llm 返回 None，由节点层降级。
"""

import logging
from typing import Any

from openai import APIError, OpenAI
from pydantic import BaseModel

from config import llm_api_key, llm_base_url, llm_model, llm_timeout_seconds
from llm.base import LLMError, LLMResponse, Message

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    """OpenAI 兼容 chat/completions 的 Provider 实现。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float | None = None,
        max_retries: int = 2,
        http_client=None,
    ) -> None:
        self._model = model
        self._client = OpenAI(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    def generate(
        self,
        messages: list[Message],
        *,
        structured_output: type[BaseModel] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": 0.2,
        }
        if structured_output is not None:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except APIError as e:
            logger.error("llm request failed: %s", e)
            raise LLMError(f"llm chat/completions failed: {e}") from e

        try:
            content = resp.choices[0].message.content or ""
            usage = resp.usage
            return LLMResponse(
                content=content,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
        except (AttributeError, IndexError, TypeError) as e:
            raise LLMError(f"llm unexpected response shape: {e}") from e

    def close(self) -> None:
        self._client.close()

    @property
    def model(self) -> str:
        return self._model


def make_default_llm() -> OpenAICompatProvider | None:
    """按环境变量构建默认 Provider；配置不完整时返回 None（节点层降级）。"""
    base_url, api_key, model = llm_base_url(), llm_api_key(), llm_model()
    if not (base_url and api_key and model):
        missing = [
            name
            for name, val in (
                ("LLM_BASE_URL", base_url),
                ("LLM_API_KEY", api_key),
                ("LLM_MODEL", model),
            )
            if not val
        ]
        logger.warning("llm not configured, missing: %s", ", ".join(missing))
        return None
    return OpenAICompatProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=llm_timeout_seconds(),
    )


__all__ = ["OpenAICompatProvider", "make_default_llm"]
