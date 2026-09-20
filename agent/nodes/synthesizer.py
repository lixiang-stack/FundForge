"""Synthesizer 节点（Node 合同 §4）。

职责：把 State 中的结构化结果组装成标准 Report（§11），并渲染 Markdown。
- 文字部分用确定性模板（不调用 LLM，零成本可单测）；
- risks_and_disclaimers 强制包含合规声明；
- 关键结论可追溯：key_claims 即 Thesis 中通过证据绑定校验的 Claim；
- Thesis 缺失（LLM 降级）时仍产出完整结构的降级报告。
"""

import logging
from datetime import datetime
from typing import TypedDict

from domain.analysis import AnalysisResult, PeerComparison
from domain.evaluation import EvaluationResult, EvaluationStatus
from domain.evidence import TokenUsage
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.report import Report, ReportMetadata, render_markdown
from domain.shared import coerce_model
from domain.thesis import InvestmentThesis
from domain.task_type import TaskType
from state import FundForgeState

logger = logging.getLogger(__name__)

_DISCLAIMER = "本报告由程序自动生成，不构成任何投资建议。"
_DATA_ADVISORY = "历史业绩不代表未来表现，量化指标基于历史净值计算，存在模型简化假设。"
_NO_FUND_GUIDANCE = "请在提问中包含 6 位基金代码，例如：分析基金 519770"
_ALIGNMENT_NOTE = "注：各基金指标已对齐至共同区间（最短历史为准，最长 10 年）计算，口径一致。"

_NO_THESIS_NOTE = "投资论点未生成（LLM 不可用或校验未通过），本报告仅包含数据与确定性分析。"
_INSUFFICIENT_EVIDENCE_NOTE = (
    "证据不足：评估未通过（经 1 次修复后仍存在问题），上述结论的可靠性受限，请谨慎参考。"
)


class SynthesizerOutput(TypedDict, total=False):
    """Synthesizer 节点输出（§4：report）。"""

    report: Report


class SynthesizerNode:
    """Synthesizer 节点：组装结构化报告（§11）。"""

    def __call__(self, state: FundForgeState) -> SynthesizerOutput:
        # State 经 LangGraph 回传后可能是 dict，统一归一化为模型
        summaries = [
            s if isinstance(s, FundSummary) else FundSummary.model_validate(s)
            for s in state.get("funds_summary", [])
        ]
        evidence = state.get("evidence", [])
        tool_calls = state.get("tool_calls", [])
        issues = state.get("data_quality_issues", [])
        analysis = coerce_model(state.get("analysis"), AnalysisResult)
        thesis = coerce_model(state.get("investment_thesis"), InvestmentThesis)
        usage = coerce_model(state.get("token_usage"), TokenUsage) or TokenUsage()
        plan = ResearchPlan.from_state(state.get("research_plan"))
        notes = list(plan.notes) if plan else []
        is_comparison = plan is not None and plan.task_type == TaskType.FUND_COMPARISON

        primary = summaries[0] if summaries else None
        data_gaps = [*notes, *(thesis.data_gaps if thesis else [])]
        if not summaries and not notes:
            data_gaps.append(_NO_FUND_GUIDANCE)
        if thesis is None and evidence:
            data_gaps.append(_NO_THESIS_NOTE)

        evaluation = coerce_model(state.get("evaluation"), EvaluationResult)
        repair_applied = int(state.get("iteration", 0)) > 0
        if evaluation is not None and evaluation.status == EvaluationStatus.FAIL:
            # §4 Repair 原则：仍 Fail → 强制进入 Synthesizer，显式标注证据不足
            data_gaps.append(_INSUFFICIENT_EVIDENCE_NOTE)

        report = Report(
            title=(
                _comparison_title(summaries)
                if is_comparison
                else (
                    f"FundForge 基金研究报告：{primary.name}（{primary.id}）"
                    if primary
                    else "FundForge 基金研究报告"
                )
            ),
            generated_at=datetime.now(),
            request_id=state.get("request_id", ""),
            executive_summary=(
                _comparison_executive_summary(summaries, analysis, thesis)
                if is_comparison
                else _executive_summary(primary, summaries, analysis, thesis)
            ),
            fund_overview=summaries,
            holdings_analysis=_holdings_text(summaries, evidence),
            performance_analysis=(
                _comparison_performance_text(summaries, analysis)
                if is_comparison
                else _performance_text(primary, analysis)
            ),
            risk_analysis=(
                _comparison_risk_text(summaries, analysis)
                if is_comparison
                else _risk_text(primary, analysis)
            ),
            peer_comparison=(
                _comparison_peer_text(analysis, summaries)
                if is_comparison
                else _peer_text(analysis, summaries)
            ),
            manager_analysis=(
                _comparison_manager_text(summaries)
                if is_comparison
                else (
                    f"{primary.id} 现任基金经理：{primary.manager_name}。"
                    if primary and primary.manager_name
                    else None
                )
            ),
            investment_thesis=thesis,
            key_claims=list(thesis.claims) if thesis else [],
            data_gaps_and_limitations=data_gaps,
            risks_and_disclaimers=[
                *(thesis.risks if thesis else []),
                _DATA_ADVISORY,
                _DISCLAIMER,
            ],
            analysis=analysis,
            metadata=ReportMetadata(
                fund_count=len(summaries),
                evidence_count=len(evidence),
                tool_call_count=len(tool_calls),
                data_quality_issue_count=len(issues),
                thesis_generated=thesis is not None,
                evaluation_status=evaluation.status if evaluation else None,
                repair_applied=repair_applied,
                llm_calls=usage.llm_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                task_type=str(plan.task_type) if plan else None,
            ),
        )
        logger.info(
            "synthesizer: report built (%d funds, thesis=%s)",
            len(summaries),
            thesis is not None,
        )
        return SynthesizerOutput(report=report)


