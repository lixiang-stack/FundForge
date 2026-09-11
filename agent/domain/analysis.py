"""分析结果领域模型（docs/TechnicalContract.md §9）。

Analysis Engine 的产出结构。portfolio 分析为 V1 Non-Goal，暂不建模。
"""

from datetime import date

from pydantic import BaseModel

from domain.fund import FundSummary
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
    """Peer 对比单行指标（含主基金自身）。"""

    fund_id: str
    annualized_return: float | None = None
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None


class PeerComparison(BaseModel):
    """Peer 对比占位：query 中手动传入 1–2 只对比基金（Phase 6 完善）。"""

    base_fund_id: str
    rows: list[PeerMetricsRow]


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
    "PeerComparison",
    "FundMetrics",
    "AnalysisResult",
]
