"""Screen Finalize 节点（fund_screening，Step 1）。

职责（agent/docs/fund-screening.md §5）：对预选集执行预选集级硬过滤与最终排序，
产出 ScreenResult（短名单 + 全部披露）。

强约束：全确定性；指标缺失 = 剔除并披露，绝不放宽阈值、绝不降窗口硬算。
0 只时输出明确原因（剔除最多的条件），1~N 只如实输出。
"""

import logging
from datetime import datetime
from typing import Any, NamedTuple, TypedDict

from domain.analysis import AnalysisResult, PeerMetricsRow
from analysis import DAYS_PER_YEAR, DAYS_PER_YEAR_JULIAN
from formatting import fmt_pct, fmt_ratio
from domain.screening import (
    ANCHOR_COLUMN_LABELS,
    BIAS_DISCLOSURE,
    SORT_ATTRS,
    SORT_LABELS,
    ScreenResult,
    ScreenSpec,
    ScreeningMeta,
    ShortlistEntry,
    SortKey,
)
from domain.shared import coerce_model
from domain.fund import Fund, FundSummary, NAVPoint
from state import FundForgeState
from store import FundStore

logger = logging.getLogger(__name__)


class RankedCandidate(NamedTuple):
    """排序后的候选：排序键取自 _sort_value（锚点值或指标行字段）。"""

    fund_id: str
    row: PeerMetricsRow
    sort_value: float


class ScreenFinalizeOutput(TypedDict, total=False):
    """Screen Finalize 节点输出（screening_result）。"""

    screening_result: ScreenResult


