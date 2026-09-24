"""Analyzer 节点（Node 合同 §4）。

职责：执行**确定性金融计算**。强约束：关键金融指标不得由 LLM 计算。
- 从外部 Store 按需加载净值序列 → Analysis Engine 纯函数 → analysis + calculation 类型 Evidence；
- evidence 只允许追加；
- Peer 对比占位：query 中手动传入的对比基金（plan.fund_ids 第 1 个为主基金，其余为 peer）。
"""

import logging
import uuid
from itertools import combinations
from typing import TypedDict
from datetime import datetime, timedelta

from analysis import (
    benchmark_comparison,
    compute_fund_metrics,
    fund_concentration,
    holdings_overlap,
    market_split,
)
from domain.analysis import (
    AnalysisResult,
    FundConcentration,
    FundHoldingsMetrics,
    FundMetrics,
    HoldingsOverlap,
    PeerComparison,
    PeerMetricsRow,
    PerformanceAnalysis,
    RiskAnalysis,
)
from domain.evidence import Evidence, EvidenceType
from domain.fund import Holding, resolve_benchmark_code
from domain.plan import ResearchPlan
from domain.shared import DataQuality
from domain.task_type import TaskType
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

        # 超额收益/跟踪误差：按各基金解析出的基准指数计算（无法解析或无指数数据则留空）
        excess_by_fund: dict[str, tuple[float | None, float | None]] = {}
        benchmark_codes: dict[str, str | None] = {}
        for fid in fund_ids:
            fund = self._store.get_fund(fid)
            code = resolve_benchmark_code(fund) if fund else None
            benchmark_codes[fid] = code
            index_points = self._store.get_index_series(code) if code else []
            if code and index_points:
                excess_by_fund[fid] = benchmark_comparison(
                    _window_points(fid), metrics_by_fund[fid].nav_basis, index_points
                )

        # 持仓分析：集中度与市场分布对所有任务计算（研究报告同样呈现）；
        # 重叠度仅多基金场景（对比价值所在），PeerComparison.concentration 仅对比任务填充
        task_type = plan.task_type if plan else state.get("task_type")
        holdings_by_fund: dict[str, list[Holding]] = {
            fid: self._store.get_holdings(fid) for fid in fund_ids
        }
        concentration_all = [fund_concentration(holdings_by_fund[fid], fid) for fid in fund_ids]
        splits = {fid: market_split(holdings_by_fund[fid]) for fid in fund_ids}
        holdings_metrics = [
            FundHoldingsMetrics(
                fund_id=fid,
                top10_sum=c.top10_sum,
                holding_count=c.holding_count,
                market_split=splits[fid],
            )
            for fid, c in zip(fund_ids, concentration_all)
        ]
        is_comparison = task_type == TaskType.FUND_COMPARISON and len(fund_ids) > 1
        concentration = concentration_all if is_comparison else []
        overlaps: list[HoldingsOverlap] = []
        if is_comparison:
            overlaps = [
                holdings_overlap(holdings_by_fund[a], holdings_by_fund[b], a, b)
                for a, b in combinations(fund_ids, 2)
            ]
            if not any(holdings_by_fund.values()):
                issues.append("多基金对比：持仓数据缺失，未计算持仓集中度与重叠度")

        analysis = self._build_analysis(
            primary_id,
            fund_ids,
            metrics_by_fund,
            concentration,
            overlaps,
            holdings_metrics,
            excess_by_fund,
            benchmark_codes,
        )
        evidence = self._build_evidence(
            fund_ids, metrics_by_fund, alignment, holdings_metrics, overlaps,
            excess_by_fund, benchmark_codes,
        )
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
        concentration: list[FundConcentration] | None = None,
        overlaps: list[HoldingsOverlap] | None = None,
        holdings_metrics: list[FundHoldingsMetrics] | None = None,
        excess_by_fund: dict[str, tuple[float | None, float | None]] | None = None,
        benchmark_codes: dict[str, str | None] | None = None,
    ) -> AnalysisResult:
        excess_by_fund = excess_by_fund or {}
        benchmark_codes = benchmark_codes or {}
        primary = metrics_by_fund[primary_id]
        primary_excess, primary_te = excess_by_fund.get(primary_id, (None, None))
        performance = PerformanceAnalysis(
            fund_id=primary_id,
            period_start=primary.period_start,
            period_end=primary.period_end,
            nav_point_count=primary.nav_point_count,
            cumulative_return=primary.cumulative_return,
            annualized_return=primary.annualized_return,
            yearly_returns=primary.yearly_returns,
            rolling_1y=primary.rolling_1y,
            benchmark_code=benchmark_codes.get(primary_id),
            excess_return=primary_excess,
            tracking_error=primary_te,
            data_quality=primary.data_quality,
        )
        risk = RiskAnalysis(
            fund_id=primary_id,
            annual_volatility=primary.annual_volatility,
            max_drawdown=primary.max_drawdown,
            max_drawdown_recovery_days=primary.max_drawdown_recovery_days,
            sharpe=primary.sharpe,
            sortino=primary.sortino,
            data_quality=primary.data_quality,
        )
        peer_comparison = None
        if len(fund_ids) > 1:
            peer_comparison = PeerComparison(
                base_fund_id=primary_id,
                rows=[
                    PeerMetricsRow(
                        fund_id=fid,
                        period_start=m.period_start,
                        period_end=m.period_end,
                        nav_point_count=m.nav_point_count,
                        cumulative_return=m.cumulative_return,
                        annualized_return=m.annualized_return,
                        annual_volatility=m.annual_volatility,
                        max_drawdown=m.max_drawdown,
                        sharpe=m.sharpe,
                        sortino=m.sortino,
                        benchmark_code=benchmark_codes.get(fid),
                        excess_return=(excess_by_fund.get(fid, (None, None)))[0],
                        tracking_error=(excess_by_fund.get(fid, (None, None)))[1],
                        nav_basis=m.nav_basis,
                    )
                    for fid, m in metrics_by_fund.items()
                ],
                concentration=concentration or [],
                overlaps=overlaps or [],
            )
        return AnalysisResult(
            performance=performance,
            risk=risk,
            peer_comparison=peer_comparison,
            holdings_metrics=holdings_metrics or [],
        )

    def _build_evidence(
        self,
        fund_ids: list[str],
        metrics_by_fund: dict[str, FundMetrics],
        alignment: tuple | None = None,
        holdings_metrics: list[FundHoldingsMetrics] | None = None,
        overlaps: list[HoldingsOverlap] | None = None,
        excess_by_fund: dict[str, tuple[float | None, float | None]] | None = None,
        benchmark_codes: dict[str, str | None] | None = None,
    ) -> list[Evidence]:
        """每只基金一条指标 calculation Evidence + 持仓分析 Evidence + 重叠度 Evidence（§9）。"""
        excess_by_fund = excess_by_fund or {}
        benchmark_codes = benchmark_codes or {}
        evidences = []
        for fid in fund_ids:
            m = metrics_by_fund[fid]
            fid_excess, fid_te = excess_by_fund.get(fid, (None, None))
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
                        "max_drawdown_recovery_days": m.max_drawdown_recovery_days,
                        "sharpe": m.sharpe,
                        "sortino": m.sortino,
                        "yearly_returns": m.yearly_returns,
                        "rolling_1y": m.rolling_1y.model_dump() if m.rolling_1y else None,
                        "benchmark_code": benchmark_codes.get(fid),
                        "excess_return": fid_excess,
                        "tracking_error": fid_te,
                        "nav_basis": m.nav_basis,
                        "alignment_window": [str(alignment[0]), str(alignment[1])] if alignment else None,
                    },
                    data_quality=m.data_quality,
                    raw_ref=FundStore.nav_ref(fid),
                )
            )
        for h in holdings_metrics or []:
            if h.top10_sum is None and h.market_split is None:
                continue
            evidences.append(
                Evidence(
                    id=f"ev-{uuid.uuid4().hex[:12]}",
                    evidence_type=EvidenceType.CALCULATION,
                    source=_ANALYSIS_SOURCE,
                    source_detail="确定性持仓分析计算（Analysis Engine，无 LLM）",
                    as_of=datetime.now(),
                    value={
                        "metric": "holdings_metrics",
                        "fund_id": h.fund_id,
                        "top10_sum": h.top10_sum,
                        "holding_count": h.holding_count,
                        "market_split": h.market_split.model_dump() if h.market_split else None,
                    },
                    data_quality=DataQuality.COMPLETE,
                    raw_ref=FundStore.holdings_ref(h.fund_id),
                )
            )
        for o in overlaps or []:
            if o.overlap_ratio is None:
                continue
            evidences.append(
                Evidence(
                    id=f"ev-{uuid.uuid4().hex[:12]}",
                    evidence_type=EvidenceType.CALCULATION,
                    source=_ANALYSIS_SOURCE,
                    source_detail="确定性持仓对比计算（Analysis Engine，无 LLM）",
                    as_of=datetime.now(),
                    value={
                        "metric": "holdings_overlap",
                        "fund_a": o.fund_a,
                        "fund_b": o.fund_b,
                        "overlap_ratio": o.overlap_ratio,
                        "common_names": o.common_names,
                    },
                    data_quality=DataQuality.COMPLETE,
                    raw_ref=FundStore.holdings_ref(o.fund_a),
                )
            )
        return evidences


__all__ = ["AnalyzerNode", "AnalyzerOutput"]
