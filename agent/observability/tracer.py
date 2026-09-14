"""运行期 Trace 采集器：包装节点，记录输入/输出摘要与耗时。

用法（DI，与 Store / LLM Provider 一致）：
    tracer = RunTracer()
    graph = build_graph(tracer=tracer)
    result = graph.invoke(state)
    trace = tracer.build(result)      # → RunTrace
    sink.write(trace)

说明：
- 失败节点也会被记录（duration + error），异常继续向上抛出；
- tracer 记住最近一次节点输入 State，异常退出时也能 build 出部分 Trace；
- 业务摘要集中在 observability 层（_NODE_SUMMARIZERS），节点保持业务纯净。
"""

import logging
import time
from datetime import datetime
from typing import Any, Callable

from domain.evaluation import EvaluationResult
from domain.evidence import ToolCallRecord, TokenUsage
from domain.report import Report
from domain.shared import coerce_model
from domain.thesis import InvestmentThesis
from observability.models import GenerationTrace, NodeChild, NodeTrace, RunTrace

logger = logging.getLogger(__name__)


def _get(output: Any, key: str, default: Any = None) -> Any:
    return output.get(key, default) if isinstance(output, dict) else default


def _len(value: Any) -> int:
    return len(value) if value else 0


def _short(text: Any, limit: int = 100) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _duration_ms(started_mono: float, finished_mono: float) -> float:
    """耗时用 monotonic 时钟计算（wall clock 受 NTP/时钟调整影响，会扭曲 duration）。"""
    return round((finished_mono - started_mono) * 1000, 2)


# ---- 节点业务摘要器（关键节点给出可调试的业务字段，体积可控） ----

def _summarize_router(state: dict, output: dict) -> dict:
    return {
        "task_type": str(_get(output, "task_type")),
        "rule_hit": str(_get(output, "classification_rule_hit")),
        "confidence": _get(output, "classification_confidence"),
    }


def _summarize_planner(state: dict, output: dict) -> dict:
    plan = _get(output, "research_plan")
    return {
        "task_type": str(getattr(plan, "task_type", None)),
        "primary_fund_id": getattr(plan, "primary_fund_id", None),
        "fund_ids": _len(getattr(plan, "fund_ids", None)),
        "peer_fund_ids": _len(getattr(plan, "peer_fund_ids", None)),
        "notes": _len(getattr(plan, "notes", None)),
        "rule_hits": [str(h) for h in (getattr(plan, "classification_rule_hits", None) or [])],
    }


def _summarize_collector(state: dict, output: dict) -> dict:
    summaries = _get(output, "funds_summary", []) or []
    return {
        "fund_ids": _len(_get(output, "fund_ids", [])),
        "funds_collected": _len(summaries),
        "fund_quality": {s.id: str(s.data_quality) for s in summaries},
        "evidence": _len(_get(output, "evidence", [])),
        "tool_calls": _len(_get(output, "tool_calls", [])),
        "tool_failures": sum(1 for t in (_get(output, "tool_calls", []) or []) if not t.success),
        "data_quality_issues": _len(_get(output, "data_quality_issues", [])),
    }


def _summarize_analyzer(state: dict, output: dict) -> dict:
    analysis = _get(output, "analysis")
    performance = getattr(analysis, "performance", None)
    return {
        "analysis_present": analysis is not None,
        "primary_quality": str(getattr(performance, "data_quality", None)),
        "nav_point_count": getattr(performance, "nav_point_count", None),
        "peer_comparison": getattr(analysis, "peer_comparison", None) is not None,
        "alignment_window": [
            str(getattr(performance, "period_start", None)),
            str(getattr(performance, "period_end", None)),
        ],
        "evidence": _len(_get(output, "evidence", [])),
        "data_quality_issues": _len(_get(output, "data_quality_issues", [])),
    }


def _summarize_researcher(state: dict, output: dict) -> dict:
    return {"research_items": _len(_get(output, "research_items", []))}


