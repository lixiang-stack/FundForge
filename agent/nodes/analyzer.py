"""Analyzer 节点（Node 合同 §4）。

职责：执行**确定性金融计算**。强约束：关键金融指标不得由 LLM 计算。
- 从外部 Store 按需加载净值序列 → Analysis Engine 纯函数 → analysis + calculation 类型 Evidence；
- evidence 只允许追加；
- Peer 对比占位：query 中手动传入的对比基金（plan.fund_ids 第 1 个为主基金，其余为 peer）。
"""

import logging
import uuid
from typing import TypedDict
from datetime import datetime, timedelta

from analysis import compute_fund_metrics
from domain.analysis import (
    AnalysisResult,
    FundMetrics,
    PeerComparison,
    PeerMetricsRow,
    PerformanceAnalysis,
    RiskAnalysis,
)
from domain.evidence import Evidence, EvidenceType
from domain.plan import ResearchPlan
from domain.shared import DataQuality
from state import FundForgeState
from store import FundStore

logger = logging.getLogger(__name__)

_ANALYSIS_SOURCE = "fundforge:analysis-engine"
_ALIGNMENT_MAX_DAYS = 365 * 10   # 对齐窗口上限：10 年
_MIN_ALIGNMENT_DAYS = 30         # 低于该窗口的对比无统计意义
_POINT_COUNT_DIFF_TOLERANCE = 0.01  # 同窗口净值点数差容忍度，超过即向下游披露


def _aligned_window(series: dict[str, list]) -> tuple | None:
    """多基金共同对齐区间：最晚起点 ~ 最早终点，最长 10 年。

    无法对齐（任一基金有效点不足 / 共同区间过短）返回 None。
    """
    spans = []
    for points in series.values():
        valid = [p for p in points if p.has_value]
        if len(valid) >= 2:
            spans.append((valid[0].nav_date, valid[-1].nav_date))
    if len(spans) < 2:
        return None
    start = max(s for s, _ in spans)
    end = min(e for _, e in spans)
    if (end - start).days > _ALIGNMENT_MAX_DAYS:
        start = end - timedelta(days=_ALIGNMENT_MAX_DAYS)
    if (end - start).days < _MIN_ALIGNMENT_DAYS:
        return None
    return start, end


class AnalyzerOutput(TypedDict, total=False):
    """Analyzer 节点输出（§4：analysis, evidence）。"""

    analysis: AnalysisResult
    evidence: list[Evidence]
    data_quality_issues: list[str]


class AnalyzerNode:
    """Analyzer 节点：读取 Store 数据 → 纯函数计算 → 结构化结果与 Evidence。"""

    def __init__(self, store: FundStore) -> None:
        self._store = store

    def __call__(self, state: FundForgeState) -> AnalyzerOutput:
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

        issues: list[str] = []
        alignment: tuple | None = None
        if len(fund_ids) > 1:
            series = {fid: self._store.get_nav_series(fid) for fid in fund_ids}
            alignment = _aligned_window(series)
            if alignment is None:
                issues.append(
                    "多基金对比：共同对齐区间不足（<30 个自然日），peer 对比跳过，"
                    "各基金指标按其自身全历史计算"
                )

        # 对比场景：全部基金按对齐区间重算（主基金指标与对比表口径一致）；
        # 单基金：按其自身全历史计算
        def _window_points(fid: str) -> list:
            points = self._store.get_nav_series(fid)
            if alignment is not None:
                start, end = alignment
                return [p for p in points if start <= p.nav_date <= end]
            return points

        metrics_by_fund: dict[str, FundMetrics] = {
            fid: compute_fund_metrics(_window_points(fid)) for fid in fund_ids
        }
        if len(fund_ids) > 1 and len({m.nav_basis for m in metrics_by_fund.values()}) > 1:
            # 对比基金口径必须一致：任一基金 acc 覆盖不全，全组拉回 unit 口径重算
            issues.append("净值口径不一致（部分基金累计净值覆盖不全），已统一按单位净值口径对比")
            metrics_by_fund = {
                fid: compute_fund_metrics(_window_points(fid), basis="unit")
                for fid in fund_ids
            }

        # 对齐窗口只统一端点、不统一逐日覆盖：各基金披露频率不同（如新基金建仓期
        # 按周披露）或数据源缺行都会造成同窗口点数差，指标横向对比口径偏松，须披露
        if len(fund_ids) > 1 and alignment is not None:
            counts = {fid: m.nav_point_count for fid, m in metrics_by_fund.items()}
            hi, lo = max(counts.values()), min(counts.values())
            if lo > 0 and (hi - lo) / lo > _POINT_COUNT_DIFF_TOLERANCE:
                detail = ", ".join(f"{fid}={cnt}" for fid, cnt in counts.items())
                issues.append(
                    f"多基金对比：同窗口内净值点数差超{_POINT_COUNT_DIFF_TOLERANCE:.0%}"
                    f"（{detail}），各基金逐日覆盖不一致，指标横向对比需谨慎"
                )

        analysis = self._build_analysis(primary_id, fund_ids, metrics_by_fund)
        evidence = self._build_evidence(fund_ids, metrics_by_fund, alignment)
        issues += [
            f"{fid}: 净值数据不足（{m.nav_point_count} 个有效点），指标不可信"
            for fid, m in metrics_by_fund.items()
            if m.data_quality != DataQuality.COMPLETE
        ]

        logger.info(
            "analyzer: analyzed %d funds (primary=%s, quality=%s, alignment=%s)",
            len(fund_ids),
            primary_id,
            analysis.performance.data_quality,
            alignment,
        )
        return AnalyzerOutput(
            analysis=analysis,
            evidence=[*state.get("evidence", []), *evidence],
            data_quality_issues=[*state.get("data_quality_issues", []), *issues],
        )

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
        alignment: tuple | None = None,
    ) -> list[Evidence]:
        """每只基金一条 calculation 类型 Evidence（§9：计算结果写入 Evidence）。"""
        evidences = []
        for fid in fund_ids:
            m = metrics_by_fund[fid]
            evidences.append(
                Evidence(
                    id=f"ev-{uuid.uuid4().hex[:12]}",
                    evidence_type=EvidenceType.CALCULATION,
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
                        "nav_basis": m.nav_basis,
                        "alignment_window": [str(alignment[0]), str(alignment[1])] if alignment else None,
                    },
                    data_quality=m.data_quality,
                    raw_ref=FundStore.nav_ref(fid),
                )
            )
        return evidences


__all__ = ["AnalyzerNode", "AnalyzerOutput"]