class ScreenFinalizeNode:
    """Screen Finalize 节点：预选集 → 硬过滤 → 排序 → Top N（全确定性）。"""

    def __init__(self, store: FundStore) -> None:
        self._store = store

    def __call__(self, state: FundForgeState) -> ScreenFinalizeOutput:
        spec = ScreenSpec.from_state(state.get("screen_spec")) or ScreenSpec(raw_query="")
        meta = coerce_model(state.get("screening_meta"), ScreeningMeta) or ScreeningMeta()
        analysis = coerce_model(state.get("analysis"), AnalysisResult)
        summaries = self._summary_map(state)
        rank_rows: dict[str, dict] = dict(state.get("screen_rank_rows") or {})
        preselected_rows: list[PeerMetricsRow] = (
            list(analysis.peer_comparison.rows) if analysis and analysis.peer_comparison else []
        )

        excluded: dict[str, list[str]] = {}  # 剔除原因 → fund_ids（保序）
        candidates: list[tuple[str, PeerMetricsRow]] = []
        for row in preselected_rows:
            fid = row.fund_id
            reason = self._insufficient_history(spec, fid) or self._violates(
                spec, row, summaries.get(fid), self._store.get_fund(fid)
            )
            if reason:
                excluded.setdefault(reason, []).append(fid)
                continue
            candidates.append((fid, row))

        ranked = self._sort_candidates(spec, candidates, rank_rows, excluded)
        entries = [
            self._entry(c.fund_id, c.row, rank_rows, summaries)
            for c in ranked[: spec.top_n]
        ]

        result = ScreenResult(
            universe_size=meta.universe_size,
            preselected_size=meta.preselected_size,
            anchor=meta.anchor,
            sort_by=spec.sort_by,
            sort_order=spec.sort_order,
            top_n=spec.top_n,
            conditions=self._condition_lines(spec),
            entries=entries,
            data_gaps=self._data_gaps(spec, meta, excluded),
            empty_reason=self._empty_reason(meta, preselected_rows, entries, excluded),
        )
        logger.info(
            "screen_finalize: candidates=%d entries=%d excluded=%d",
            len(candidates), len(entries), sum(len(v) for v in excluded.values()),
        )
        return {"screening_result": result}

    # ---- 硬过滤（任一不满足即剔除，首个命中原因生效） ----

    def _insufficient_history(self, spec: ScreenSpec, fid: str) -> str | None:
        """历史充分性按基金全历史跨度判断（Store 全量净值）。

        不能用窗口化后的行内区间：trailing 窗口过滤本身会把起点裁到窗口内，
        离散净值点下行内 span 恒略小于窗口，边界日恰好被裁掉的基金会被误杀。
        """
        points = [p for p in self._store.get_nav_series(fid) if p.has_value]
        if len(points) < 2:
            return f"历史数据缺失或不足 {spec.lookback_years} 年"
        span_days = (points[-1].nav_date - points[0].nav_date).days
        if span_days < DAYS_PER_YEAR * spec.lookback_years:
            return f"历史不足 {spec.lookback_years} 年"
        return None

    def _violates(
        self,
        spec: ScreenSpec,
        row: PeerMetricsRow,
        summary: FundSummary | None,
        fund: Fund | None,
    ) -> str | None:
        if spec.min_sharpe is not None:
            if row.sharpe is None:
                return "夏普缺失"
            if row.sharpe < spec.min_sharpe:
                return f"夏普低于 {spec.min_sharpe:g}"
        if spec.max_max_drawdown is not None:
            if row.max_drawdown is None:
                return "最大回撤缺失"
            if row.max_drawdown < spec.max_max_drawdown:  # 回撤更负 = 更深
                return f"最大回撤深于 {abs(spec.max_max_drawdown):.0%}"
        if spec.max_volatility is not None:
            if row.annual_volatility is None:
                return "波动率缺失"
            if row.annual_volatility > spec.max_volatility:
                return f"波动率高于 {spec.max_volatility:.0%}"
        if spec.min_aum is not None or spec.max_aum is not None:
            aum = summary.aum if summary else None
            if aum is None:
                return "规模缺失"
            if spec.min_aum is not None and aum < spec.min_aum:
                return f"规模低于 {spec.min_aum:g} 亿"
            if spec.max_aum is not None and aum > spec.max_aum:
                return f"规模高于 {spec.max_aum:g} 亿"
        if spec.min_inception_years is not None:
            years = self._inception_years(fund)
            if years is None:
                return "成立年限缺失"
            if years < spec.min_inception_years:
                return f"成立不足 {spec.min_inception_years:g} 年"
        return None

    def _sort_candidates(
        self,
        spec: ScreenSpec,
        candidates: list[tuple[str, PeerMetricsRow]],
        rank_rows: dict[str, dict],
        excluded: dict[str, list[str]],
    ) -> list[RankedCandidate]:
        """排序键缺失 = 剔除并披露（排序依据不完整时宁缺毋滥）。"""
        ranked: list[RankedCandidate] = []
        for fid, row in candidates:
            if spec.sort_by == SortKey.PERIOD_RETURN:
                value = (rank_rows.get(fid) or {}).get("anchor_return")
            else:
                value = getattr(row, SORT_ATTRS[spec.sort_by])
            if not isinstance(value, (int, float)):
                excluded.setdefault("排序键缺失", []).append(fid)
                continue
            ranked.append(RankedCandidate(fid, row, float(value)))
        ranked.sort(key=lambda c: c.sort_value, reverse=spec.sort_order == "desc")
        return ranked

    # ---- 短名单条目（确定性一句话理由） ----

    def _entry(
        self,
        fid: str,
        row: PeerMetricsRow,
        rank_rows: dict[str, dict],
        summaries: dict[str, FundSummary],
    ) -> ShortlistEntry:
        summary = summaries.get(fid)
        fund = self._store.get_fund(fid)
        rank_row = rank_rows.get(fid) or {}
        period_return = rank_row.get("anchor_return")
        period_return = period_return if isinstance(period_return, (int, float)) else None
        aum = summary.aum if summary else None

        bits = [
            f"{ANCHOR_COLUMN_LABELS.get(rank_row.get('anchor_column', ''), rank_row.get('anchor_column', ''))}"
            f"收益 {fmt_pct(period_return)}",
            f"年化 {fmt_pct(row.annualized_return)}",
            f"最大回撤 {fmt_pct(row.max_drawdown)}",
            f"夏普 {fmt_ratio(row.sharpe)}",
        ]
        if aum is not None:
            bits.append(f"规模 {aum:.2f} 亿")
        return ShortlistEntry(
            fund_id=fid,
            name=summary.name if summary else rank_row.get("fund_name"),
            fund_type=summary.fund_type if summary else None,
            annualized_return=row.annualized_return,
            max_drawdown=row.max_drawdown,
            annual_volatility=row.annual_volatility,
            sharpe=row.sharpe,
            period_return=period_return,
            aum=aum,
            inception_years=self._inception_years(fund),
            rationale="，".join(bits) + "；满足全部筛选条件",
        )

    # ---- 披露装配 ----

    def _condition_lines(self, spec: ScreenSpec) -> list[str]:
        """ScreenSpec → 人类可读条件复述（报告「筛选条件（系统理解）」章节）。

        排除项仅在确实生效（与候选池主类有交集、在取数层面被剔除）时渲染，
        未生效的排除条件不进条件复述（走 unsupported/assumptions 披露）。
        """
        lines: list[str] = []
        if spec.fund_types:
            lines.append("类型：" + "、".join(spec.fund_types))
        if spec.fund_types:
            effective = [t for t in spec.exclude_types if t in set(spec.fund_types)]
            if effective:
                lines.append("排除类型：" + "、".join(effective))
        lines.append(f"回溯窗口：近{spec.lookback_years}年")
        if spec.min_period_return is not None:
            lines.append(f"区间收益 ≥ {fmt_pct(spec.min_period_return)}")
        if spec.min_sharpe is not None:
            lines.append(f"夏普 ≥ {spec.min_sharpe:g}")
        if spec.max_max_drawdown is not None:
            lines.append(f"最大回撤不深于 {fmt_pct(abs(spec.max_max_drawdown))}")
        if spec.max_volatility is not None:
            lines.append(f"年化波动 ≤ {fmt_pct(spec.max_volatility)}")
        if spec.min_aum is not None:
            lines.append(f"规模 ≥ {spec.min_aum:g} 亿")
        if spec.max_aum is not None:
            lines.append(f"规模 ≤ {spec.max_aum:g} 亿")
        if spec.min_inception_years is not None:
            lines.append(f"成立年限 ≥ {spec.min_inception_years:g} 年")
        direction = "升序" if spec.sort_order == "asc" else "降序"
        lines.append(f"排序：{SORT_LABELS[spec.sort_by]}{direction}，取 Top {spec.top_n}")
        return lines

    def _data_gaps(
        self,
        spec: ScreenSpec,
        meta: ScreeningMeta,
        excluded: dict[str, list[str]],
    ) -> list[str]:
        gaps: list[str] = []
        gaps.extend(spec.unsupported_requirements)
        if spec.uses_risk_metrics():
            gaps.append(BIAS_DISCLOSURE)
        for reason, fids in excluded.items():
            gaps.append(f"预选集内剔除「{reason}」：{len(fids)} 只（{'、'.join(fids)}）")
        if meta.skipped_no_anchor:
            label = ANCHOR_COLUMN_LABELS.get(meta.anchor_column, meta.anchor_column)
            gaps.append(f"候选池中 {meta.skipped_no_anchor} 只因缺{label}收益数据未参与预筛")
        if meta.filtered_by_conditions:
            gaps.append(f"候选池中 {meta.filtered_by_conditions} 只未满足候选池级条件（收益阈值等）")
        # 去重保序（unsupported 可能与固定文案重叠）
        seen: set[str] = set()
        return [gap for gap in gaps if not (gap in seen or seen.add(gap))]

    def _empty_reason(
        self,
        meta: ScreeningMeta,
        preselected_rows: list[PeerMetricsRow],
        entries: list[ShortlistEntry],
        excluded: dict[str, list[str]],
    ) -> str | None:
        if entries:
            return None
        if meta.preselected_size == 0:
            return "候选池预筛后无候选基金（条件过严或排行数据缺失）"
        if not preselected_rows:
            return "预选集为空（候选池为空或排行数据源失败），无法给出短名单"
        if excluded:
            reason, fids = max(excluded.items(), key=lambda kv: len(kv[1]))
            return f"无可满足条件的基金（剔除最多的条件：{reason}，{len(fids)} 只）"
        return "无可满足条件的基金"

    # ---- helpers ----

    def _summary_map(self, state: FundForgeState) -> dict[str, FundSummary]:
        summaries: dict[str, FundSummary] = {}
        for raw in state.get("funds_summary", []):
            s = raw if isinstance(raw, FundSummary) else FundSummary.model_validate(raw)
            summaries[s.id] = s
        return summaries

    @staticmethod
    def _inception_years(fund: Fund | None) -> float | None:
        if fund is None or fund.inception_date is None:
            return None
        return (datetime.now().date() - fund.inception_date).days / DAYS_PER_YEAR_JULIAN


__all__ = ["ScreenFinalizeNode", "ScreenFinalizeOutput"]
