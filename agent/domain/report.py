"""结构化报告模型（docs/TechnicalContract.md §11）。

与合同的偏差：investment_thesis 允许为 None —— LLM 未配置/生成失败时
工作流仍需产出降级报告（Graceful Degradation，与 Collector/Analyzer 一致）。

文字部分（executive_summary / performance_analysis / risk_analysis）由
Synthesizer 用确定性模板生成（Plan.md Phase 4：「简单模板或轻量 LLM」，
V1 选模板：零成本、可单测）。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from domain.analysis import AnalysisResult
from domain.fund import FundSummary
from domain.thesis import Claim, InvestmentThesis

_MANDATORY_DISCLAIMER = "本报告由程序自动生成，不构成任何投资建议。"


class ReportMetadata(BaseModel):
    """报告元信息（§11：token / cost / tool_calls 等；estimated_cost 由 Phase 7 接入）。"""

    fund_count: int = 0
    evidence_count: int = 0
    tool_call_count: int = 0
    data_quality_issue_count: int = 0
    thesis_generated: bool = False
    analysis_engine: str = "fundforge-analysis-engine"
    evaluation_status: str | None = None    # pass | fail（未运行评估时为 None）
    repair_applied: bool = False
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Report(BaseModel):
    title: str
    generated_at: datetime
    request_id: str

    executive_summary: str
    fund_overview: list[FundSummary] = Field(default_factory=list)
    performance_analysis: str = ""
    risk_analysis: str = ""
    peer_comparison: str | None = None
    manager_analysis: str | None = None

    investment_thesis: InvestmentThesis | None = None   # 偏差：降级时为 None
    key_claims: list[Claim] = Field(default_factory=list)

    data_gaps_and_limitations: list[str] = Field(default_factory=list)
    risks_and_disclaimers: list[str] = Field(default_factory=list)

    analysis: AnalysisResult | None = None              # 结构化分析结果（供下游/展示复用）
    metadata: ReportMetadata = Field(default_factory=ReportMetadata)


def render_markdown(report: Report) -> str:
    """Report → Markdown（纯模板渲染，确定性）。"""
    lines = [f"# {report.title}", ""]
    header_meta = [
        f"生成时间：{report.generated_at:%Y-%m-%d %H:%M}（request_id: {report.request_id}）"
    ]
    evaluation_bits = []
    if report.metadata.evaluation_status:
        evaluation_bits.append(f"评估：{report.metadata.evaluation_status}")
    if report.metadata.repair_applied:
        evaluation_bits.append("已执行修复")
    if evaluation_bits:
        header_meta.append(" | ".join(evaluation_bits))
    if report.metadata.llm_calls:
        header_meta.append(
            f"Token：入 {report.metadata.input_tokens} / 出 {report.metadata.output_tokens}"
            f"（{report.metadata.llm_calls} 次 LLM 调用）"
        )
    lines += [
        *header_meta,
        "",
        "## 摘要",
        report.executive_summary,
        "",
    ]

    if report.fund_overview:
        lines += ["## 基金概览"]
        for s in report.fund_overview:
            aum = f"{s.aum:.2f}亿" if s.aum is not None else "未知"
            lines.append(
                f"- **{s.id} {s.name}**（{s.fund_type or '类型未知'}，规模 {aum}，"
                f"基金经理 {s.manager_name or '未知'}，数据质量 {s.data_quality}）"
            )
        lines.append("")

    if report.performance_analysis:
        lines += ["## 业绩分析", report.performance_analysis, ""]
    if report.risk_analysis:
        lines += ["## 风险分析", report.risk_analysis, ""]
    if report.peer_comparison:
        lines += ["## 同类对比", report.peer_comparison, ""]
    if report.manager_analysis:
        lines += ["## 基金经理", report.manager_analysis, ""]

    thesis = report.investment_thesis
    if thesis is not None:
        lines += [
            "## 投资论点",
            f"**结论**：{thesis.suitability}（证据充分度 {thesis.confidence:.2f}）",
            "",
            thesis.summary,
            "",
            "**关键结论**：",
        ]
        for c in thesis.claims:
            lines.append(f"- [{c.strength}] {c.statement}（依据: {', '.join(c.evidence_ids)}）")
        lines += _bullets("积极因素", thesis.positives)
        lines += _bullets("消极因素", thesis.negatives)
        lines += _bullets("风险", thesis.risks)
        lines += _bullets("关键假设", thesis.key_assumptions)
        lines.append("")

    if report.key_claims:
        lines += ["## 关键结论追溯"]
        for c in report.key_claims:
            lines.append(f"- [{c.claim_type}] {c.statement}（依据: {', '.join(c.evidence_ids)}）")
        lines.append("")

    if report.data_gaps_and_limitations:
        lines += ["## 数据缺口与局限"]
        lines += [f"- {g}" for g in report.data_gaps_and_limitations]
        lines.append("")

    lines += ["## 风险提示与免责声明"]
    lines += [f"- {r}" for r in report.risks_and_disclaimers]
    return "\n".join(lines)


def _bullets(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"**{title}**：", *[f"- {i}" for i in items], ""]


__all__ = ["Report", "ReportMetadata", "render_markdown"]
