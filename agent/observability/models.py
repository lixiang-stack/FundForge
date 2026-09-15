"""Trace 数据模型（§12 可观测性合同）。"""

from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from domain.evaluation import EvaluationResult
from domain.evidence import ToolCallRecord, TokenUsage
from domain.report import ReportMetadata


class NodeTrace(BaseModel):
    """单个节点的执行摘要（输入/输出摘要 + 耗时；失败节点记录 error）。"""

    node: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    input_keys: list[str] = Field(default_factory=list)    # 执行时 State 可见字段
    output_keys: list[str] = Field(default_factory=list)   # 该节点写回的字段
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None                               # 节点抛错时的摘要（失败运行可追溯）


class GenerationTrace(BaseModel):
    """一次 LLM 调用的可观测记录（归属节点 + input/output 摘要 + token）。"""

    name: str
    node: str = "thesis"              # 归属节点（Langfuse 中嵌套在该节点 span 内）
    model: str | None = None
    calls: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)


class RunTrace(BaseModel):
    """一次完整 Agent Execution 的可持久化 Trace。"""

    request_id: str
    user_query: str
    started_at: datetime
    finished_at: datetime
    nodes: list[NodeTrace] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    generations: list[GenerationTrace] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    llm_model: str | None = None
    evaluation: EvaluationResult | None = None
    report_metadata: ReportMetadata | None = None
    data_quality_issues: list[str] = Field(default_factory=list)
    error: str | None = None                               # 运行级失败摘要（失败运行也写入）


# ---- live tracing 子元素载荷（节点 span 内嵌套的 tool / generation） ----

class ToolChild(TypedDict):
    kind: Literal["tool"]
    call: ToolCallRecord


class GenerationChild(TypedDict):
    kind: Literal["generation"]
    generation: GenerationTrace


NodeChild = ToolChild | GenerationChild


__all__ = ["NodeTrace", "GenerationTrace", "RunTrace", "ToolChild", "GenerationChild", "NodeChild"]
