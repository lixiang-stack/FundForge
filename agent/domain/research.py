"""外部研究领域模型（Node 合同 §4 Researcher / Tool 合同 §6 Research Tools）。

V1 仅定义契约与数据结构：Researcher 节点默认无外部研究源（确定性降级），
真实 web_search / fetch_document 在 Phase 7+ 按 Evaluation ROI 接入。
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class ResearchItem(BaseModel):
    """一条外部研究信息（State 只保留结构化摘要）。"""

    title: str
    content: str
    source: str
    as_of: datetime | None = None


class ResearchProvider(Protocol):
    """外部研究能力协议（web_search / fetch_document 的抽象）。"""

    def search(self, query: str, limit: int = 5) -> list[ResearchItem]:
        """按查询返回研究条目；无可用来源时返回空列表。"""
        ...


def empty_research_note() -> str:
    return "外部研究未接入（ResearchProvider 未配置），research_items 为空"


__all__ = ["ResearchItem", "ResearchProvider", "empty_research_note"]
