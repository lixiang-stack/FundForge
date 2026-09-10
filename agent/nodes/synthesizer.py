"""Synthesizer 节点（Node 合同 §4）。

职责：组装最终报告。必须包含风险提示与「不构成投资建议」声明。
Phase 1：固定模板 + 已采集基金摘要列表；结构化 Report 在 Phase 4 定义。
"""

import logging

from domain.plan import ResearchPlan
from state import FundForgeState

logger = logging.getLogger(__name__)

_DISCLAIMER = "免责声明：本报告不构成任何投资建议。"

_NO_FUND_GUIDANCE = "请在提问中包含 6 位基金代码，例如：分析基金 519770"


def synthesizer(state: FundForgeState) -> dict:
    summaries = state.get("funds_summary", [])
    evidence = state.get("evidence", [])
    issues = state.get("data_quality_issues", [])
    plan = ResearchPlan.from_state(state.get("research_plan"))
    notes = list(plan.notes) if plan else []

    lines = [
        "FundForge 研究报告（Phase 1 骨架输出）",
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
    if issues:
        lines.append("数据质量提示：")
        lines.extend(f"- {i}" for i in issues)
    lines += [
        "",
        "尚未接入量化分析、LLM 推理与评估环节。",
        _DISCLAIMER,
    ]

    logger.info("synthesizer: report generated (%d funds)", len(summaries))
    return {"report": "\n".join(lines)}
