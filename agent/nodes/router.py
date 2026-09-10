"""Router 节点（Node 合同 §4）。

职责：判断任务类型，不负责投资分析。
Phase 1 为确定性 stub：默认 fund_research，不做 LLM 调用。
"""

import logging

from domain.task_type import TaskType
from state import FundForgeState

logger = logging.getLogger(__name__)


def router(state: FundForgeState) -> dict:
    logger.info("router: user_query=%r", state.get("user_query"))
    return {"task_type": TaskType.FUND_RESEARCH}
