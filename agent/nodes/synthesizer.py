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
# 单基金研究的同类对比小节沿用对齐口径注；对比报告改由核心指标对比表上方的对齐区间说明承载
_ALIGNMENT_NOTE = "注：各基金指标已对齐至共同区间（最短历史为准，最长 10 年）计算，口径一致。"

_NO_THESIS_NOTE = "投资论点未生成（LLM 不可用或校验未通过），本报告仅包含数据与确定性分析。"
_INSUFFICIENT_EVIDENCE_NOTE = (
    "证据不足：评估未通过（经 1 次修复后仍存在问题），上述结论的可靠性受限，请谨慎参考。"
)

# 区间收益标签（与 engine.TRAILING_WINDOWS 的键一致）
_TRAILING_LABELS: tuple[tuple[str, str], ...] = (
    ("1m", "近1月"),
    ("3m", "近3月"),
    ("6m", "近6月"),
    ("1y", "近1年"),
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
            holdings_analysis=_holdings_text(summaries, evidence, analysis),
            cost_and_rating=_fund_facts_text(summaries, evidence),
            # 对比报告：收益/风险/经理指标统一由「核心指标对比」表承载，不设重复章节
            performance_analysis="" if is_comparison else _performance_text(primary, analysis),
            risk_analysis="" if is_comparison else _risk_text(primary, analysis),
            peer_comparison=(
                _comparison_peer_text(analysis, summaries)
                if is_comparison
                else _peer_text(analysis, summaries)
            ),
            comparison_differences=(
                _comparison_differences_text(summaries, analysis) if is_comparison else None
            ),
            manager_analysis=(
                None
                if is_comparison
                else (
                    f"{primary.id} 现任基金经理：{primary.manager_name}。"
                    if primary and primary.manager_name
                    else None
                )
            ),
            recommendation=(
                _comparison_recommendation_text(summaries, analysis) if is_comparison else None
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


def _fmt_ratio(value: float | None) -> str:
    """比率 → 2 位小数字符串（夏普 / Sortino）；None → 未知。"""
    return f"{value:.2f}" if value is not None else "未知"


def _executive_summary(
    primary: FundSummary | None,
    summaries: list[FundSummary],
    analysis: AnalysisResult | None,
    thesis: InvestmentThesis | None,
) -> str:
    if not summaries:
        return "未能采集到基金数据，无法形成研究结论。"
    parts = [
        f"本次研究覆盖 {len(summaries)} 只基金，主体为 {primary.id} {primary.name}"
        f"（{primary.fund_type or '类型未知'}）。"
    ]
    if analysis is not None:
        perf = analysis.performance
        parts.append(
            f"确定性量化分析：{perf.period_start} ~ {perf.period_end}"
            f"（{perf.nav_point_count} 个净值点）累计收益 {_fmt_pct(perf.cumulative_return)}，"
            f"年化收益 {_fmt_pct(perf.annualized_return)}。"
        )
    if thesis is not None:
        parts.append(f"投资论点：{thesis.suitability}")
    return "\n\n".join(parts)


def _fund_label(fund_id: str, names: dict[str, str]) -> str:
    """「代码 名称」标签；名称缺失时退回纯代码。"""
    name = names.get(fund_id)
    return f"{fund_id} {name}" if name else fund_id


def _evidence_value_map(evidence: list, key: str) -> dict[str, dict]:
    """按 value 顶层键筛选证据，返回 fund_id → value 映射（同基金取最后一条）。"""
    by_fund: dict[str, dict] = {}
    for e in evidence:
        value = e.get("value") if isinstance(e, dict) else getattr(e, "value", None)
        if isinstance(value, dict) and value.get("fund_id") and key in value:
            by_fund[value["fund_id"]] = value
    return by_fund


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """统一 Markdown 表格拼装：分隔行列数与表头强一致（防列数错配导致渲染错乱）。"""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _performance_text(primary: FundSummary | None, analysis: AnalysisResult | None) -> str:
    """业绩分析（research）：指标矩阵 + 分年度收益表；数据缺失的行省略（不编造）。"""
    if analysis is None:
        return ""
    perf = analysis.performance
    trailing = perf.trailing_returns or {}
    rows: list[list[str]] = []
    if perf.period_start and perf.period_end:
        rows.append(["区间（净值点数）", f"{perf.period_start} ~ {perf.period_end}（{perf.nav_point_count} 点）"])
    if perf.cumulative_return is not None:
        rows.append(["累计收益", _fmt_pct(perf.cumulative_return)])
    if perf.annualized_return is not None:
        rows.append(["年化收益", _fmt_pct(perf.annualized_return)])
    rows += [
        [label, _fmt_pct(trailing[key])]
        for key, label in _TRAILING_LABELS
        if trailing.get(key) is not None
    ]
    if perf.excess_return is not None:
        benchmark = f"（{perf.benchmark_code}）" if perf.benchmark_code else ""
        rows.append([f"相对基准超额{benchmark}", _fmt_pct(perf.excess_return)])
        if perf.tracking_error is not None:
            rows.append(["近似跟踪误差", _fmt_pct(perf.tracking_error)])
    rolling = perf.rolling_1y
    if rolling is not None and rolling.min is not None:
        rows.append(
            [
                f"滚动{rolling.window_days}日（约1年）收益（最低/中位/最高）",
                f"{_fmt_pct(rolling.min)} / {_fmt_pct(rolling.median)} / {_fmt_pct(rolling.max)}",
            ]
        )
    if not rows:
        return ""

    subject = f"{primary.id} {primary.name}（主体基金）" if primary else ""
    lines = ([subject, ""] if subject else []) + _md_table(["指标", "数值"], rows)
    yearly = sorted((perf.yearly_returns or {}).items())
    yearly_rows = [[f"{y}年", _fmt_pct(r)] for y, r in yearly if r is not None]
    if yearly_rows:
        lines += ["", "分年度收益：", "", *_md_table(["年份", "收益"], yearly_rows)]
    return "\n".join(lines)


def _risk_text(primary: FundSummary | None, analysis: AnalysisResult | None) -> str:
    """风险分析（research）：指标矩阵；数据缺失的行省略（不编造）。"""
    if analysis is None:
        return ""
    risk = analysis.risk
    rows: list[list[str]] = []
    if risk.annual_volatility is not None:
        rows.append(["年化波动率", _fmt_pct(risk.annual_volatility)])
    if risk.max_drawdown is not None:
        rows.append(["最大回撤", _fmt_pct(risk.max_drawdown)])
    if risk.max_drawdown not in (None, 0.0):
        if risk.max_drawdown_recovery_days is not None:
            rows.append(["最大回撤修复", f"{risk.max_drawdown_recovery_days} 个自然日"])
        else:
            rows.append(["最大回撤修复", "截至期末尚未修复"])
    if risk.sharpe is not None:
        rows.append(["夏普比率", _fmt_ratio(risk.sharpe)])
    if risk.sortino is not None:
        rows.append(["Sortino", _fmt_ratio(risk.sortino)])
    if not rows:
        return ""
    subject = f"{primary.id} {primary.name}（主体基金）" if primary else ""
    lines = ([subject, ""] if subject else []) + _md_table(["指标", "数值"], rows)
    return "\n".join(lines)


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
    """对比摘要：逐维度分段（对比对象 / 对齐区间 / 确定性量化 / 投资论点）。"""
    if not summaries:
        return "未能采集到基金数据，无法形成对比结论。"
    labels = "、".join(f"{s.id} {s.name}" for s in summaries)
    parts = [f"本报告对比 {len(summaries)} 只基金：{labels}。"]
    rows = analysis.peer_comparison.rows if analysis and analysis.peer_comparison else []
    if rows:
        window = next((r for r in rows if r.period_start and r.period_end), None)
        if window:
            parts.append(f"对齐区间 {window.period_start} ~ {window.period_end}。")
        parts.append(
            "确定性量化分析："
            + "、".join(f"{r.fund_id} 年化 {_fmt_pct(r.annualized_return)}" for r in rows)
            + "。"
        )
    if thesis is not None:
        parts.append(f"投资论点：{thesis.suitability}")
    return "\n\n".join(parts)


def _peer_rows(analysis: AnalysisResult | None) -> list:
    """对比任务的逐基金指标行（peer_comparison 缺失时为空，章节整节省略）。"""
    return analysis.peer_comparison.rows if analysis and analysis.peer_comparison else []


def _comparison_peer_text(analysis: AnalysisResult | None, summaries: list[FundSummary]) -> str | None:
    """核心指标对比（对比模式）：单一总览表 + 持仓重叠要点行（集中度已在持仓概览逐基金披露）。

    收益 / 风险 / 风险调整 / 超额合并为一张表，避免与独立「业绩分析 / 风险分析」重复。
    """
    if analysis is None or analysis.peer_comparison is None:
        return None
    pc = analysis.peer_comparison
    names = {s.id: s.name for s in summaries}
    lines = []
    window = next((r for r in pc.rows if r.period_start and r.period_end), None)
    if window:
        lines += [f"对齐区间 {window.period_start} ~ {window.period_end}（全部基金同口径）。", ""]
    lines += [
        "| 基金 | 累计收益 | 年化收益 | 年化波动 | 最大回撤 | 夏普 | Sortino | 相对基准超额 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in pc.rows:
        lines.append(
            f"| {_fund_label(r.fund_id, names)} | {_fmt_pct(r.cumulative_return)} "
            f"| {_fmt_pct(r.annualized_return)} | {_fmt_pct(r.annual_volatility)} "
            f"| {_fmt_pct(r.max_drawdown)} | {_fmt_ratio(r.sharpe)} | {_fmt_ratio(r.sortino)} "
            f"| {_excess_cell(r)} |"
        )
    trailing_lines = _trailing_returns_table(pc, names)
    if trailing_lines:
        lines += ["", *trailing_lines]
    overlap_lines = _holdings_overlap_lines(pc, names)
    if overlap_lines:
        lines += ["", *overlap_lines]
    return "\n".join(lines)


def _trailing_returns_table(pc: PeerComparison, names: dict[str, str]) -> list[str]:
    """区间收益表（近1月/近3月/近6月/近1年，按 21/63/126/252 个交易日近似）。

    全部基金所有窗口均缺失时整节省略（不编造）。
    """
    if not any(
        any((r.trailing_returns or {}).get(key) is not None for key, _ in _TRAILING_LABELS)
        for r in pc.rows
    ):
        return []
    lines = [
        "区间收益（按净值计算；近1月≈21 个交易日、近3月≈63、近6月≈126、近1年≈252）：",
        "",
        "| 基金 | " + " | ".join(label for _, label in _TRAILING_LABELS) + " |",
        "| " + " | ".join(["---"] * (len(_TRAILING_LABELS) + 1)) + " |",
    ]
    for r in pc.rows:
        trailing = r.trailing_returns or {}
        cells = " | ".join(
            _fmt_pct(trailing[key]) if trailing.get(key) is not None else "—"
            for key, _ in _TRAILING_LABELS
        )
        lines.append(f"| {_fund_label(r.fund_id, names)} | {cells} |")
    return lines


def _excess_cell(row) -> str:
    """相对基准超额单元格：超额缺失填「—」，有基准代码时随附。"""
    if row.excess_return is None:
        return "—"
    benchmark = f"（{row.benchmark_code}）" if row.benchmark_code else ""
    return f"{_fmt_pct(row.excess_return)}{benchmark}"


def _holdings_overlap_lines(pc: PeerComparison, names: dict[str, str]) -> list[str]:
    """持仓重叠：两两一句话呈现（共同持仓为长列表，不适合塞进表格单元格）。"""
    lines = []
    for o in pc.overlaps:
        if o.overlap_ratio is None:
            continue
        common = "、".join(o.common_names) if o.common_names else "无"
        lines.append(
            f"- 持仓重叠（最新报告期，按股票名）：{_fund_label(o.fund_a, names)} 与 "
            f"{_fund_label(o.fund_b, names)} 重叠 {o.overlap_ratio:.0%}，共同持仓：{common}"
        )
    return lines


# (维度标签, PeerMetricsRow 字段, 数值越大越优, 是否百分比口径)
_DIFF_DIMENSIONS: list[tuple[str, str, bool, bool]] = [
    ("年化收益", "annualized_return", True, True),
    ("年化波动", "annual_volatility", False, True),
    ("最大回撤", "max_drawdown", True, True),   # 回撤为负值，越接近 0（越大）越浅
    ("夏普比率", "sharpe", True, False),
]


def _comparison_differences_text(
    summaries: list[FundSummary], analysis: AnalysisResult | None
) -> str | None:
    """差异总结（对比模式）：Markdown 表格，逐维度并列各基金取值并标注更优者与差距。

    列 = 各基金（代码作列头，全称见基金概览），行 = 维度；仅保留有 ≥2 个非 None 值
    且取值不同的维度；无任何可比维度整节省略，可比但取值全部相同时退化为
    「指标相当」结论句（不虚构差异）。
    """
    rows = [r for r in _peer_rows(analysis)]
    if len(rows) < 2:
        return None
    fund_ids = [r.fund_id for r in rows]
    # 列 = 维度 + 各基金 + 表现更优 + 差距
    sep = "| " + " | ".join(["---"] * (len(fund_ids) + 3)) + " |"
    table_rows = []
    comparable = False
    for label, field, higher_is_better, is_pct in _DIFF_DIMENSIONS:
        items = [(r.fund_id, getattr(r, field)) for r in rows if getattr(r, field) is not None]
        if len(items) < 2:
            continue
        comparable = True
        pick_best = max if higher_is_better else min
        pick_worst = min if higher_is_better else max
        best = pick_best(items, key=lambda t: t[1])
        worst = pick_worst(items, key=lambda t: t[1])
        if best[1] == worst[1]:
            continue
        fmt = _fmt_pct if is_pct else _fmt_ratio
        value_map = dict(items)
        value_cells = " | ".join(
            fmt(value_map[fid]) if fid in value_map else "—" for fid in fund_ids
        )
        gap = abs(best[1] - worst[1])
        gap_text = f"{gap * 100:.2f} 个百分点" if is_pct else f"{gap:.2f}"
        table_rows.append(f"| {label} | {value_cells} | {best[0]} | {gap_text} |")
    if not comparable:
        return None
    if not table_rows:
        return "各基金在同口径对齐区间指标上基本相当，未呈现方向性差异（数值见核心指标对比表）。"
    header = "| 维度 | " + " | ".join(fund_ids) + " | 表现更优 | 差距 |"
    return "\n".join(
        [
            "以下按同口径对齐区间指标列出各基金差异（基金全称见基金概览）。",
            "",
            header,
            sep,
            *table_rows,
        ]
    )


def _comparison_recommendation_text(
    summaries: list[FundSummary],
    analysis: AnalysisResult | None,
) -> str | None:
    """明确推荐倾向（对比模式）：基于同口径指标的确定性取舍结论。

    thesis.suitability 已在「对比结论」章节呈现，此处不重复引用。
    """
    rows = [r for r in _peer_rows(analysis)]
    if len(rows) < 2:
        return None
    names = {s.id: s.name for s in summaries}

    def _leader(field: str):
        """该维度最高值者；仅 1 个有效值或并列最高（无明确领先）时返回 None。"""
        values = sorted(
            ((r.fund_id, getattr(r, field)) for r in rows if getattr(r, field) is not None),
            key=lambda t: t[1],
            reverse=True,
        )
        if len(values) < 2 or values[0][1] == values[1][1]:
            return None
        return values[0]

    ret = _leader("annualized_return")
    sharpe = _leader("sharpe")
    if ret is not None and sharpe is not None and ret[0] == sharpe[0]:
        verdict = (
            f"综合收益与风险调整后表现，{_fund_label(ret[0], names)} 在同口径区间内同时领先"
            f"（年化收益 {_fmt_pct(ret[1])}、夏普 {sharpe[1]:.2f}）；"
            f"确定性倾向：长期持有场景下 {_fund_label(ret[0], names)} 相对更契合。"
        )
    elif ret is not None and sharpe is not None:
        verdict = (
            f"收益与风险调整后表现由不同基金领先：年化收益 {_fund_label(ret[0], names)} 最高"
            f"（{_fmt_pct(ret[1])}），夏普比率 {_fund_label(sharpe[0], names)} 最高"
            f"（{sharpe[1]:.2f}）；确定性倾向：追求收益弹性更契合 {_fund_label(ret[0], names)}，"
            f"控制回撤与波动更契合 {_fund_label(sharpe[0], names)}。"
        )
    else:
        leader = ret if ret is not None else sharpe
        if leader is None:
            fund_list = "、".join(_fund_label(r.fund_id, names) for r in rows)
            verdict = (
                f"各基金（{fund_list}）同口径收益与风险调整后指标接近（或无明确领先者），"
                "确定性倾向不显著；建议结合核心指标对比表按自身风险偏好取舍。"
            )
        else:
            metric = "年化收益" if ret is not None else "夏普比率"
            value = _fmt_pct(leader[1]) if ret is not None else f"{leader[1]:.2f}"
            verdict = (
                f"在可比的同口径指标中，{_fund_label(leader[0], names)} 的{metric}领先（{value}）；"
                f"确定性倾向：长期持有场景下 {_fund_label(leader[0], names)} 相对更契合。"
            )

    return "\n\n".join(
        [verdict, "以上倾向基于同口径历史量化指标与证据，属确定性输出，不构成投资建议。"]
    )


def _holdings_text(
    summaries: list[FundSummary],
    evidence: list,
    analysis: AnalysisResult | None = None,
) -> str | None:
    """持仓概览（确定性模板）。

    多基金：前十大按排名对齐成表 + 持仓结构矩阵（逐维度对照）；
    单基金：保持要点列表（单列表格无对照意义）。
    """
    by_fund: dict[str, dict] = {}
    for e in evidence:
        value = e.get("value") if isinstance(e, dict) else getattr(e, "value", None)
        if not isinstance(value, dict) or not value.get("top_holdings"):
            continue
        fund_id = value.get("fund_id")
        if fund_id:
            by_fund[fund_id] = value
    metrics = {m.fund_id: m for m in (analysis.holdings_metrics if analysis else [])}
    industry_map = _evidence_value_map(evidence, "top_industries")
    allocation_map = _evidence_value_map(evidence, "allocation")
    if not by_fund and not metrics and not industry_map and not allocation_map:
        return None
    if len(summaries) > 1:
        return _holdings_tables(summaries, by_fund, metrics, industry_map, allocation_map)
    if not summaries:
        return None
    s = summaries[0]
    return _holdings_single(
        by_fund.get(s.id), metrics.get(s.id), industry_map.get(s.id), allocation_map.get(s.id)
    )


def _holdings_single(by_fund: dict | None, metrics, industry: dict | None, allocation: dict | None) -> str | None:
    """单基金持仓概览：前十大明细表（排名/股票/占净值比）+ 持仓结构表（维度/数值）。"""
    if by_fund is None and metrics is None and industry is None and allocation is None:
        return None
    lines = []
    holdings = (by_fund or {}).get("top_holdings") or []
    if holdings:
        rows = []
        for i, h in enumerate(holdings):
            name = h.get("stock_name")
            ratio = h.get("hold_ratio")
            rows.append(
                [
                    str(i + 1),
                    str(name) if name is not None else "—",
                    f"{ratio:.2f}%" if ratio is not None else "—",
                ]
            )
        lines += _md_table(["排名", "股票", "占净值比"], rows)

    struct_rows: list[list[str]] = []
    period = (by_fund or {}).get("latest_report_period")
    if period:
        struct_rows.append(["报告期", period])
    if metrics is not None and metrics.top10_sum is not None:
        struct_rows.append(["前十大合计", f"{metrics.top10_sum:.2f}%（{metrics.holding_count} 只）"])
    if metrics is not None:
        split_bits = _market_split_bits(metrics.market_split)
        if split_bits:
            struct_rows.append(["市场分布（占披露持仓净值比）", split_bits])
    if industry and industry.get("top_industries"):
        bits = "、".join(
            f"{t.get('industry')} {t.get('nav_ratio'):.2f}%"
            for t in industry["top_industries"]
            if t.get("industry") and t.get("nav_ratio") is not None
        )
        if bits:
            struct_rows.append([f"行业前五（{industry.get('latest_report_date') or '最新报告期'}）", bits])
    if allocation and allocation.get("allocation"):
        bits = "、".join(
            f"{a.get('asset_type')} {a.get('percent'):.2f}%"
            for a in allocation["allocation"]
            if a.get("asset_type") and a.get("percent") is not None
        )
        if bits:
            struct_rows.append(["资产配置", bits])
    if struct_rows:
        lines += ["", *_md_table(["持仓结构", "数值"], struct_rows)]
    return "\n".join(lines) if lines else None


def _holdings_tables(
    summaries: list[FundSummary],
    by_fund: dict[str, dict],
    metrics: dict,
    industry_map: dict,
    allocation_map: dict,
) -> str | None:
    """多基金持仓概览：前十大排名对齐表 + 持仓结构矩阵（列 = 基金代码，全称见基金概览）。"""
    fund_ids = [s.id for s in summaries]
    lines = []

    holding_lists = [(by_fund.get(fid) or {}).get("top_holdings") or [] for fid in fund_ids]
    if any(holding_lists):
        depth = max(len(h) for h in holding_lists)
        rows = [
            [str(i + 1), *(_holding_cell(h[i]) if i < len(h) else "—" for h in holding_lists)]
            for i in range(depth)
        ]
        lines += _md_table(["排名", *fund_ids], rows)

    struct_rows: list[tuple[str, list[str]]] = []

    def _row_if_any(label: str, cells: list[str]) -> None:
        if any(c != "—" for c in cells):
            struct_rows.append((label, cells))

    periods = [(by_fund.get(fid) or {}).get("latest_report_period") for fid in fund_ids]
    if any(periods):
        _row_if_any("报告期", [p or "—" for p in periods])

    conc = []
    for fid in fund_ids:
        m = metrics.get(fid)
        conc.append(f"{m.top10_sum:.2f}%（{m.holding_count} 只）" if m and m.top10_sum is not None else "—")
    _row_if_any("前十大合计", conc)

    splits = []
    for fid in fund_ids:
        m = metrics.get(fid)
        splits.append(_market_split_bits(m.market_split) if m else "")
    _row_if_any("市场分布（占披露持仓净值比）", [c or "—" for c in splits])

    industries = [industry_map.get(fid) for fid in fund_ids]
    industry_cells = []
    industry_dates = []
    for ind in industries:
        bits = ""
        if ind and ind.get("top_industries"):
            bits = "、".join(
                f"{t.get('industry')} {t.get('nav_ratio'):.2f}%"
                for t in ind["top_industries"]
                if t.get("industry") and t.get("nav_ratio") is not None
            )
        industry_cells.append(bits)
        industry_dates.append(ind.get("latest_report_date") if ind else None)
    if any(industry_cells):
        common_dates = {d for d in industry_dates if d}
        if len(common_dates) == 1:
            label = f"行业前五（{common_dates.pop()}）"
            cells = [c or "—" for c in industry_cells]
        else:
            label = "行业前五"
            cells = [f"（{d}）{c}" if c and d else (c or "—") for c, d in zip(industry_cells, industry_dates)]
        struct_rows.append((label, cells))

    allocations = [allocation_map.get(fid) for fid in fund_ids]
    allocation_cells = []
    for allocation in allocations:
        bits = ""
        if allocation and allocation.get("allocation"):
            bits = "、".join(
                f"{a.get('asset_type')} {a.get('percent'):.2f}%"
                for a in allocation["allocation"]
                if a.get("asset_type") and a.get("percent") is not None
            )
        allocation_cells.append(bits)
    _row_if_any("资产配置", [c or "—" for c in allocation_cells])

    if struct_rows:
        lines += ["", *_md_table(["持仓结构", *fund_ids], [[label, *cells] for label, cells in struct_rows])]
    return "\n".join(lines) if lines else None


def _holding_cell(holding: dict) -> str:
    """单个持仓 → 表格单元格；占比缺失仅列名称。"""
    name = holding.get("stock_name")
    ratio = holding.get("hold_ratio")
    if name is None:
        return "—"
    return f"{name} {ratio:.2f}%" if ratio is not None else str(name)


def _market_split_bits(split) -> str:
    """MarketSplit → 「A股 xx%、港股 xx%…」片段；全空返回空串。"""
    if split is None:
        return ""
    labels = [
        ("a_share_ratio", "A股"),
        ("hk_share_ratio", "港股"),
        ("overseas_ratio", "美股(海外)"),
        ("other_ratio", "其他"),
    ]
    bits = [
        # market_split 各字段已是百分数（"acc"口径注释见 engine.market_split），
        # 不能走 _fmt_pct（其语义为小数×100），否则渲染成 5989.00% 这类双重百分比
        f"{label} {getattr(split, key):.2f}%"
        for key, label in labels
        if getattr(split, key) is not None
    ]
    return "、".join(bits)


# 第三方评级机构（键 → 展示名）
_RATING_LABELS: tuple[tuple[str, str], ...] = (
    ("rating_sh", "上海证券"),
    ("rating_zs", "招商证券"),
    ("rating_ja", "济安金信"),
    ("rating_mx", "晨星"),
)


def _fee_rating_cells(fees: dict, rating: dict) -> list[str]:
    """单只基金的费率/评级单元格（缺失维度填 —）。"""
    count = rating.get("five_star_count")
    return [
        f"{fees['management_fee_rate']:.2f}%" if fees.get("management_fee_rate") is not None else "—",
        f"{fees['custodian_fee_rate']:.2f}%" if fees.get("custodian_fee_rate") is not None else "—",
        f"{fees['service_fee_rate']:.2f}%" if fees.get("service_fee_rate") is not None else "—",
        f"{count:.0f}" if count is not None else "—",
        *(
            f"{rating[key]:.0f}星" if rating.get(key) is not None else "—"
            for key, _ in _RATING_LABELS
        ),
    ]


def _rank_bits(rank: str | None) -> str | None:
    """\"308/1070\" → \"前 28.8%\"（池内分位，越小越好）；无法解析返回 None。"""
    if not rank or "/" not in rank:
        return None
    try:
        num, denom = (int(x) for x in rank.split("/", 1))
    except ValueError:
        return None
    if denom <= 0 or num < 0:
        return None
    return f"前 {num / denom * 100:.1f}%"


def _rank_periods(
    summaries: list[FundSummary], ach_map: dict, max_periods: int = 4
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """同类排名索引：(周期顺序（按首个基金出现序，最多 max_periods）, fund_id → 周期 → 单元格)。"""
    per_fund: dict[str, dict[str, str]] = {}
    period_order: list[str] = []
    for s in summaries:
        rows = (ach_map.get(s.id) or {}).get("achievement") or []
        mapping: dict[str, str] = {}
        for r in rows:
            rank = r.get("category_rank")
            if not rank:
                continue
            period = r.get("period") or "未知周期"
            if period not in mapping:
                pct = _rank_bits(rank)
                mapping[period] = f"{pct}（{rank}）" if pct else f"（{rank}）"
                if period not in period_order:
                    period_order.append(period)
        per_fund[s.id] = mapping
    return period_order[:max_periods], per_fund


def _fund_facts_text(summaries: list[FundSummary], evidence: list) -> str | None:
    """每基金事实小节（费率 / 评级 / 同类排名），任一维度有数据才成节。

    多基金：费率与评级成表（行 = 基金）+ 同类排名按周期对照矩阵；
    单基金：项目/数值两列表 + 周期/排名两列表。
    """
    fees_map = _evidence_value_map(evidence, "management_fee_rate")
    rating_map = _evidence_value_map(evidence, "five_star_count")
    ach_map = _evidence_value_map(evidence, "achievement")
    if not (fees_map or rating_map or ach_map):
        return None
    periods, per_fund = _rank_periods(summaries, ach_map)

    if len(summaries) > 1:
        fund_ids = [s.id for s in summaries]
        fact_rows = [
            _fee_rating_cells(fees_map.get(fid) or {}, rating_map.get(fid) or {}) for fid in fund_ids
        ]
        lines = []
        if any(any(c != "—" for c in row) for row in fact_rows):
            headers = ["基金", "管理费/年", "托管费/年", "销售服务费/年", "五星数", *(
                label for _, label in _RATING_LABELS
            )]
            lines += _md_table(headers, [[fid, *row] for fid, row in zip(fund_ids, fact_rows)])
        if periods:
            lines += [
                "",
                "同类排名（池内分位；跨类型基金之间不可直接比较）：",
                "",
                *_md_table(
                    ["周期", *fund_ids],
                    [[p, *(per_fund[f].get(p, "—") for f in fund_ids)] for p in periods],
                ),
            ]
        return "\n".join(lines) if lines else None

    if not summaries:
        return None
    s = summaries[0]
    fees = fees_map.get(s.id) or {}
    rating = rating_map.get(s.id) or {}
    rows: list[list[str]] = []
    for label, key in (
        ("管理费/年", "management_fee_rate"),
        ("托管费/年", "custodian_fee_rate"),
        ("销售服务费/年", "service_fee_rate"),
    ):
        if fees.get(key) is not None:
            rows.append([label, f"{fees[key]:.2f}%"])
    if rating.get("five_star_count") is not None:
        rows.append(["五星数", f"{rating['five_star_count']:.0f}"])
    rows += [
        [label, f"{rating[key]:.0f}星"]
        for key, label in _RATING_LABELS
        if rating.get(key) is not None
    ]
    lines = _md_table(["项目", "数值"], rows) if rows else []
    if periods:
        lines += [
            "",
            "同类排名（池内分位；跨类型基金之间不可直接比较）：",
            "",
            *_md_table(["周期", "同类排名"], [[p, per_fund[s.id].get(p, "—")] for p in periods]),
        ]
    return "\n".join(lines) if lines else None


__all__ = ["SynthesizerNode", "SynthesizerOutput", "render_markdown"]
