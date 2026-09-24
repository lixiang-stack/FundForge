"""基金领域数据模型。

合同见 docs/TechnicalContract.md §7。所有核心模型必须携带
data_quality 与 as_of，用于数据质量传递与披露。
"""

import re
from datetime import date, datetime

from pydantic import BaseModel

from domain.shared import DataQuality

_QUARTER_RE = re.compile(r"(\d{4})年(\d{1,2})季度")


class NAVPoint(BaseModel):
    """单个净值数据点（原始事实，存放于外部 Store）。"""

    nav_date: date
    unit_nav: float | None = None
    acc_nav: float | None = None
    daily_return: float | None = None

    @property
    def has_value(self) -> bool:
        """点有效性（口径无关）：单位净值或累计净值至少一个非空。

        对齐窗口端点检测与净值口径选择共用同一判定，避免各处内联重复。
        """
        return self.unit_nav is not None or self.acc_nav is not None


class Holding(BaseModel):
    """股票持仓（原始事实，存放于外部 Store）。"""

    stock_code: str
    stock_name: str
    hold_ratio: float | None = None     # 占净值比例（%）
    report_date: str | None = None      # 报告期（如 "2025-06-30"）


class IndustryAllocRow(BaseModel):
    """行业配置单行（原始事实，存放于外部 Store）。"""

    industry: str | None = None
    nav_ratio: float | None = None      # 占净值比例（%）
    market_value: float | None = None   # 市值（万元）
    report_date: str | None = None      # 截止时间（如 "2026-06-30"）


class AssetAllocRow(BaseModel):
    """资产配置单行（原始事实，存放于外部 Store）。"""

    asset_type: str | None = None       # 股票 / 债券 / 现金 / 其他
    percent: float | None = None        # 仓位占比（%）


class FeeInfo(BaseModel):
    """基金运作费用（原始事实，% / 年）。"""

    management_fee_rate: float | None = None
    custodian_fee_rate: float | None = None
    service_fee_rate: float | None = None


class AchievementRow(BaseModel):
    """雪球业绩单行：区间收益 / 回撤 / 同类排名（原始事实）。"""

    performance_type: str | None = None  # 年度业绩 / 阶段业绩
    period: str | None = None
    return_rate: float | None = None     # %
    max_drawdown: float | None = None    # %
    category_rank: str | None = None     # 如 "308/1070"


class FundRating(BaseModel):
    """第三方评级（天天基金评级总汇，原始事实）。"""

    fund_code: str
    five_star_count: int | None = None
    rating_sh: float | None = None       # 上海证券
    rating_zs: float | None = None       # 招商证券
    rating_ja: float | None = None       # 济安金信
    rating_mx: float | None = None       # 晨星


class IndexPoint(BaseModel):
    """基准指数单日收盘点（原始事实，存放于外部 Store）。"""

    nav_date: date
    close: float | None = None


def resolve_benchmark_code(fund: "Fund") -> str | None:
    """从业绩比较基准文本 / 基金类型解析可拉取的指数代码（东财源需市场前缀）。

    启发式（V1，显式声明）：
    - 基准文本含"中证500"→ sh000905、"沪深300"→ sh000300、"上证指数"→ sh000001、
      "创业板"→ sz399006；
    - 文本未命中时，增强指数型基金缺省其中证500；
    - 其余返回 None（不计算超额收益，由报告注明）。
    注意：混合型基准常为"股 + 债"复合，按股票部分近似，属已知简化。
    """
    text = fund.benchmark or ""
    if "中证500" in text:
        return "sh000905"
    if "沪深300" in text:
        return "sh000300"
    if "上证指数" in text:
        return "sh000001"
    if "创业板" in text:
        return "sz399006"
    if fund.fund_type and "增强指数" in fund.fund_type:
        return "sh000905"
    return None


class Fund(BaseModel):
    """基金完整信息（存放于外部 Store，State 不直接携带）。"""

    id: str
    name: str
    full_name: str | None = None
    fund_type: str | None = None
    manager_name: str | None = None
    company: str | None = None
    custodian: str | None = None                   # 托管银行
    benchmark: str | None = None
    inception_date: date | None = None
    aum: float | None = None                       # 单位：亿元
    currency: str = "CNY"
    rating_agency: str | None = None
    rating: str | None = None
    investment_strategy: str | None = None
    investment_objective: str | None = None
    source: str
    as_of: datetime
    data_quality: DataQuality = DataQuality.COMPLETE


class FundSummary(BaseModel):
    """State 轻量版基金摘要。"""

    id: str
    name: str
    fund_type: str | None = None
    aum: float | None = None
    manager_name: str | None = None
    as_of: datetime
    data_quality: DataQuality = DataQuality.COMPLETE


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
    source: str
    as_of: datetime
    data_quality: DataQuality = DataQuality.COMPLETE


def summarize_fund(fund: Fund) -> FundSummary:
    """Fund → FundSummary（State 只保留摘要）。"""
    return FundSummary(
        id=fund.id,
        name=fund.name,
        fund_type=fund.fund_type,
        aum=fund.aum,
        manager_name=fund.manager_name,
        as_of=fund.as_of,
        data_quality=fund.data_quality,
    )


def parse_report_period(raw: str | None) -> tuple[int, int] | None:
    """解析报告期字符串（akshare 季度原文，如"2024年1季度股票投资明细"）→ (年, 季度)。"""
    if not raw:
        return None
    m = _QUARTER_RE.search(str(raw))
    return (int(m.group(1)), int(m.group(2))) if m else None


def latest_report_period(holdings: list["Holding"]) -> str | None:
    """持仓中最新的报告期原文；无可解析报告期时返回 None（不编造）。"""
    best: tuple[tuple[int, int], str] | None = None
    for h in holdings:
        parsed = parse_report_period(h.report_date)
        if parsed and (best is None or parsed > best[0]):
            best = (parsed, h.report_date)
    return best[1] if best else None


def top_holdings(holdings: list["Holding"], n: int = 10) -> list["Holding"]:
    """最新报告期内按占净值比例降序的前 n 条（None 排最后）。

    akshare 按季度分块返回全年持仓，直接取前 n 条会混入最早季度，
    必须先锁定最新报告期再排序。
    """
    period = latest_report_period(holdings)
    rows = [h for h in holdings if period is None or h.report_date == period]
    return sorted(rows, key=lambda h: (h.hold_ratio is None, -(h.hold_ratio or 0.0)))[:n]


def quality_of(*fields: object) -> DataQuality:
    """根据关键字段缺失情况推导 data_quality：全缺 missing，部分缺 partial，否则 complete。"""
    present = [f is not None for f in fields]
    if not any(present):
        return DataQuality.MISSING
    if not all(present):
        return DataQuality.PARTIAL
    return DataQuality.COMPLETE


__all__ = [
    "NAVPoint",
    "Holding",
    "IndustryAllocRow",
    "AssetAllocRow",
    "FeeInfo",
    "AchievementRow",
    "FundRating",
    "IndexPoint",
    "resolve_benchmark_code",
    "Fund",
    "FundSummary",
    "FundPerformance",
    "summarize_fund",
    "parse_report_period",
    "latest_report_period",
    "top_holdings",
    "quality_of",
]