def _fmt_pct(value: float | None) -> str:
    """小数 → 百分比字符串（2 位小数）；None → 未知。"""
    return f"{value * 100:.2f}%" if value is not None else "未知"


def _executive_summary(
    primary: FundSummary | None,
    summaries: list[FundSummary],
    analysis: AnalysisResult | None,
    thesis: InvestmentThesis | None,
) -> str:
    if not summaries:
        return "未能采集到基金数据，无法形成研究结论。"
    lines = [
        f"本次研究覆盖 {len(summaries)} 只基金，主体为 {primary.id} {primary.name}"
        f"（{primary.fund_type or '类型未知'}）。",
    ]
    if analysis is not None:
        perf = analysis.performance
        lines.append(
            f"确定性量化分析显示：{perf.period_start} ~ {perf.period_end}"
            f"（{perf.nav_point_count} 个净值点）累计收益 {_fmt_pct(perf.cumulative_return)}，"
            f"年化收益 {_fmt_pct(perf.annualized_return)}。"
        )
    if thesis is not None:
        lines.append(f"投资论点：{thesis.suitability}")
    return " ".join(lines)


def _fund_label(fund_id: str, names: dict[str, str]) -> str:
    """「代码 名称」标签；名称缺失时退回纯代码。"""
    name = names.get(fund_id)
    return f"{fund_id} {name}" if name else fund_id


def _performance_text(primary: FundSummary | None, analysis: AnalysisResult | None) -> str:
    if analysis is None:
        return ""
    perf = analysis.performance
    subject = f"{primary.id} {primary.name}（主体基金）：" if primary else ""
    return (
        f"{subject}区间 {perf.period_start} ~ {perf.period_end}"
        f"（{perf.nav_point_count} 个净值点），"
        f"累计收益 {_fmt_pct(perf.cumulative_return)}，年化收益 {_fmt_pct(perf.annualized_return)}。"
    )


def _risk_text(primary: FundSummary | None, analysis: AnalysisResult | None) -> str:
    if analysis is None:
        return ""
    risk = analysis.risk
    sharpe = f"{risk.sharpe:.2f}" if risk.sharpe is not None else "未知"
    subject = f"{primary.id} {primary.name}（主体基金）：" if primary else ""
    return (
        f"{subject}年化波动率 {_fmt_pct(risk.annual_volatility)}，"
        f"最大回撤 {_fmt_pct(risk.max_drawdown)}，"
        f"夏普比率 {sharpe}。"
    )


