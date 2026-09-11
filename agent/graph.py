"""Graph 构建 — V1 工作流骨架。

Graph 合同见 docs/TechnicalContract.md §5。完整 V1 Graph 为：
router → planner → collector → analyzer → researcher → thesis → evaluator → synthesizer

Phase 5 已接入：router → planner → collector → analyzer → thesis → evaluator
→ (PASS) synthesizer → END / (FAIL) repair → evaluator（iteration 硬限制 max=1，
超限强制 synthesizer 并在报告中标注证据不足）。
（researcher 在后续 Phase 接入。）
条件边：planner 之后若无 fund_ids，则短路直达 synthesizer（输出引导信息）。
Workflow Control 由 LangGraph 和程序逻辑负责，不由 LLM 决定执行路径。
"""

from langgraph.graph import END, START, StateGraph

from domain.evaluation import EvaluationStatus
from domain.plan import ResearchPlan
from llm import LLMProvider, make_default_llm
from nodes import (
    AnalyzerNode,
    CollectorNode,
    EvaluatorNode,
    PlannerNode,
    RepairNode,
    ResearcherNode,
    RouterNode,
    SynthesizerNode,
    ThesisNode,
)
from state import FundForgeState
from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools

MAX_REPAIR_ITERATIONS = 1  # §13 CostLimits.max_repair_iterations


def _route_after_plan(state: FundForgeState) -> str:
    """planner 之后的路由：无 fund_ids 时短路跳过 collector。"""
    plan = ResearchPlan.from_state(state.get("research_plan"))
    if plan and plan.fund_ids:
        return "collector"
    return "synthesizer"


def _route_after_evaluation(state: FundForgeState) -> str:
    """evaluator 之后的路由（§5 唯一条件边）：PASS → synthesizer；
    FAIL → repair（仅 1 次），超限强制 synthesizer。"""
    evaluation = state.get("evaluation")
    iteration = int(state.get("iteration", 0))
    if evaluation is not None and evaluation.status == EvaluationStatus.FAIL and iteration < MAX_REPAIR_ITERATIONS:
        return "repair"
    return "synthesizer"


def build_graph(
    client: CollectorClient | None = None,
    store: FundStore | None = None,
    llm: LLMProvider | None = None,
):
    """构建并编译 FundForge V1 Graph。

    client / store / llm 可注入（测试用）；llm 缺省时按环境变量构建
    （LLM_BASE_URL / LLM_API_KEY / LLM_MODEL），未配置则 Thesis 节点降级。
    """
    store = store or FundStore()
    client = client or CollectorClient()
    llm = llm if llm is not None else make_default_llm()
    tools = make_fund_tools(client, store)

    graph = StateGraph(FundForgeState)

    graph.add_node("router", RouterNode())
    graph.add_node("planner", PlannerNode())
    graph.add_node("collector", CollectorNode(tools))
    graph.add_node("analyzer", AnalyzerNode(store))
    graph.add_node("researcher", ResearcherNode())
    graph.add_node("thesis", ThesisNode(llm))
    graph.add_node("evaluator", EvaluatorNode())
    graph.add_node("repair", RepairNode())
    graph.add_node("synthesizer", SynthesizerNode())

    graph.add_edge(START, "router")
    graph.add_edge("router", "planner")
    graph.add_conditional_edges("planner", _route_after_plan, ["collector", "synthesizer"])
    graph.add_edge("collector", "analyzer")
    graph.add_edge("analyzer", "researcher")
    graph.add_edge("researcher", "thesis")
    graph.add_edge("thesis", "evaluator")
    graph.add_conditional_edges(
        "evaluator", _route_after_evaluation, ["repair", "synthesizer"]
    )
    graph.add_edge("repair", "evaluator")
    graph.add_edge("synthesizer", END)

    return graph.compile()
