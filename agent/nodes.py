"""空节点实现（Phase 0 骨架）。

Node 合同见 docs/TechnicalContract.md §4。当前全部为空实现：
- router / planner：仅记录日志并透传 State；
- synthesizer：输出固定字符串报告（不调用 LLM）。

后续 Phase 将逐步填充真实逻辑（Phase 3 起才引入 LLM 调用）。
"""

import logging

from state import FundForgeState

logger = logging.getLogger(__name__)


def router(state: FundForgeState) -> dict:
    """Router：判断任务类型。Phase 0 为空实现，直接透传。"""
    logger.info("router: user_query=%r", state.get("user_query"))
    return {}


def planner(state: FundForgeState) -> dict:
    """Planner：生成 research_plan。Phase 0 为空实现，直接透传。"""
    logger.info("planner: pass-through")
    return {}


def synthesizer(state: FundForgeState) -> dict:
    """Synthesizer：组装最终报告。Phase 0 输出固定字符串。"""
    logger.info("synthesizer: generating fixed report")
    report = (
        "FundForge 研究报告（Phase 0 骨架输出）\n"
        "========================================\n"
        "本报告由空工作流生成，仅用于验证 Graph 可运行。\n"
        "尚未接入数据采集、量化分析与 LLM 推理。\n"
        "\n"
        "免责声明：本报告不构成任何投资建议。"
    )
    return {"report": report}
