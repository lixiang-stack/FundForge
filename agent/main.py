"""FundForge Agent 入口脚本（Phase 1）。

用法：
    uv run python main.py "分析基金 519770 是否适合长期持有"

行为：
    运行 router → planner → collector → synthesizer 工作流。
    Planner 从 query 中提取基金代码，Collector 经 collector service
    采集基金数据（结构化摘要 + Evidence），Synthesizer 输出报告。
    不包含 LLM 调用（Phase 3 引入）。
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

    print("=== funds_summary ===")
    for s in result.get("funds_summary", []):
        print(s.model_dump_json())
    print()
    print("=== evidence ===")
    for e in result.get("evidence", []):
        print(e.model_dump_json())
    print()
    print("=== tool_calls ===")
    for t in result.get("tool_calls", []):
        print(t.model_dump_json())
    print()
    print("=== investment_thesis ===")
    if result.get("investment_thesis") is not None:
        print(result["investment_thesis"].model_dump_json(indent=2))
    else:
        print("null（见数据质量提示）")


if __name__ == "__main__":
    main()
