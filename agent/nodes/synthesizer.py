"""Synthesizer 节点（Node 合同 §4）。

职责：把 State 中的结构化结果组装成标准 Report（§11），并渲染 Markdown。
- 文字部分用确定性模板（不调用 LLM，零成本可单测）；
- risks_and_disclaimers 强制包含合规声明；
- 关键结论可追溯：key_claims 即 Thesis 中通过证据绑定校验的 Claim；
- Thesis 缺失（LLM 降级）时仍产出完整结构的降级报告。
"""

import logging
from datetime import datetime

from domain.analysis import AnalysisResult
from domain.fund import FundSummary
from domain.plan import ResearchPlan
from domain.report import Report, ReportMetadata, render_markdown
from domain.thesis import InvestmentThesis
from state import FundForgeState

logger = logging.getLogger(__name__)

_DISCLAIMER = "本报告由程序自动生成，不构成任何投资建议。"
_DATA_ADVISORY = "历史业绩不代表未来表现，量化指标基于历史净值计算，存在模型简化假设。"
_NO_FUND_GUIDANCE = "请在提问中包含 6 位基金代码，例如：分析基金 519770"

_NO_THESIS_NOTE = "投资论点未生成（LLM 不可用或校验未通过），本报告仅包含数据与确定性分析。"


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.2f}%" if value is not None else "未知"


def synthesizer(state: FundForgeState) -> dict:
    # State 经 LangGraph 回传后可能是 dict，统一归一化为模型
    summaries = [
        s if isinstance(s, FundSummary) else FundSummary.model_validate(s)
        for s in state.get("funds_summary", [])
    ]
    evidence = state.get("evidence", [])
    tool_calls = state.get("tool_calls", [])
    issues = state.get("data_quality_issues", [])
    analysis = _normalize(state.get("analysis"), AnalysisResult)
    thesis = _normalize(state.get("investment_thesis"), InvestmentThesis)
    plan = ResearchPlan.from_state(state.get("research_plan"))
    notes = list(plan.notes) if plan else []

    primary = summaries[0] if summaries else None
    data_gaps = [*notes, *(thesis.data_gaps if thesis else [])]
    if not summaries and not notes:
        data_gaps.append(_NO_FUND_GUIDANCE)
    if thesis is None and evidence:
        data_gaps.append(_NO_THESIS_NOTE)

    report = Report(
        title=f"FundForge 基金研究报告：{primary.name}（{primary.id}）" if primary else "FundForge 基金研究报告",
        generated_at=datetime.now(),
        request_id=state.get("request_id", ""),
        executive_summary=_executive_summary(primary, summaries, analysis, thesis),
        fund_overview=summaries,
        performance_analysis=_performance_text(analysis),
        risk_analysis=_risk_text(analysis),
        peer_comparison=_peer_text(analysis),
        manager_analysis=(
            f"{primary.id} 现任基金经理：{primary.manager_name}。" if primary and primary.manager_name else None
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
        ),
    )
    logger.info(
        "synthesizer: report built (%d funds, thesis=%s)",
        len(summaries),
        thesis is not None,
    )
    return {"report": report}


def _normalize(value, model):
    """dict → Pydantic 模型；None/模型原样返回。"""
    if value is None or isinstance(value, model):
        return value
    return model.model_validate(value)


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


def _performance_text(analysis: AnalysisResult | None) -> str:
    if analysis is None:
        return ""
    perf = analysis.performance
    return (
        f"区间 {perf.period_start} ~ {perf.period_end}（{perf.nav_point_count} 个净值点），"
        f"累计收益 {_fmt_pct(perf.cumulative_return)}，年化收益 {_fmt_pct(perf.annualized_return)}。"
    )


def _risk_text(analysis: AnalysisResult | None) -> str:
    if analysis is None:
        return ""
    risk = analysis.risk
    sharpe = f"{risk.sharpe:.2f}" if risk.sharpe is not None else "未知"
    return (
        f"年化波动率 {_fmt_pct(risk.annual_volatility)}，"
        f"最大回撤 {_fmt_pct(risk.max_drawdown)}，"
        f"夏普比率 {sharpe}。"
    )


def _peer_text(analysis: AnalysisResult | None) -> str | None:
    if analysis is None or analysis.peer_comparison is None:
        return None
    pc = analysis.peer_comparison
    lines = [f"基准基金 {pc.base_fund_id}："]
    for row in pc.rows:
        sharpe = f"{row.sharpe:.2f}" if row.sharpe is not None else "未知"
        lines.append(
            f"- {row.fund_id}: 年化收益 {_fmt_pct(row.annualized_return)}，"
            f"年化波动 {_fmt_pct(row.annual_volatility)}，"
            f"最大回撤 {_fmt_pct(row.max_drawdown)}，夏普 {sharpe}"
        )
    lines.append("注：各基金指标基于其自身全部历史净值计算，区间起点不同，横向对比仅供参考（后续版本将做区间对齐）。")
    return "\n".join(lines)


__all__ = ["synthesizer", "render_markdown"]
