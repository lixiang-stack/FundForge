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


# 确定性意图分类关键词（Router 分类 / Evaluator 对齐检查共用）
ANALYSIS_INTENT_KEYWORDS = ("分析", "研究", "适合", "持有", "值得", "评估")
COMPARISON_INTENT_KEYWORDS = ("对比", "比较", "相比", "哪个好", "哪一个好", "更值得")


__all__ = ["TaskType", "ANALYSIS_INTENT_KEYWORDS", "COMPARISON_INTENT_KEYWORDS"]
