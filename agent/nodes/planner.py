"""Planner 节点（Node 合同 §4）。

职责：决定需要哪些数据，输出结构化 research_plan。约束：不直接执行 Tool。
- 消费 Router 的 task_type 初始分类，做**数据可行性校验**：
  对比意图但基金代码不足 2 只 → 降级 fund_research 并记录 note；
- 提取 6 位基金代码（首个为主基金），其余为对比基金（peer_fund_ids）；
- 不调用 LLM；名称→代码解析为 Phase 7+ 增强。
"""

import logging
import re
from typing import TypedDict

from domain.plan import ResearchPlan
from domain.task_type import TaskType
from state import FundForgeState

logger = logging.getLogger(__name__)

_FUND_CODE_RE = re.compile(r"\b(\d{6})\b")


class PlannerOutput(TypedDict, total=False):
    task_type: TaskType
    research_plan: ResearchPlan
    peer_fund_ids: list[str]


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


class PlannerNode:
    """Planner 节点：从 query 规划数据采集计划（含对比基金与可行性校验）。"""

    def __call__(self, state: FundForgeState) -> PlannerOutput:
        query = state.get("user_query", "")
        task_type = self._initial_task_type(state)
        fund_ids = extract_fund_codes(query)

        if not fund_ids:
            note = "query 中未发现 6 位基金代码，无法规划数据采集"
            logger.warning("planner: %s", note)
            plan = ResearchPlan(task_type=task_type, fund_ids=[], notes=[note])
            return PlannerOutput(task_type=task_type, research_plan=plan)

        primary = fund_ids[0]
        peers = fund_ids[1:]
        notes: list[str] = []

        # 可行性校验：对比任务至少需要 2 只基金，否则降级为单基金研究
        if task_type == TaskType.FUND_COMPARISON and len(fund_ids) < 2:
            note = "query 含对比意图但基金代码不足 2 只，按单基金研究（fund_research）处理"
            notes.append(note)
            task_type = TaskType.FUND_RESEARCH
            logger.warning("planner: %s", note)

        if peers and task_type == TaskType.FUND_RESEARCH:
            notes.append(f"检测到对比基金 {peers}，已纳入 research_plan")

        plan = ResearchPlan(
            task_type=task_type,
            primary_fund_id=primary,
            fund_ids=fund_ids,
            peer_fund_ids=peers,
            notes=notes,
        )
        logger.info(
            "planner: task_type=%s primary=%s peers=%s",
            task_type,
            primary,
            peers,
        )
        return PlannerOutput(
            task_type=task_type,
            research_plan=plan,
            peer_fund_ids=peers,
        )

    @staticmethod
    def _initial_task_type(state: FundForgeState) -> TaskType:
        """读取 Router 的初始分类（State 回传可能是 str/enum，容错归一化）。"""
        raw = state.get("task_type")
        if raw is None:
            return TaskType.FUND_RESEARCH
        try:
            return TaskType(str(raw))
        except ValueError:
            return TaskType.FUND_RESEARCH


__all__ = ["PlannerNode", "PlannerOutput", "extract_fund_codes"]
