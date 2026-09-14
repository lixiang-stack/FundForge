"""Researcher 节点（Node 合同 §4）。

职责：获取结构化数据之外的外部研究信息（web_search / fetch_document）。
V1 为契约占位：默认无 ResearchProvider（确定性降级，记录 note），
真实研究源在 Phase 7+ 按 Evaluation ROI 接入；节点本身可注入 mock。
"""

import logging
import uuid
from datetime import datetime
from typing import TypedDict

from domain.evidence import Evidence, EvidenceType
from domain.plan import ResearchPlan
from domain.research import ResearchItem, ResearchProvider, empty_research_note
from state import FundForgeState

logger = logging.getLogger(__name__)


class ResearcherOutput(TypedDict, total=False):
    """Researcher 节点输出（§4：research_items, evidence）。"""

    research_items: list[ResearchItem]
    evidence: list[Evidence]
    data_quality_issues: list[str]


class ResearcherNode:
    """Researcher 节点：经 ResearchProvider 获取外部研究（可注入 mock）。"""

    def __init__(self, provider: ResearchProvider | None = None) -> None:
        self._provider = provider

    def __call__(self, state: FundForgeState) -> ResearcherOutput:
        plan = ResearchPlan.from_state(state.get("research_plan"))
        primary_id = None
        if plan:
            primary_id = plan.primary_fund_id or (plan.fund_ids[0] if plan.fund_ids else None)
        if primary_id is None:
            primary_id = next(iter(state.get("fund_ids", [])), None)

        if self._provider is None:
            # 外部研究缺失是 V1 预期状态，非数据质量问题：仅日志记录，不进 issues
            logger.info("researcher: %s", empty_research_note())
            return ResearcherOutput(research_items=[])

        query = f"{primary_id} 基金 分析" if primary_id else "基金 研究"
        items = self._provider.search(query)
        evidence = [
            Evidence(
                id=f"ev-{uuid.uuid4().hex[:12]}",
                evidence_type=EvidenceType.RESEARCH,
                source=item.source,
                source_detail=item.title,
                as_of=item.as_of or datetime.now(),
                value={"title": item.title, "content": item.content[:500]},
                raw_ref=None,
            )
            for item in items
        ]
        logger.info("researcher: %d research items for %r", len(items), query)
        return ResearcherOutput(
            research_items=items,
            evidence=[*state.get("evidence", []), *evidence],
        )


__all__ = ["ResearcherNode", "ResearcherOutput"]
