"""Planner 节点（Node 合同 §4）。

职责：决定需要哪些数据，输出结构化 research_plan。约束：不直接执行 Tool。
- 消费 Router 的意图分类（task_type + rule_hit + confidence）；
- 数据可行性校验：对比意图但基金代码不足 2 只 → 降级 fund_research 并记录 note；
- 提取 6 位基金代码（首个为主基金），其余为对比基金（peer_fund_ids，§2）；
- 分类规则命中与置信度透传进 research_plan（评测与对齐检查用）；
- 不调用 LLM；名称→代码解析为 Phase 7+ 增强。
"""

import logging
from typing import TypedDict

from domain.plan import ResearchPlan
from domain.task_type import ClassificationRuleHit, TaskType
from nodes.intent import classify, extract_fund_codes
from state import FundForgeState

logger = logging.getLogger(__name__)


class PlannerOutput(TypedDict, total=False):
    task_type: TaskType
    research_plan: ResearchPlan
    peer_fund_ids: list[str]


class PlannerNode:
    """Planner 节点：从 query 规划数据采集计划（含对比基金与可行性校验）。"""

    def __call__(self, state: FundForgeState) -> PlannerOutput:
        query = state.get("user_query", "")
        classification = classify(query)
        task_type = classification.task_type
        fund_ids = classification.fund_ids
        rule_hits = [classification.rule_hit]
        confidence = classification.confidence

        if not fund_ids:
            note = "query 中未发现 6 位基金代码，无法规划数据采集"
            logger.warning("planner: %s", note)
            plan = ResearchPlan(
                task_type=task_type,
                fund_ids=[],
                notes=[note],
                classification_rule_hits=rule_hits,
                classification_confidence=confidence,
            )
            return PlannerOutput(task_type=task_type, research_plan=plan)

        primary = fund_ids[0]
        peers = fund_ids[1:]
        notes: list[str] = []

        # 可行性校验：对比任务至少需要 2 只基金，否则降级为单基金研究
        if task_type == TaskType.FUND_COMPARISON and len(fund_ids) < 2:
            note = "query 含对比意图但基金代码不足 2 只，按单基金研究（fund_research）处理"
            notes.append(note)
            task_type = TaskType.FUND_RESEARCH
            rule_hits.append(ClassificationRuleHit.FEASIBILITY_DOWNGRADE)
            confidence = min(confidence, 0.5)
            logger.warning("planner: %s", note)

        if peers and task_type == TaskType.FUND_RESEARCH:
            notes.append(f"检测到对比基金 {peers}，已纳入 research_plan")

        plan = ResearchPlan(
            task_type=task_type,
            primary_fund_id=primary,
            fund_ids=fund_ids,
            peer_fund_ids=peers,
            notes=notes,
            classification_rule_hits=rule_hits,
            classification_confidence=confidence,
        )
        logger.info(
            "planner: task_type=%s primary=%s peers=%s rule=%s confidence=%.2f",
            task_type,
            primary,
            peers,
            classification.rule_hit,
            confidence,
        )
        return PlannerOutput(
            task_type=task_type,
            research_plan=plan,
            peer_fund_ids=peers,
        )


__all__ = ["PlannerNode", "PlannerOutput", "extract_fund_codes"]