def _peer_text(analysis: AnalysisResult | None, summaries: list[FundSummary] | None = None) -> str | None:
    if analysis is None or analysis.peer_comparison is None:
        return None
    pc = analysis.peer_comparison
    names = {s.id: s.name for s in (summaries or [])}
    lines = [f"基准基金 {_fund_label(pc.base_fund_id, names)}："]
    for row in pc.rows:
        sharpe = f"{row.sharpe:.2f}" if row.sharpe is not None else "未知"
        lines.append(
            f"- {_fund_label(row.fund_id, names)}: 年化收益 {_fmt_pct(row.annualized_return)}，"
            f"年化波动 {_fmt_pct(row.annual_volatility)}，"
            f"最大回撤 {_fmt_pct(row.max_drawdown)}，夏普 {sharpe}"
        )
    lines.append(_ALIGNMENT_NOTE)
    return "\n".join(lines)


def _comparison_title(summaries: list[FundSummary]) -> str:
    """对比报告标题：全部基金标签 vs 连接（research 标题不受影响）。"""
    labels = " vs ".join(f"{s.id} {s.name}" for s in summaries)
    return f"FundForge 基金对比报告：{labels}" if labels else "FundForge 基金对比报告"


def _comparison_executive_summary(
    summaries: list[FundSummary],
    analysis: AnalysisResult | None,
    thesis: InvestmentThesis | None,
) -> str:
    """对比摘要：对称表述 + 对齐区间 + 各基金年化收益 + 确定性领先者 + thesis 结论。"""
    if not summaries:
        return "未能采集到基金数据，无法形成对比结论。"
    labels = "、".join(f"{s.id} {s.name}" for s in summaries)
    lines = [f"本报告对比 {len(summaries)} 只基金：{labels}。"]
    rows = analysis.peer_comparison.rows if analysis and analysis.peer_comparison else []
    if rows:
        metric_bits = [
            f"{r.fund_id} 年化 {_fmt_pct(r.annualized_return)}"
            for r in rows
        ]
        metric_line = f"确定性量化分析：{'、'.join(metric_bits)}。"
        window = next((r for r in rows if r.period_start and r.period_end), None)
        if window:
            metric_line = f"对齐区间 {window.period_start} ~ {window.period_end}。" + metric_line
        if len(rows) > 1:
            best = max(
                (r for r in rows if r.annualized_return is not None),
                key=lambda r: r.annualized_return,
                default=None,
            )
            if best is not None:
                metric_line += f"对齐区间内年化收益领先：{best.fund_id}。"
        lines.append(metric_line)
    if thesis is not None:
        lines.append(f"投资论点：{thesis.suitability}")
    return " ".join(lines)


def _peer_rows(analysis: AnalysisResult | None) -> list:
    """对比任务的逐基金指标行（peer_comparison 缺失时为空，章节整节省略）。"""
    return analysis.peer_comparison.rows if analysis and analysis.peer_comparison else []


def _comparison_performance_text(summaries: list[FundSummary], analysis: AnalysisResult | None) -> str:
    """业绩分析（对比模式）：逐基金一行，对称呈现。"""
    names = {s.id: s.name for s in summaries}
    lines = [
        f"- {_fund_label(r.fund_id, names)}：区间 {r.period_start} ~ {r.period_end}"
        f"（{r.nav_point_count} 个净值点），"
        f"累计收益 {_fmt_pct(r.cumulative_return)}，年化收益 {_fmt_pct(r.annualized_return)}。"
        for r in _peer_rows(analysis)
    ]
    return "\n".join(lines)


def _comparison_risk_text(summaries: list[FundSummary], analysis: AnalysisResult | None) -> str:
    """风险分析（对比模式）：逐基金一行，对称呈现。"""
    names = {s.id: s.name for s in summaries}
    lines = []
    for r in _peer_rows(analysis):
        sharpe = f"{r.sharpe:.2f}" if r.sharpe is not None else "未知"
        lines.append(
            f"- {_fund_label(r.fund_id, names)}：年化波动率 {_fmt_pct(r.annual_volatility)}，"
            f"最大回撤 {_fmt_pct(r.max_drawdown)}，夏普比率 {sharpe}。"
        )
    return "\n".join(lines)


