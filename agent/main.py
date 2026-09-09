"""FundForge Agent 入口脚本（Phase 0）。

用法：
    python main.py "任意问题"

行为：
    运行空工作流 router → planner → synthesizer，输出固定字符串报告。
    不包含真实 Tool、真实 LLM 调用、真实数据。
"""

import logging
import sys
import uuid

from graph import build_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fundforge")


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or "测试"
    logger.info("received query: %r", user_query)

    graph = build_graph()

    state = {
        "request_id": uuid.uuid4().hex,
        "user_query": user_query,
    }
    result = graph.invoke(state)

    print()
    print(result["report"])
    print()
    logger.info("final state: %s", result)


if __name__ == "__main__":
    main()
