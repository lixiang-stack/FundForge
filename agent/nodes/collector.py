"""Collector 节点（Node 合同 §4）。

职责：通过 Fund Tools 获取结构化基金数据。
- 完整数据写入外部 Store（由 Tools 内部完成），State 只保留摘要与 ID；
- 产出 funds_summary + evidence + tool_calls + data_quality_issues；
- evidence 只允许追加。

结构：`_collect_fund` 返回结构化 `FundCollectionResult`（无副作用），
由 `CollectorNode.__call__` 统一合并进 State。
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.evidence import Evidence, ToolCallRecord
from domain.fund import Fund, FundPerformance, FundSummary, summarize_fund
from domain.plan import ResearchPlan
from langchain_core.tools import BaseTool
from state import FundForgeState
from store import FundStore
from tools.fund_tools import FundTools

logger = logging.getLogger(__name__)


@dataclass
class FundCollectionResult:
    """单只基金的采集结果（函数式产出，由 __call__ 统一合并）。"""

    fund_id: str
    summary: FundSummary | None = None
    evidence: list[Evidence] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def record_tool_call(tool: BaseTool, arguments: dict[str, Any]) -> tuple[Any, ToolCallRecord]:
    """执行一次 Tool 调用并记录 ToolCallRecord（§12 可观测性合同）。

    Tool 失败必须落记录并降级返回，不允许中断工作流。
    """
    started_at = datetime.now()
    try:
        result = tool.invoke(arguments)
    except Exception as e:  # noqa: BLE001
        logger.error("tool %s failed: %s", tool.name, e)
        return None, ToolCallRecord(
            tool_name=tool.name,
            arguments=arguments,
            started_at=started_at,
            finished_at=datetime.now(),
            success=False,
            error=str(e),
        )
    return result, ToolCallRecord(
        tool_name=tool.name,
        arguments=arguments,
        started_at=started_at,
        finished_at=datetime.now(),
        success=True,
    )


def fund_evidence(fund: Fund) -> Evidence:
    """基金基本信息 → fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type="fund_data",
        source=fund.source,
        source_detail=f"基金基本信息：{fund.name or fund.id}",
        as_of=fund.as_of,
        value={
            "fund_id": fund.id,
            "name": fund.name or None,
            "fund_type": fund.fund_type,
            "aum_yi": fund.aum,
            "manager_name": fund.manager_name,
            "inception_date": str(fund.inception_date) if fund.inception_date else None,
        },
        data_quality=fund.data_quality,
        raw_ref=FundStore.fund_ref(fund.id),
    )


def performance_evidence(perf: FundPerformance) -> Evidence:
    """净值序列摘要 → fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type="fund_data",
        source=perf.source,
        source_detail=f"净值序列：{perf.nav_point_count} 个数据点",
        as_of=perf.as_of,
        value={
            "fund_id": perf.fund_id,
            "period_start": str(perf.period_start) if perf.period_start else None,
            "period_end": str(perf.period_end) if perf.period_end else None,
            "nav_point_count": perf.nav_point_count,
        },
        data_quality=perf.data_quality,
        raw_ref=FundStore.nav_ref(perf.fund_id),
    )


class CollectorNode:
    """Collector 节点：调用 Fund Tools 采集数据，统一合并进 State。"""

    def __init__(self, tools: FundTools) -> None:
        self._tools = tools

    def __call__(self, state: FundForgeState) -> dict:
        plan = ResearchPlan.from_state(state.get("research_plan"))
        fund_ids = list(plan.fund_ids) if plan else []
        if not fund_ids:
            logger.warning("collector: research_plan 为空，跳过采集")
            return {
                "fund_ids": [],
                "funds_summary": [],
                "evidence": list(state.get("evidence", [])),
                "tool_calls": list(state.get("tool_calls", [])),
                "data_quality_issues": [
                    *state.get("data_quality_issues", []),
                    "research_plan 中没有基金代码，未执行数据采集",
                ],
            }

        results = [self._collect_fund(code) for code in fund_ids]
        collected = {
            "fund_ids": fund_ids,
            "funds_summary": [r.summary for r in results if r.summary is not None],
            "evidence": [e for r in results for e in r.evidence],
            "tool_calls": [t for r in results for t in r.tool_calls],
            "data_quality_issues": [i for r in results for i in r.issues],
        }
        # evidence 只允许追加：在既有记录基础上累加
        collected["evidence"] = [*state.get("evidence", []), *collected["evidence"]]
        collected["tool_calls"] = [*state.get("tool_calls", []), *collected["tool_calls"]]
        collected["data_quality_issues"] = [
            *state.get("data_quality_issues", []),
            *collected["data_quality_issues"],
        ]

        logger.info(
            "collector: %d funds collected, %d evidence, %d tool calls",
            len(collected["funds_summary"]),
            len(collected["evidence"]),
            len(collected["tool_calls"]),
        )
        return collected

    def _collect_fund(self, code: str) -> FundCollectionResult:
        """采集单只基金：info + performance，失败降级并记录问题。"""
        result = FundCollectionResult(fund_id=code)

        fund, info_record = record_tool_call(
            self._tools.get_fund_info, {"fund_id": code}
        )
        result.tool_calls.append(info_record)

        perf, perf_record = record_tool_call(
            self._tools.get_fund_performance, {"fund_id": code}
        )
        result.tool_calls.append(perf_record)

        if not info_record.success and not perf_record.success:
            result.issues.append(f"{code}: 基金数据获取完全失败")
            return result

        fund = fund if info_record.success else None
        perf = perf if perf_record.success else None

        if not info_record.success:
            result.issues.append(f"{code}: 基金基本信息缺失（get_fund_info 失败）")
        if not perf_record.success:
            result.issues.append(f"{code}: 基金净值序列缺失（get_fund_performance 失败）")
        elif perf is not None and perf.data_quality == "missing":
            result.issues.append(f"{code}: 净值序列为空，data_quality=missing")

        if fund is not None:
            result.summary = summarize_fund(fund)
            result.evidence.append(fund_evidence(fund))
        if perf is not None:
            result.evidence.append(performance_evidence(perf))
        return result


__all__ = ["CollectorNode", "FundCollectionResult"]
