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


__all__ = ["TaskType"]
