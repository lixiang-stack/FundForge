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
from domain.evidence import Evidence, LlmInteraction, TokenUsage, ToolCallRecord
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.report import Report
from domain.research import ResearchItem
from domain.screening import ScreenResult, ScreenSpec, ScreeningMeta
from domain.task_type import ClassificationRuleHit, TaskType
from domain.thesis import Claim, InvestmentThesis


class FundForgeState(TypedDict, total=False):
    # === Request ===
    request_id: str
    user_query: str
    task_type: TaskType
    classification_rule_hit: ClassificationRuleHit
    classification_confidence: float

    # === Planning ===
    research_plan: ResearchPlan

    # === Screening 产出（fund_screening；预选集经 fund_ids 流向 Collector/Analyzer） ===
    screen_spec: ScreenSpec
    screen_rank_rows: dict[str, dict]     # fund_code → rank 表行摘要（锚点收益/名称/费率）
    screening_meta: ScreeningMeta
    screening_result: ScreenResult

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
    llm_interactions: list[LlmInteraction]

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


def current_usage(state: FundForgeState) -> TokenUsage:
    """读 State 的累计 token 用量（LangGraph 回传后可能是 dict，需归一化）。

    产出 token_usage 的节点（thesis / screener）共用本入口，避免各写一份
    归一化逻辑后彼此漂移。
    """
    raw = state.get("token_usage")
    if raw is None or isinstance(raw, TokenUsage):
        return raw or TokenUsage()
    return TokenUsage.model_validate(raw)


__all__ = ["FundForgeState", "current_usage"]