def _summarize_thesis(state: dict, output: dict) -> dict:
    thesis = _get(output, "investment_thesis")
    usage = _get(output, "token_usage")
    return {
        "claims": _len(_get(output, "claims", [])),
        "suitability": _short(getattr(thesis, "suitability", None)),
        "confidence": getattr(thesis, "confidence", None),
        "data_gaps": _len(getattr(thesis, "data_gaps", None)),
        "llm_calls": getattr(usage, "llm_calls", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "data_quality_issues": _len(_get(output, "data_quality_issues", [])),
    }


def _summarize_evaluator(state: dict, output: dict) -> dict:
    evaluation = _get(output, "evaluation")
    issues = getattr(evaluation, "all_issues", None)
    issue_list = issues() if callable(issues) else (issues or [])
    return {
        "status": str(getattr(evaluation, "status", None)),
        "overall_score": getattr(evaluation, "overall_score", None),
        "claim_coverage_ratio": getattr(evaluation, "claim_coverage_ratio", None),
        "critical": getattr(evaluation, "critical", None),
        "issues": _len(issue_list),
    }


def _summarize_repair(state: dict, output: dict) -> dict:
    return {
        "iteration": _get(output, "iteration"),
        "actions": _len(_get(output, "repair_actions", [])),
        "claims_after": _len(_get(output, "claims", [])),
    }


def _summarize_synthesizer(state: dict, output: dict) -> dict:
    report = _get(output, "report")
    metadata = getattr(report, "metadata", None)
    return {
        "report_title": _short(getattr(report, "title", None), 80),
        "thesis_generated": getattr(metadata, "thesis_generated", None),
        "evaluation_status": getattr(metadata, "evaluation_status", None),
        "evidence_count": getattr(metadata, "evidence_count", None),
    }


_NODE_SUMMARIZERS: dict[str, Callable[[dict, dict], dict]] = {
    "router": _summarize_router,
    "planner": _summarize_planner,
    "collector": _summarize_collector,
    "analyzer": _summarize_analyzer,
    "researcher": _summarize_researcher,
    "thesis": _summarize_thesis,
    "evaluator": _summarize_evaluator,
    "repair": _summarize_repair,
    "synthesizer": _summarize_synthesizer,
}


def _default_summary(output: dict) -> dict:
    """无专用摘要器时的兜底：列表记数量，模型记类型名，其余截断字符串。"""
    summary: dict[str, Any] = {}
    for key, value in output.items():
        if isinstance(value, (list, tuple)):
            summary[key] = {"count": len(value)}
        elif isinstance(value, dict):
            summary[key] = {"keys": sorted(value.keys())}
        elif hasattr(value, "model_dump"):
            summary[key] = {"type": type(value).__name__}
        else:
            summary[key] = _short(value)
    return summary


def _make_generation(state: dict, thesis, usage: TokenUsage, model: str | None) -> GenerationTrace:
    return GenerationTrace(
        name="thesis-llm",
        node="thesis",
        model=model,
        calls=1,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        input_summary={
            "funds": _len(state.get("funds_summary", [])),
            "analysis_present": state.get("analysis") is not None,
            "evidence": _len(state.get("evidence", [])),
            "research_items": _len(state.get("research_items", [])),
        },
        output_summary={
            "claims": _len(thesis.claims),
            "suitability": _short(thesis.suitability),
            "confidence": thesis.confidence,
            "data_gaps": _len(thesis.data_gaps),
        },
    )


def _node_children(name: str, state: dict, output: dict, model: str | None) -> list[NodeChild]:
    """节点 span 内需要嵌套的子元素（live tracing 用）：

    - collector → tool 调用事件
    - thesis → LLM generation
    """
    children: list[NodeChild] = []
    if name == "collector":
        for call in output.get("tool_calls") or []:
            children.append({"kind": "tool", "call": call})
    elif name == "thesis":
        usage = output.get("token_usage")
        thesis = output.get("investment_thesis")
        if usage is not None and getattr(usage, "llm_calls", 0) and thesis is not None:
            children.append({"kind": "generation", "generation": _make_generation(state, thesis, usage, model)})
    return children


class RunTracer:
    """节点包装器 + RunTrace 组装。

    live_sink（可选）：支持 begin_run/begin_node/end_node 的 Sink（如 Langfuse），
    在节点真实执行时创建/关闭 span —— 时间戳与顺序即真实执行顺序。
    未配置时仅累积 RunTrace，由 sink.write(trace) 一次性写入。
    并发：节点级 live span 按节点名索引，支持并行分支（同节点同名并行不支持）。
    """

    def __init__(self, live_sink: Any | None = None) -> None:
        self._nodes: list[NodeTrace] = []
        self._last_state: dict | None = None
        self._live = live_sink
        self._run_started: datetime | None = None
        self.llm_model: str | None = None

    def set_live_sink(self, live_sink: Any | None) -> None:
        """注入 live sink（须在 begin_run 之前调用）。"""
        self._live = live_sink

    def begin_run(self, request_id: str, user_query: str) -> None:
        """记录运行真实起点（含 first-node 之前的开销）；有 live sink 时同时开启运行级 span。"""
        self._run_started = datetime.now()
        if self._live is None:
            return
        try:
            self._live.begin_run(request_id, user_query)
        except Exception as e:  # noqa: BLE001 —— 可观测性故障不影响业务
            logger.error("live trace begin failed, fallback to end-of-run write: %s", e)
            self._live = None

    def wrap(self, name: str, node: Callable) -> Callable:
        """包装节点：记录耗时与业务摘要；失败也记录后继续抛出。"""
        summarize = _NODE_SUMMARIZERS.get(name, _default_summary)

        def traced(state: dict) -> dict:
            self._last_state = state
            started_mono = time.monotonic()
            started = datetime.now()
            if self._live is not None:
                try:
                    self._live.begin_node(name)
                except Exception as e:  # noqa: BLE001
                    logger.error("live trace begin_node failed: %s", e)
                    self._live = None
            try:
                output = node(state)
            except Exception as e:  # noqa: BLE001 —— 记录失败节点后原样抛出
                finished_mono = time.monotonic()
                node_trace = NodeTrace(
                    node=name,
                    started_at=started,
                    finished_at=datetime.now(),
                    duration_ms=_duration_ms(started_mono, finished_mono),
                    input_keys=sorted(state.keys()),
                    error=f"{type(e).__name__}: {e}"[:300],
                )
                self._nodes.append(node_trace)
                self._end_live_node(name, node_trace, children=[])
                logger.error("traced node %s failed: %s", name, e)
                raise
            finished_mono = time.monotonic()
            output_dict = output if isinstance(output, dict) else {}
            node_trace = NodeTrace(
                node=name,
                started_at=started,
                finished_at=datetime.now(),
                duration_ms=_duration_ms(started_mono, finished_mono),
                input_keys=sorted(state.keys()),
                output_keys=sorted(output_dict.keys()),
                output_summary=summarize(state, output_dict),
            )
            self._nodes.append(node_trace)
            self._end_live_node(name, node_trace, children=_node_children(name, state, output_dict, self.llm_model))
            return output

        return traced

    def _end_live_node(self, name: str, node_trace: NodeTrace, children: list[dict]) -> None:
        if self._live is None:
            return
        try:
            self._live.end_node(name, node_trace, children)
        except Exception as e:  # noqa: BLE001
            logger.error("live trace end_node failed: %s", e)
            self._live = None

    @property
    def last_state(self) -> dict | None:
        """最近一次节点输入 State（异常退出时用于组装部分 Trace）。"""
        return self._last_state

    def build(self, state: dict, error: str | None = None) -> RunTrace:
        """由最终（或部分）State 组装 RunTrace。"""
        started = self._run_started or min((n.started_at for n in self._nodes), default=datetime.now())
        finished = datetime.now()
        report = coerce_model(state.get("report"), Report)
        usage = coerce_model(state.get("token_usage"), TokenUsage) or TokenUsage()
        return RunTrace(
            request_id=state.get("request_id", ""),
            user_query=state.get("user_query", ""),
            started_at=started,
            finished_at=finished,
            nodes=list(self._nodes),
            tool_calls=[
                t if isinstance(t, ToolCallRecord) else ToolCallRecord.model_validate(t)
                for t in state.get("tool_calls", [])
            ],
            generations=_build_generations(state, usage, self.llm_model),
            token_usage=usage,
            llm_model=self.llm_model,
            evaluation=coerce_model(state.get("evaluation"), EvaluationResult),
            report_metadata=report.metadata if report is not None else None,
            data_quality_issues=list(state.get("data_quality_issues", [])),
            error=error,
        )


def _build_generations(state: dict, usage: TokenUsage, model: str | None) -> list[GenerationTrace]:
    """从 State 派生 LLM 调用记录（当前仅 Thesis；未来新增调用可扩展）。

    局限：节点硬崩（非 ThesisNode 内部已捕获的 LLMError/ValidationError 路径）时
    usage 不入 State，该次 generation 无法归因——ThesisNode 已覆盖常见失败。
    """
    thesis = coerce_model(state.get("investment_thesis"), InvestmentThesis)
    if usage.llm_calls and thesis is not None:
        return [_make_generation(state, thesis, usage, model)]
    return []


__all__ = ["RunTracer"]
