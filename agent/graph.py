"""Graph 构建 — V1 工作流骨架。

Graph 合同见 docs/TechnicalContract.md §5。完整 V1 Graph 为：
router → planner → collector → analyzer → researcher → thesis → evaluator → synthesizer

Phase 5 已接入：router → planner → collector → analyzer → thesis → evaluator
→ (PASS) synthesizer → END / (FAIL) repair → evaluator（iteration 硬限制 max=1，
超限强制 synthesizer 并在报告中标注证据不足）。
（researcher 在后续 Phase 接入。）
条件边：planner 之后若无 fund_ids，则短路直达 synthesizer（输出引导信息）。
Workflow Control 由 LangGraph 和程序逻辑负责，不由 LLM 决定执行路径。

task_type → 节点路径（三处条件边的判据集中在此表，改动路由须同步）：

| task_type        | planner 之后                | analyzer 之后   | evaluator FAIL |
| ---------------- | --------------------------- | --------------- | -------------- |
| FUND_SCREENING   | screener                    | screen_finalize | 直达 synthesizer |
| 其余任务         | collector（无 fund_ids 则 synthesizer） | researcher | repair（≤1 次）→ synthesizer |

筛选任务的两处例外均由「全确定性、无 LLM 产物可修」与「无需论点」推出，
与上表同源；改动任一例外须回到本表核对。
"""

from langgraph.graph import END, START, StateGraph

from domain.evaluation import EvaluationStatus
from domain.plan import ResearchPlan
from domain.task_type import TaskType
from llm import LLMProvider, make_default_llm
from nodes import (
    AnalyzerNode,
    CollectorNode,
    EvaluatorNode,
    PlannerNode,
    RepairNode,
    ResearcherNode,
    RouterNode,
    ScreenFinalizeNode,
    ScreenerNode,
    SynthesizerNode,
    ThesisNode,
)
from state import FundForgeState
from store import FundStore
from observability import RunTracer
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools

MAX_REPAIR_ITERATIONS = 1  # §13 CostLimits.max_repair_iterations

# 区分「未传 llm（按环境变量构建）」与「显式 llm=None（无 LLM，Thesis 降级）」：
# None 不能兼任两种语义，否则测试在配置了 LLM_* 环境变量的机器上会打出真实请求
_UNSET = object()


def _is_screening(task_type: object) -> bool:
    """是否筛选任务（fund_screening）。

    三处条件边共用本判据，避免同一谓词在三份路由函数里各写一遍后彼此漂移。
    task_type 显式传入而非读 state：planner 之后取自 research_plan（plan 可能
    为 None），analyzer / evaluator 之后取自 state。路由差异见本模块
    docstring 的「task_type → 节点路径」表。
    """
    return task_type == TaskType.FUND_SCREENING


def _route_after_plan(state: FundForgeState) -> str:
    """planner 之后的路由：筛选任务 → screener；无 fund_ids 时短路跳过 collector。"""
    plan = ResearchPlan.from_state(state.get("research_plan"))
    if plan and _is_screening(plan.task_type):
        return "screener"
    if plan and plan.fund_ids:
        return "collector"
    return "synthesizer"


def _route_after_analyzer(state: FundForgeState) -> str:
    """analyzer 之后的路由：筛选任务 → screen_finalize（跳过 researcher/thesis）。"""
    if _is_screening(state.get("task_type")):
        return "screen_finalize"
    return "researcher"


def _route_after_evaluation(state: FundForgeState) -> str:
    """evaluator 之后的路由（§5 唯一条件边）：PASS → synthesizer；
    FAIL → repair（仅 1 次），超限强制 synthesizer。
    筛选任务不进 repair 回路（确定性流程无可修 LLM 产物），FAIL 直达 synthesizer。"""
    if _is_screening(state.get("task_type")):
        return "synthesizer"
    evaluation = state.get("evaluation")
    iteration = int(state.get("iteration", 0))
    if evaluation is not None and evaluation.status == EvaluationStatus.FAIL and iteration < MAX_REPAIR_ITERATIONS:
        return "repair"
    return "synthesizer"


def build_graph(
    client: CollectorClient | None = None,
    store: FundStore | None = None,
    llm: LLMProvider | None | object = _UNSET,
    tracer: RunTracer | None = None,
):
    """构建并编译 FundForge V1 Graph。

    client / store / llm / tracer 可注入（测试用）；llm 未传时按环境变量构建
    （LLM_BASE_URL / LLM_API_KEY / LLM_MODEL），显式传 None 表示无 LLM（Thesis 降级）。
    tracer 记录每个节点的输入/输出摘要，供可观测性 sink 持久化。
    """
    store = store or FundStore()
    client = client or CollectorClient()
    llm = make_default_llm() if llm is _UNSET else llm
    tracer = tracer or RunTracer()
    tracer.llm_model = getattr(llm, "model", None)
    tools = make_fund_tools(client, store)

    graph = StateGraph(FundForgeState)

    graph.add_node("router", tracer.wrap("router", RouterNode()))
    graph.add_node("planner", tracer.wrap("planner", PlannerNode()))
    graph.add_node("screener", tracer.wrap("screener", ScreenerNode(client, llm)))
    graph.add_node("collector", tracer.wrap("collector", CollectorNode(tools)))
    graph.add_node("analyzer", tracer.wrap("analyzer", AnalyzerNode(store)))
    graph.add_node("screen_finalize", tracer.wrap("screen_finalize", ScreenFinalizeNode(store)))
    graph.add_node("researcher", tracer.wrap("researcher", ResearcherNode()))
    graph.add_node("thesis", tracer.wrap("thesis", ThesisNode(llm)))
    graph.add_node("evaluator", tracer.wrap("evaluator", EvaluatorNode()))
    graph.add_node("repair", tracer.wrap("repair", RepairNode()))
    graph.add_node("synthesizer", tracer.wrap("synthesizer", SynthesizerNode()))

    graph.add_edge(START, "router")
    graph.add_edge("router", "planner")
    graph.add_conditional_edges(
        "planner", _route_after_plan, ["screener", "collector", "synthesizer"]
    )
    graph.add_edge("screener", "collector")
    graph.add_edge("collector", "analyzer")
    graph.add_conditional_edges(
        "analyzer", _route_after_analyzer, ["screen_finalize", "researcher"]
    )
    graph.add_edge("screen_finalize", "evaluator")
    graph.add_edge("researcher", "thesis")
    graph.add_edge("thesis", "evaluator")
    graph.add_conditional_edges(
        "evaluator", _route_after_evaluation, ["repair", "synthesizer"]
    )
    graph.add_edge("repair", "evaluator")
    graph.add_edge("synthesizer", END)

    return graph.compile()
