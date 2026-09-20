"""TaskType — 任务类型常量（docs/TechnicalContract.md §3）。

V1 只支持以下四类，取值与合同的 Literal 完全一致；
以 StrEnum 定义为唯一来源，避免到处使用裸字符串。
"""

from enum import StrEnum


class TaskType(StrEnum):
    FUND_RESEARCH = "fund_research"
    FUND_COMPARISON = "fund_comparison"
    FUND_SCREENING = "fund_screening"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"


class ClassificationRuleHit(StrEnum):
    """意图分类规则命中标识（nodes/intent.py 规则引擎；R6 为 Planner 可行性降级标记）。"""

    R1_DUAL_INTENT_SUBJECT = "R1_dual_intent_subject"
    R2_ANALYSIS_INTENT = "R2_analysis_intent"
    R3_COMPARISON_INTENT = "R3_comparison_intent"
    R4_MULTI_CODE_COMPARISON = "R4_multi_code_comparison"
    R5_FALLBACK = "R5_fallback"
    FEASIBILITY_DOWNGRADE = "R6_feasibility_downgrade"


# 确定性意图分类关键词（Router 分类 / Evaluator 对齐检查共用）
ANALYSIS_INTENT_KEYWORDS = ("分析", "研究", "适合", "持有", "值得", "评估")
COMPARISON_INTENT_KEYWORDS = ("对比", "比较", "相比", "哪个好", "哪一个好", "更值得", "哪个更", "哪一个更")


__all__ = [
    "TaskType",
    "ClassificationRuleHit",
    "ANALYSIS_INTENT_KEYWORDS",
    "COMPARISON_INTENT_KEYWORDS",
]
