"""FundForgeState — Agent 工作流的任务上下文。

完整 State 合同见 docs/TechnicalContract.md §2：
- 只保存跨 Node 真正需要共享的摘要与 ID；
- 不保存 LLM Client、DB Connection、Tool Instance 等运行时对象；
- evidence 只允许追加。

Phase 1 新增：research_plan、fund_ids、funds_summary、evidence、tool_calls、
data_quality_issues。完整基金数据与净值序列存放在外部 Store（store.py）。
"""

from typing import TypedDict

from domain.evidence import Evidence, ToolCallRecord
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.task_type import TaskType


class FundForgeState(TypedDict, total=False):
    # === Request ===
    request_id: str
    user_query: str
    task_type: TaskType

    # === Planning ===
    research_plan: ResearchPlan

    # === Collector 产出（摘要 + ID，完整数据在外部 Store） ===
    fund_ids: list[str]
    funds_summary: list[FundSummary]
    evidence: list[Evidence]
    tool_calls: list[ToolCallRecord]
    data_quality_issues: list[str]

    # === Output ===
    report: str


__all__ = ["FundForgeState"]
