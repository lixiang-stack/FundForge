"""分析结果领域模型（docs/TechnicalContract.md §9）。

Analysis Engine 的产出结构。portfolio 分析为 V1 Non-Goal，暂不建模。
"""

from datetime import date

from pydantic import BaseModel, Field

from domain.shared import DataQuality


class PerformanceAnalysis(BaseModel):
    """主基金业绩分析。"""

    fund_id: str
    period_start: date | None = None
    period_end: date | None = None
    nav_point_count: int = 0
    cumulative_return: float | None = None
    annualized_return: float | None = None
    data_quality: DataQuality = DataQuality.COMPLETE


class RiskAnalysis(BaseModel):
    """主基金风险分析。"""

    fund_id: str
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    data_quality: DataQuality = DataQuality.COMPLETE


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
    sharpe: float | None = None
    nav_basis: str | None = None                   # 净值口径："acc" | "unit"
    data_quality: DataQuality = DataQuality.COMPLETE


class AnalysisResult(BaseModel):
    """分析结果（写入 State 的结构化中间结果，体积小、可直接共享）。"""

    performance: PerformanceAnalysis
    risk: RiskAnalysis
    peer_comparison: PeerComparison | None = None


__all__ = [
    "PerformanceAnalysis",
    "RiskAnalysis",
    "PeerMetricsRow",
    "FundConcentration",
    "HoldingsOverlap",
    "PeerComparison",
    "FundMetrics",
    "AnalysisResult",
]
