"""Router 节点（Node 合同 §4）。

职责：判断任务类型，不负责投资分析，不负责数据可行性（Planner 校验）。
确定性关键词分类：
- 仅含对比意图（无分析类词）→ fund_comparison；
- 含分析意图（分析 / 适合 / 持有 …）→ fund_research（对比基金由 Planner 规划）。
名称→代码解析、对比可行性校验在 Planner 完成（Phase 7+ 增强）。
"""

import logging
from typing import TypedDict

from domain.task_type import COMPARISON_INTENT_KEYWORDS, ANALYSIS_INTENT_KEYWORDS, TaskType
from state import FundForgeState

logger = logging.getLogger(__name__)


class RouterOutput(TypedDict, total=False):
    task_type: TaskType


class RouterNode:
    """Router 节点：判断任务类型。"""

    def __call__(self, state: FundForgeState) -> RouterOutput:
        query = state.get("user_query", "")
        has_analysis_intent = any(kw in query for kw in ANALYSIS_INTENT_KEYWORDS)
        has_comparison_intent = any(kw in query for kw in COMPARISON_INTENT_KEYWORDS)
        # 对比 + 分析意图并存（如「分析A并与B比较」）属于带 peer 的 fund_research（V1 核心 Case）
        task_type = (
            TaskType.FUND_COMPARISON
            if has_comparison_intent and not has_analysis_intent
            else TaskType.FUND_RESEARCH
        )
        logger.info("router: user_query=%r task_type=%s", query, task_type)
        return RouterOutput(task_type=task_type)


__all__ = ["RouterNode", "RouterOutput"]
