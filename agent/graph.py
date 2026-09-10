"""Graph 构建 — V1 工作流骨架。

Graph 合同见 docs/TechnicalContract.md §5。完整 V1 Graph 为：
router → planner → collector → analyzer → researcher → thesis → evaluator → synthesizer

Phase 2 已接入：router → planner → collector → analyzer → synthesizer → END
（researcher / thesis / evaluator 在后续 Phase 接入）。
条件边：planner 之后若无 fund_ids，则短路直达 synthesizer（输出引导信息）。
Workflow Control 由 LangGraph 和程序逻辑负责，不由 LLM 决定执行路径。
"""

from langgraph.graph import END, START, StateGraph

from domain.plan import ResearchPlan
from nodes import AnalyzerNode, CollectorNode, planner, router, synthesizer
from state import FundForgeState
from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools


def _route_after_plan(state: FundForgeState) -> str:
    """planner 之后的路由：无 fund_ids 时短路跳过 collector。"""
    plan = ResearchPlan.from_state(state.get("research_plan"))
    if plan and plan.fund_ids:
        return "collector"
    return "synthesizer"


def build_graph(client: CollectorClient | None = None, store: FundStore | None = None):
    """构建并编译 FundForge V1 Graph。

    client / store 可注入（测试用）；默认按环境配置创建。
    """
    store = store or FundStore()
    client = client or CollectorClient()
    tools = make_fund_tools(client, store)

    graph = StateGraph(FundForgeState)

    graph.add_node("router", router)
    graph.add_node("planner", planner)
    graph.add_node("collector", CollectorNode(tools))
    graph.add_node("analyzer", AnalyzerNode(store))
    graph.add_node("synthesizer", synthesizer)

    graph.add_edge(START, "router")
    graph.add_edge("router", "planner")
    graph.add_conditional_edges("planner", _route_after_plan, ["collector", "synthesizer"])
    graph.add_edge("collector", "analyzer")
    graph.add_edge("analyzer", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph.compile()
