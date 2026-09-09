"""Graph 构建 — V1 工作流骨架。

Graph 合同见 docs/TechnicalContract.md §5。完整 V1 Graph 为：
router → planner → collector → analyzer → researcher → thesis → evaluator → synthesizer

Phase 0 仅接入已存在的空节点：router → planner → synthesizer → END。
Workflow Control 由 LangGraph 负责，不由 LLM 决定执行路径。
"""

from langgraph.graph import END, START, StateGraph

from state import FundForgeState
from nodes import planner, router, synthesizer


def build_graph():
    """构建并编译 FundForge V1 空流程 Graph。"""
    graph = StateGraph(FundForgeState)

    graph.add_node("router", router)
    graph.add_node("planner", planner)
    graph.add_node("synthesizer", synthesizer)

    # add_edge(from_node, to_node)
    graph.add_edge(START, "router")
    graph.add_edge("router", "planner")
    graph.add_edge("planner", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph.compile()
