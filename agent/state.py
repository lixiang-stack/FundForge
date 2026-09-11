"""FundForgeState — Agent 工作流的任务上下文。

完整 State 合同见 docs/TechnicalContract.md §2：
- 只保存跨 Node 真正需要共享的摘要与 ID；
- 不保存 LLM Client、DB Connection、Tool Instance 等运行时对象；
- evidence 只允许追加。

Phase 1 新增：research_plan、fund_ids、funds_summary、evidence、tool_calls、
data_quality_issues。完整基金数据与净值序列存放在外部 Store（store.py）。
"""

from typing import TypedDict

from domain.analysis import AnalysisResult
from domain.evaluation import EvaluationResult
from domain.evidence import Evidence, ToolCallRecord
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.report import Report
from domain.task_type import TaskType
from domain.thesis import Claim, InvestmentThesis


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

    # === Analyzer 产出 ===
    analysis: AnalysisResult

    # === Thesis 产出 ===
    claims: list[Claim]
    investment_thesis: InvestmentThesis

    # === Evaluator / Repair 产出（iteration 硬限制 max=1） ===
    evaluation: EvaluationResult
    iteration: int
    repair_actions: list[str]

    # === Output ===
    report: Report


__all__ = ["FundForgeState"]
