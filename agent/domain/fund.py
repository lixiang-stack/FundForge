"""基金领域数据模型。

合同见 docs/TechnicalContract.md §7。所有核心模型必须携带
data_quality 与 as_of，用于数据质量传递与披露。
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

DataQuality = Literal["complete", "partial", "stale", "missing"]


class NAVPoint(BaseModel):
    """单个净值数据点（原始事实，存放于外部 Store）。"""

    nav_date: date
    unit_nav: float | None = None
    acc_nav: float | None = None
    daily_return: float | None = None


class Fund(BaseModel):
    """基金完整信息（存放于外部 Store，State 不直接携带）。"""

    id: str
    name: str
    fund_type: str | None = None
    category: str | None = None
    manager_id: str | None = None
    manager_name: str | None = None
    company: str | None = None
    benchmark: str | None = None
    inception_date: date | None = None
    aum: float | None = None                       # 单位：亿元
    currency: str = "CNY"
    source: str
    as_of: datetime
    data_quality: DataQuality = "complete"


class FundSummary(BaseModel):
    """State 轻量版基金摘要。"""

    id: str
    name: str
    fund_type: str | None = None
    category: str | None = None
    aum: float | None = None
    manager_name: str | None = None
    as_of: datetime
    data_quality: DataQuality = "complete"


class FundPerformance(BaseModel):
    """基金业绩结构化结果。

    Phase 1 只采集原始净值序列（事实），指标字段留空；
    年化收益 / 波动率 / 最大回撤 / 夏普等由 Phase 2 Analyzer 纯函数计算。
    """

    fund_id: str
    period_start: date | None = None
    period_end: date | None = None
    nav_point_count: int = 0
    cumulative_return: float | None = None
    annualized_return: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    benchmark_return: float | None = None
    source: str
    as_of: datetime
    data_quality: DataQuality = "complete"


def summarize_fund(fund: Fund) -> FundSummary:
    """Fund → FundSummary（State 只保留摘要）。"""
    return FundSummary(
        id=fund.id,
        name=fund.name,
        fund_type=fund.fund_type,
        category=fund.category,
        aum=fund.aum,
        manager_name=fund.manager_name,
        as_of=fund.as_of,
        data_quality=fund.data_quality,
    )


def quality_of(*fields: object) -> DataQuality:
    """根据关键字段缺失情况推导 data_quality：全缺 missing，部分缺 partial，否则 complete。"""
    present = [f is not None for f in fields]
    if not any(present):
        return "missing"
    if not all(present):
        return "partial"
    return "complete"


__all__ = [
    "DataQuality",
    "NAVPoint",
    "Fund",
    "FundSummary",
    "FundPerformance",
    "summarize_fund",
    "quality_of",
]
