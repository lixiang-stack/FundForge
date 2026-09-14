"""FundForgeState — Agent 工作流的任务上下文。

完整 State 合同见 docs/TechnicalContract.md §2：
- 只保存跨 Node 真正需要共享的摘要与 ID；
- 不保存 LLM Client、DB Connection、Tool Instance 等运行时对象；
- evidence 只允许追加。

节点输出约定：
- **节点只返回自己负责的字段**（各模块内的 XxxOutput TypedDict），其余字段由
  Graph 按 key 合并保留；因此所有 Output 均为 total=False（允许部分更新）。
- Output 的 key/类型必须是本 State 字段的子集/同型，由 tests/test_contracts.py 强制。

完整基金数据与净值序列存放在外部 Store（store.py）。
"""

from typing import TypedDict

from domain.analysis import AnalysisResult
from domain.evaluation import EvaluationResult
from domain.evidence import Evidence, ToolCallRecord
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.report import Report
from domain.research import ResearchItem
from domain.task_type import ClassificationRuleHit, TaskType
from domain.thesis import Claim, InvestmentThesis
from domain.evidence import TokenUsage


class FundForgeState(TypedDict, total=False):
    # === Request ===
    request_id: str
    user_query: str
    task_type: TaskType
    classification_rule_hit: ClassificationRuleHit
    classification_confidence: float

    # === Planning ===
    research_plan: ResearchPlan

    # === Collector 产出（摘要 + ID，完整数据在外部 Store） ===
    fund_ids: list[str]
    peer_fund_ids: list[str]
    funds_summary: list[FundSummary]
    evidence: list[Evidence]
    tool_calls: list[ToolCallRecord]
    data_quality_issues: list[str]

    # === Analyzer 产出 ===
    analysis: AnalysisResult

    # === Thesis 产出 ===
    claims: list[Claim]
    investment_thesis: InvestmentThesis

    # === Researcher 产出 ===
    research_items: list[ResearchItem]

    # === 可观测性（§12） ===
    token_usage: TokenUsage

    # === Evaluator / Repair 产出（iteration 硬限制 max=1） ===
    evaluation: EvaluationResult
    iteration: int
    repair_actions: list[str]

    # === Output ===
    report: Report


__all__ = ["FundForgeState"]
