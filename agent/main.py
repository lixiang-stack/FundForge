"""FundForge Agent 入口脚本。

用法：
    uv run python main.py "分析基金 519770 是否适合长期持有"

行为：
    运行完整工作流（router → planner → collector → analyzer → researcher →
    thesis → evaluator → repair/synthesizer），输出报告、完整 Trace 与 Trace ID。
    配置 LANGFUSE_* 时 Trace 同步写入 Langfuse（未配置则仅控制台输出）。

Trace 完整性：
    - 节点失败时仍写入失败节点（duration + error），运行级错误记入 RunTrace.error；
    - 无论成功或异常，Trace 都会写入 sink，且 sink 一定 shutdown（避免缓冲丢失）；
    - sink 写入失败不影响主流程（仅记日志）。
"""

import logging
import sys
import uuid

from graph import build_graph
from domain.report import render_markdown
from observability import RunTracer, find_jsonl_sink, find_langfuse_sink, find_live_sink, make_default_trace_sink
from observability.models import RunTrace
from observability.sink import TraceSink

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fundforge")


def _write_trace(tracer: RunTracer, state: dict, sink: TraceSink, error: str | None = None) -> RunTrace:
    """组装并写入 Trace；写入失败不中断主流程。"""
    trace = tracer.build(state, error=error)
    try:
        sink.write(trace)
    except Exception as e:  # noqa: BLE001 —— 可观测性故障不影响业务
        logger.error("trace sink write failed: %s", e)
    return trace


def _shutdown_sink(sink: TraceSink) -> None:
    """统一 Sink 生命周期：任何提供 shutdown 的 Sink（含组合 Sink）都会关闭。"""
    shutdown = getattr(sink, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown()
        except Exception as e:  # noqa: BLE001
            logger.warning("trace sink shutdown failed: %s", e)


def _print_report_and_trace(result: dict, trace: RunTrace, sink: TraceSink) -> None:
    report = result["report"]
    print()
    print(render_markdown(report))
    print()
    print("=== report (json) ===")
    print(report.model_dump_json(indent=2))

    print()
    print("=== evidence ===")
    for e in result.get("evidence", []):
        print(e.model_dump_json())
    print()
    print("=== tool_calls ===")
    for t in result.get("tool_calls", []):
        print(t.model_dump_json())
    print()
    print("=== evaluation ===")
    evaluation = result.get("evaluation")
    if evaluation is not None:
        print(f"status={evaluation.status} score={evaluation.overall_score} critical={evaluation.critical}")
        for issue in evaluation.all_issues():
            print(f"- {issue}")
    print()
    print("=== repair_actions ===")
    for a in result.get("repair_actions", []):
        print(f"- {a}")
    print(f"iteration: {result.get('iteration', 0)}")
    print()
    print("=== token_usage ===")
    usage = result.get("token_usage")
    print(usage.model_dump_json() if usage is not None else "null")
    print()
    print("=== research_items ===")
    items = result.get("research_items", [])
    print(f"{len(items)} items")
    for item in items:
        print(f"- [{item.source}] {item.title}")
    print()
    print("=== investment_thesis ===")
    if result.get("investment_thesis") is not None:
        print(result["investment_thesis"].model_dump_json(indent=2))
    else:
        print("null（见数据质量提示）")

    print()
    print("=== trace ===")
    print(f"Trace ID: {trace.request_id}")
    print(
        f"节点数: {len(trace.nodes)}，Tool 调用: {len(trace.tool_calls)}，"
        f"LLM 调用: {trace.token_usage.llm_calls}"
    )
    langfuse = find_langfuse_sink(sink)
    if langfuse is not None:
        url = langfuse.trace_url(trace.request_id)
        print(f"Langfuse: {url}" if url else "Langfuse: 已写入（URL 不可用）")
    else:
        print("Langfuse: 未配置（设置 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 启用）")
    trace_file_sink = find_jsonl_sink(sink)
    if trace_file_sink is not None:
        print(f"本地 Trace 文件: {trace_file_sink.path}")


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or "测试"
    logger.info("received query: %r", user_query)

    tracer = RunTracer()
    graph = build_graph(tracer=tracer)
    sink = make_default_trace_sink()

    state = {
        "request_id": uuid.uuid4().hex,
        "user_query": user_query,
    }

    # live tracing：span 在节点真实执行时创建/关闭（时间戳、顺序、时长即真实值）
    tracer.set_live_sink(find_live_sink(sink))
    tracer.begin_run(state["request_id"], user_query)

    try:
        try:
            result = graph.invoke(state)
        except Exception as exc:  # noqa: BLE001 —— 失败运行也保留 Trace 后继续抛出
            run_error = f"{type(exc).__name__}: {exc}"
            logger.error("run failed: %s", run_error)
            _write_trace(tracer, tracer.last_state or state, sink, error=run_error)
            raise
        trace = _write_trace(tracer, result, sink)
        _print_report_and_trace(result, trace, sink)
    finally:
        _shutdown_sink(sink)


if __name__ == "__main__":
    main()
