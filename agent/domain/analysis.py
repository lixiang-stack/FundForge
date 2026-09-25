"""分析结果领域模型（docs/TechnicalContract.md §9）。

Analysis Engine 的产出结构。portfolio 分析为 V1 Non-Goal，暂不建模。
"""

from datetime import date

from pydantic import BaseModel, Field

from domain.shared import DataQuality


class RollingReturnSummary(BaseModel):
    """滚动收益摘要（每个滚动窗口的累计收益的分布）。"""

    window_days: int = 252
    min: float | None = None
    median: float | None = None
    max: float | None = None


class MarketSplit(BaseModel):
    """最新报告期披露持仓的市场分布（按股票代码形态分类，各类占净值比例合计 %）。"""

    a_share_ratio: float | None = None      # A股
    hk_share_ratio: float | None = None     # 港股
    overseas_ratio: float | None = None     # 美股等海外
    other_ratio: float | None = None


class PerformanceAnalysis(BaseModel):
    """主基金业绩分析。"""

    fund_id: str
    period_start: date | None = None
    period_end: date | None = None
    nav_point_count: int = 0
    cumulative_return: float | None = None
    annualized_return: float | None = None
    yearly_returns: dict[str, float | None] | None = None   # 自然年 → 年内累计收益（不足 2 个有效点的年份不列入）
    rolling_1y: RollingReturnSummary | None = None
    trailing_returns: dict[str, float | None] | None = None  # 区间收益：1m/3m/6m/1y（21/63/126/252 个交易日），不足窗口为 None
    benchmark_code: str | None = None    # 基准指数代码（启发式解析）；None = 无法解析不计算
    excess_return: float | None = None   # 对齐区间内基金累计收益 − 基准累计收益
    tracking_error: float | None = None  # 近似跟踪误差（对齐日收益差的年化标准差）
    data_quality: DataQuality = DataQuality.COMPLETE


class RiskAnalysis(BaseModel):
    """主基金风险分析。"""

    fund_id: str
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    max_drawdown_recovery_days: int | None = None   # 最大回撤谷底到净值修复的自然日数；未修复为 None
    sharpe: float | None = None
    sortino: float | None = None
    data_quality: DataQuality = DataQuality.COMPLETE


class FundHoldingsMetrics(BaseModel):
    """单基金持仓分析（集中度 + 市场分布），全部任务类型均计算。"""

    fund_id: str
    top10_sum: float | None = None      # 前十大占净值比例合计（%）
    holding_count: int = 0
    market_split: MarketSplit | None = None


class PeerMetricsRow(BaseModel):
    """Peer 对比单行指标（含主基金自身，全部基金同口径同区间）。"""

    fund_id: str
    period_start: date | None = None
    period_end: date | None = None
    nav_point_count: int = 0
    cumulative_return: float | None = None
    annualized_return: float | None = None
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    benchmark_code: str | None = None
    excess_return: float | None = None
    tracking_error: float | None = None
    trailing_returns: dict[str, float | None] | None = None  # 区间收益：1m/3m/6m/1y（同口径对齐期末）
    nav_basis: str | None = None


class FundConcentration(BaseModel):
    """单基金最新报告期前十大持仓集中度。"""

    fund_id: str
    top10_sum: float | None = None      # 前十大占净值比例合计（%）
    holding_count: int = 0              # 最新报告期持仓个股数


class HoldingsOverlap(BaseModel):
    """两基金最新报告期持仓重叠（按股票名 Jaccard）。"""

    fund_a: str
    fund_b: str
    overlap_ratio: float | None = None
    common_names: list[str] = Field(default_factory=list)


class PeerComparison(BaseModel):
    """Peer 对比：多基金对齐区间指标 + 持仓对比维度（集中度 / 重叠度）。"""

    base_fund_id: str
    rows: list[PeerMetricsRow]
    concentration: list[FundConcentration] = Field(default_factory=list)
    overlaps: list[HoldingsOverlap] = Field(default_factory=list)


class FundMetrics(BaseModel):
    """单只基金的原始计算指标（Analysis Engine 产出，节点据此组装合同模型）。"""

    period_start: date | None = None
    period_end: date | None = None
    nav_point_count: int = 0
    cumulative_return: float | None = None
    annualized_return: float | None = None
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    max_drawdown_recovery_days: int | None = None
    sharpe: float | None = None
    sortino: float | None = None
    yearly_returns: dict[str, float | None] | None = None
    rolling_1y: RollingReturnSummary | None = None
    trailing_returns: dict[str, float | None] | None = None  # 区间收益：1m/3m/6m/1y（21/63/126/252 个交易日）
    nav_basis: str                                # 净值口径："acc" | "unit"（Engine 必填，默认选择属于 Engine 而非调用方）
    data_quality: DataQuality = DataQuality.COMPLETE


class AnalysisResult(BaseModel):
    """分析结果（写入 State 的结构化中间结果，体积小、可直接共享）。"""

    performance: PerformanceAnalysis
    risk: RiskAnalysis
    peer_comparison: PeerComparison | None = None
    holdings_metrics: list[FundHoldingsMetrics] = Field(default_factory=list)


__all__ = [
    "PerformanceAnalysis",
    "RiskAnalysis",
    "RollingReturnSummary",
    "MarketSplit",
    "FundHoldingsMetrics",
    "PeerMetricsRow",
    "FundConcentration",
    "HoldingsOverlap",
    "PeerComparison",
    "FundMetrics",
    "AnalysisResult",
]
