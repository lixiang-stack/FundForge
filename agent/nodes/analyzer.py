"""Analyzer 节点（Node 合同 §4）。

职责：执行**确定性金融计算**。强约束：关键金融指标不得由 LLM 计算。
- 从外部 Store 按需加载净值序列 → Analysis Engine 纯函数 → analysis + calculation 类型 Evidence；
- evidence 只允许追加；
- Peer 对比占位：query 中手动传入的对比基金（plan.fund_ids 第 1 个为主基金，其余为 peer）。
"""

import logging
import uuid
from datetime import datetime

from analysis import compute_fund_metrics
from domain.analysis import (
    AnalysisResult,
    FundMetrics,
    PeerComparison,
    PeerMetricsRow,
    PerformanceAnalysis,
    RiskAnalysis,
)
from domain.evidence import Evidence
from domain.plan import ResearchPlan
from state import FundForgeState
from store import FundStore

logger = logging.getLogger(__name__)

_ANALYSIS_SOURCE = "fundforge:analysis-engine"


class AnalyzerNode:
    """Analyzer 节点：读取 Store 数据 → 纯函数计算 → 结构化结果与 Evidence。"""

    def __init__(self, store: FundStore) -> None:
        self._store = store

    def __call__(self, state: FundForgeState) -> dict:
        plan = ResearchPlan.from_state(state.get("research_plan"))
        fund_ids = list(state.get("fund_ids", [])) or (list(plan.fund_ids) if plan else [])
        if not fund_ids:
            logger.warning("analyzer: 没有 fund_ids，跳过分析")
            return {}

        # 主基金：优先 plan.primary_fund_id（显式声明），回退 fund_ids[0]
        primary_id = plan.primary_fund_id if plan and plan.primary_fund_id else fund_ids[0]
        if primary_id not in fund_ids:
            logger.warning("analyzer: primary_fund_id=%s 不在采集列表中，回退首个", primary_id)
            primary_id = fund_ids[0]

        metrics_by_fund = {
            fund_id: compute_fund_metrics(self._store.get_nav_series(fund_id))
            for fund_id in fund_ids
        }

        analysis = self._build_analysis(primary_id, fund_ids, metrics_by_fund)
        evidence = self._build_evidence(fund_ids, metrics_by_fund)
        issues = [
            f"{fid}: 净值数据不足（{m.nav_point_count} 个有效点），指标不可信"
            for fid, m in metrics_by_fund.items()
            if m.data_quality != "complete"
        ]

        logger.info(
            "analyzer: analyzed %d funds (primary=%s, quality=%s)",
            len(fund_ids),
            primary_id,
            analysis.performance.data_quality,
        )
        return {
            "analysis": analysis,
            "evidence": [*state.get("evidence", []), *evidence],
            "data_quality_issues": [*state.get("data_quality_issues", []), *issues],
        }

    def _build_analysis(
        self,
        primary_id: str,
        fund_ids: list[str],
        metrics_by_fund: dict[str, FundMetrics],
    ) -> AnalysisResult:
        primary = metrics_by_fund[primary_id]
        performance = PerformanceAnalysis(
            fund_id=primary_id,
            period_start=primary.period_start,
            period_end=primary.period_end,
            nav_point_count=primary.nav_point_count,
            cumulative_return=primary.cumulative_return,
            annualized_return=primary.annualized_return,
            data_quality=primary.data_quality,
        )
        risk = RiskAnalysis(
            fund_id=primary_id,
            annual_volatility=primary.annual_volatility,
            max_drawdown=primary.max_drawdown,
            sharpe=primary.sharpe,
            data_quality=primary.data_quality,
        )
        peer_comparison = None
        if len(fund_ids) > 1:
            peer_comparison = PeerComparison(
                base_fund_id=primary_id,
                rows=[
                    PeerMetricsRow(
                        fund_id=fid,
                        annualized_return=m.annualized_return,
                        annual_volatility=m.annual_volatility,
                        max_drawdown=m.max_drawdown,
                        sharpe=m.sharpe,
                    )
                    for fid, m in metrics_by_fund.items()
                ],
            )
        return AnalysisResult(performance=performance, risk=risk, peer_comparison=peer_comparison)

    def _build_evidence(
        self,
        fund_ids: list[str],
        metrics_by_fund: dict[str, FundMetrics],
    ) -> list[Evidence]:
        """每只基金一条 calculation 类型 Evidence（§9：计算结果写入 Evidence）。"""
        evidences = []
        for fid in fund_ids:
            m = metrics_by_fund[fid]
            evidences.append(
                Evidence(
                    id=f"ev-{uuid.uuid4().hex[:12]}",
                    evidence_type="calculation",
                    source=_ANALYSIS_SOURCE,
                    source_detail="确定性量化计算（Analysis Engine，无 LLM）",
                    as_of=datetime.now(),
                    value={
                        "fund_id": fid,
                        "period_start": str(m.period_start) if m.period_start else None,
                        "period_end": str(m.period_end) if m.period_end else None,
                        "nav_point_count": m.nav_point_count,
                        "cumulative_return": m.cumulative_return,
                        "annualized_return": m.annualized_return,
                        "annual_volatility": m.annual_volatility,
                        "max_drawdown": m.max_drawdown,
                        "sharpe": m.sharpe,
                    },
                    data_quality=m.data_quality,
                    raw_ref=FundStore.nav_ref(fid),
                )
            )
        return evidences


__all__ = ["AnalyzerNode"]
