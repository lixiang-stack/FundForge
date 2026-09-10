"""TaskType — 任务类型常量（docs/TechnicalContract.md §3）。

V1 只支持以下四类，取值与合同的 Literal 完全一致；
以 str 枚举形式定义，避免到处使用裸字符串。
"""

from enum import Enum


class TaskType(str, Enum):
    FUND_RESEARCH = "fund_research"
    FUND_COMPARISON = "fund_comparison"
    FUND_SCREENING = "fund_screening"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"


__all__ = ["TaskType"]
