"""Evidence 与可观测性模型。

合同见 docs/TechnicalContract.md §8 / §12。
- Evidence 只允许追加，不允许修改历史记录（State Rules §2.5）。
- 每个 Claim 必须绑定 evidence_ids（Claim 模型在 domain/thesis.py）。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from domain.shared import DataQuality


class EvidenceType(StrEnum):
    """证据类型（§8），Evalutor 按此分支检查证据覆盖。"""

    FUND_DATA = "fund_data"
    MARKET_DATA = "market_data"
    CALCULATION = "calculation"
    RESEARCH = "research"
    MANAGER = "manager"


class Evidence(BaseModel):
    id: str
    evidence_type: EvidenceType
    source: str
    source_detail: str | None = None
    as_of: datetime | None = None
    value: str | float | dict | list | None = None
    data_quality: DataQuality = DataQuality.COMPLETE
    confidence: float = 1.0
    raw_ref: str | None = None      # 指向外部 Store 中的完整原始数据


class ToolCallRecord(BaseModel):
    """单次 Tool 调用记录（可观测性合同 §12）。"""

    tool_name: str
    arguments: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    success: bool
    error: str | None = None


class TokenUsage(BaseModel):
    """LLM 用量统计（可观测性合同 §12）。

    estimated_cost 因各家模型费率不同，V1 恒为 0（Phase 7 Cost Governor 接入）。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    estimated_cost: float = 0.0

    def merged(self, other: "TokenUsage") -> "TokenUsage":
        """合并两份用量（append 语义）。"""
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            llm_calls=self.llm_calls + other.llm_calls,
            estimated_cost=self.estimated_cost + other.estimated_cost,
        )


__all__ = ["Evidence", "EvidenceType", "ToolCallRecord", "TokenUsage"]
