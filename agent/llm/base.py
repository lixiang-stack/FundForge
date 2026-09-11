"""LLM Provider 抽象（docs/TechnicalContract.md §14）。

核心原则：Agent 不直接依赖具体模型（OpenAI / DeepSeek / GLM / Claude 等），
通过 Provider 替换；Domain 层不依赖任何 LLM SDK。

V1 简化：generate 为同步接口（当前工作流全部为同步节点）；
Provider 可替换的原则不变，必要时再演进为 async。
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class Message:
    """单条对话消息。role: "system" | "user" | "assistant"。"""

    __slots__ = ("role", "content")

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class LLMResponse(BaseModel):
    """一次 LLM 调用的响应。"""

    content: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """LLM Provider 协议：结构化输出版 generate。"""

    def generate(
        self,
        messages: list[Message],
        *,
        structured_output: type[BaseModel] | None = None,
    ) -> LLMResponse: ...


class LLMError(RuntimeError):
    """LLM 调用失败（网络 / 鉴权 / 响应异常）。"""


__all__ = ["Message", "LLMResponse", "LLMProvider", "LLMError"]
