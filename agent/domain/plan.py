"""ResearchPlan 模型（Node 合同 §4：Planner 输出必须结构化）。

V1 结构刻意保持最小；后续 Phase 按需扩展（对比基金、研究步骤等）。
"""

from pydantic import BaseModel, Field

from domain.task_type import TaskType


class ResearchPlan(BaseModel):
    task_type: TaskType = TaskType.FUND_RESEARCH
    primary_fund_id: str | None = None   # 主基金（分析主体）；None 时下游默认取 fund_ids[0]
    fund_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_state(cls, value: "ResearchPlan | dict | None") -> "ResearchPlan | None":
        """从 State 中归一化 research_plan（LangGraph 可能回传 dict）。"""
        if value is None:
            return None
        return cls.model_validate(value) if isinstance(value, dict) else value


__all__ = ["ResearchPlan"]
