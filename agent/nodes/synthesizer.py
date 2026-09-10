"""Synthesizer 节点（Node 合同 §4）。

职责：组装最终报告。必须包含风险提示与「不构成投资建议」声明。
Phase 2：固定模板 + 基金摘要 + 确定性量化分析结果；结构化 Report 在 Phase 4 定义。
"""

import logging

from domain.analysis import PeerMetricsRow
from domain.plan import ResearchPlan
from state import FundForgeState

logger = logging.getLogger(__name__)

_DISCLAIMER = "免责声明：本报告不构成任何投资建议。"

_NO_FUND_GUIDANCE = "请在提问中包含 6 位基金代码，例如：分析基金 519770"


def _fmt_pct(value: float | None) -> str:
    """小数 → 百分比字符串（2 位小数）；None → 未知。"""
    return f"{value * 100:.2f}%" if value is not None else "未知"


def _fmt_metric_row(row: PeerMetricsRow) -> str:
    """PeerMetricsRow → 报告行。"""
    sharpe = f"{row.sharpe:.2f}" if row.sharpe is not None else "未知"
    return (
        f"- {row.fund_id}: 年化收益 {_fmt_pct(row.annualized_return)}，"
        f"年化波动 {_fmt_pct(row.annual_volatility)}，"
        f"最大回撤 {_fmt_pct(row.max_drawdown)}，"
        f"夏普 {sharpe}"
    )


def synthesizer(state: FundForgeState) -> dict:
    summaries = state.get("funds_summary", [])
    evidence = state.get("evidence", [])
    issues = state.get("data_quality_issues", [])
    analysis = state.get("analysis")
    plan = ResearchPlan.from_state(state.get("research_plan"))
    notes = list(plan.notes) if plan else []

    lines = [
        "FundForge 研究报告（Phase 2 骨架输出）",
        "========================================",
        f"已采集基金：{len(summaries)} 只，证据条目：{len(evidence)} 条",
    ]
    for s in summaries:
        aum = f"{s.aum:.2f}亿" if s.aum is not None else "未知"
        lines.append(
            f"- {s.id} {s.name}（{s.fund_type or '类型未知'}，规模 {aum}，"
            f"基金经理 {s.manager_name or '未知'}，数据质量 {s.data_quality}）"
        )
    if not summaries:
        lines.append("未能采集到基金数据。")
        lines.extend(f"- {n}" for n in notes)
        lines.append(_NO_FUND_GUIDANCE)

    if analysis is not None:
        perf = analysis.performance
        lines += [
            "",
            "量化分析（确定性计算，无 LLM）：",
            f"- 区间 {perf.period_start} ~ {perf.period_end}（{perf.nav_point_count} 个净值点），"
            f"累计收益 {_fmt_pct(perf.cumulative_return)}，年化收益 {_fmt_pct(perf.annualized_return)}",
        ]
        if analysis.peer_comparison is not None:
            lines.append(f"同类对比（基准 {analysis.peer_comparison.base_fund_id}）：")
            lines.extend(_fmt_metric_row(row) for row in analysis.peer_comparison.rows)
            lines.append(
                "注：各基金指标基于其自身全部历史净值计算，区间起点不同，"
                "横向对比仅供参考（后续版本将做区间对齐）。"
            )

    if issues:
        lines.append("数据质量提示：")
        lines.extend(f"- {i}" for i in issues)
    lines += [
        "",
        "尚未接入 LLM 推理与评估环节。",
        _DISCLAIMER,
    ]

    logger.info("synthesizer: report generated (%d funds)", len(summaries))
    return {"report": "\n".join(lines)}
