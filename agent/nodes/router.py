"""Router 节点（Node 合同 §4）。

职责：判断任务类型，不负责投资分析，不负责数据可行性（Planner 校验）。
分类由 nodes/intent.py 的确定性规则引擎完成：规则按序命中、首个生效，
规则命中与置信度写入 State（供 Planner 透传与后续评测）。
"""

import logging
from typing import TypedDict

from domain.task_type import ClassificationRuleHit, TaskType
from nodes.intent import IntentClassification, classify
from state import FundForgeState

logger = logging.getLogger(__name__)


class RouterOutput(TypedDict, total=False):
    task_type: TaskType
    classification_rule_hit: ClassificationRuleHit
    classification_confidence: float


class RouterNode:
    """Router 节点：基于意图规则引擎判断任务类型。"""

    def __call__(self, state: FundForgeState) -> RouterOutput:
        query = state.get("user_query", "")
        result: IntentClassification = classify(query)
        logger.info(
            "router: user_query=%r task_type=%s rule=%s confidence=%.2f",
            query,
            result.task_type,
            result.rule_hit,
            result.confidence,
        )
        return RouterOutput(
            task_type=result.task_type,
            classification_rule_hit=result.rule_hit,
            classification_confidence=result.confidence,
        )


__all__ = ["RouterNode", "RouterOutput"]