def _comparison_peer_text(analysis: AnalysisResult | None, summaries: list[FundSummary]) -> str | None:
    """核心指标对比（对比模式）：Markdown 表格 + 持仓集中度/重叠度小节。"""
    if analysis is None or analysis.peer_comparison is None:
        return None
    pc = analysis.peer_comparison
    names = {s.id: s.name for s in summaries}
    types = {s.id: s.fund_type for s in summaries}
    lines = [
        "| 基金 | 类型 | 累计收益 | 年化收益 | 年化波动 | 最大回撤 | 夏普 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in pc.rows:
        sharpe = f"{r.sharpe:.2f}" if r.sharpe is not None else "未知"
        lines.append(
            f"| {_fund_label(r.fund_id, names)} | {types.get(r.fund_id) or '类型未知'} "
            f"| {_fmt_pct(r.cumulative_return)} | {_fmt_pct(r.annualized_return)} "
            f"| {_fmt_pct(r.annual_volatility)} | {_fmt_pct(r.max_drawdown)} | {sharpe} |"
        )
    lines.append(_ALIGNMENT_NOTE)

    holding_lines = _holdings_comparison_lines(pc, names)
    if holding_lines:
        lines.append("")
        lines.extend(holding_lines)
    return "\n".join(lines)


def _holdings_comparison_lines(pc: PeerComparison, names: dict[str, str]) -> list[str]:
    """持仓对比小节：集中度与两两重叠；数据缺失的维度整行省略（不编造）。"""
    lines = []
    conc = [c for c in pc.concentration if c.top10_sum is not None]
    if conc:
        detail = "、".join(
            f"{_fund_label(c.fund_id, names)} {c.top10_sum:.2f}%（{c.holding_count} 只）"
            for c in conc
        )
        lines.append(f"- 持仓集中度（最新报告期前十大合计）：{detail}")
    for o in pc.overlaps:
        if o.overlap_ratio is None:
            continue
        common = "、".join(o.common_names) if o.common_names else "无"
        lines.append(
            f"- 持仓重叠（最新报告期，按股票名）：{_fund_label(o.fund_a, names)} 与 "
            f"{_fund_label(o.fund_b, names)} 重叠 {o.overlap_ratio:.0%}，共同持仓：{common}"
        )
    return [f"持仓对比：", *lines] if lines else []


def _comparison_manager_text(summaries: list[FundSummary]) -> str | None:
    """基金经理（对比模式）：逐基金一行。"""
    lines = [
        f"- {s.id} {s.name}：现任基金经理 {s.manager_name}。" for s in summaries if s.manager_name
    ]
    return "\n".join(lines) if lines else None


def _holdings_text(summaries: list[FundSummary], evidence: list) -> str | None:
    """持仓概览（确定性模板）：从 holdings evidence 汇总各基金最新报告期前十大。"""
    by_fund: dict[str, dict] = {}
    for e in evidence:
        value = e.get("value") if isinstance(e, dict) else getattr(e, "value", None)
        if not isinstance(value, dict) or not value.get("top_holdings"):
            continue
        fund_id = value.get("fund_id")
        if fund_id:
            by_fund[fund_id] = value
    if not by_fund:
        return None
    lines = []
    for s in summaries:
        data = by_fund.get(s.id)
        if data is None:
            continue
        period = data.get("latest_report_period")
        period_label = f"（报告期 {period}）" if period else ""
        items = "、".join(
            f"{h.get('stock_name')} {h.get('hold_ratio'):.2f}%"
            if h.get("hold_ratio") is not None
            else str(h.get("stock_name"))
            for h in data["top_holdings"]
        )
        lines.append(f"- **{s.id} {s.name}**{period_label}：{items}")
    return "\n".join(lines) if lines else None


__all__ = ["SynthesizerNode", "SynthesizerOutput", "render_markdown"]
