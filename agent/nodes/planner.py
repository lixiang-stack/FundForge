"""Planner 节点（Node 合同 §4）。

职责：决定需要哪些数据。约束：不直接执行 Tool，输出必须结构化。
Phase 1 为确定性实现：从 query 中提取 6 位基金代码，不调用 LLM。
"""

import logging
import re

from domain.plan import ResearchPlan
from domain.task_type import TaskType
from state import FundForgeState

logger = logging.getLogger(__name__)

_FUND_CODE_RE = re.compile(r"\b(\d{6})\b")


def extract_fund_codes(query: str) -> list[str]:
    """从用户 query 中提取 6 位基金代码（去重、保序）。"""
    seen: set[str] = set()
    codes: list[str] = []
    for m in _FUND_CODE_RE.finditer(query):
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def planner(state: FundForgeState) -> dict:
    query = state.get("user_query", "")
    fund_ids = extract_fund_codes(query)
    if not fund_ids:
        note = "query 中未发现 6 位基金代码，无法规划数据采集"
        logger.warning("planner: %s", note)
        plan = ResearchPlan(task_type=TaskType.FUND_RESEARCH, fund_ids=[], notes=[note])
    else:
        plan = ResearchPlan(
            task_type=TaskType.FUND_RESEARCH,
            primary_fund_id=fund_ids[0],
            fund_ids=fund_ids,
        )
    logger.info("planner: fund_ids=%s", plan.fund_ids)
    return {"task_type": plan.task_type, "research_plan": plan}
