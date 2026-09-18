"""FundForge Agent 入口脚本。

用法：
    uv run python main.py "分析基金 519770 是否适合长期持有"

行为：
    运行完整工作流（router → planner → collector → analyzer → researcher →
    thesis → evaluator → repair/synthesizer）。
    - 终端（精简）：只打印最终报告 + 文件路径；
    - 运行记录：output/<request_id>.md（分析过程在前、最终报告在后，失败也写入）；
    - 日志：log/<request_id>.log（INFO 全量；控制台仅 WARNING 以上）；
    - Trace：配置 LANGFUSE_* 时同步写入 Langfuse，TRACE_FILE 写本地 JSONL。

Trace 完整性：
    - 节点失败时仍写入失败节点（duration + error），运行级错误记入 RunTrace.error；
    - 无论成功或异常，Trace 都会写入 sink，且 sink 一定 shutdown（避免缓冲丢失）；
    - sink / 运行记录写入失败不影响主流程（仅记日志）。
"""

import json
import logging
import sys
import uuid
from pathlib import Path

from domain.evidence import LlmInteraction
from domain.report import Report, render_markdown
from domain.shared import coerce_model
from graph import build_graph
from observability import RunTracer, find_jsonl_sink, find_langfuse_sink, find_live_sink, make_default_trace_sink
from observability.models import RunTrace
from observability.sink import TraceSink

_AGENT_ROOT = Path(__file__).resolve().parent
_OUTPUT_DIR = _AGENT_ROOT / "output"
_LOG_DIR = _AGENT_ROOT / "log"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logger = logging.getLogger("fundforge")


def _setup_logging(request_id: str) -> Path:
    """日志落盘 log/<request_id>.log；控制台仅 WARNING 以上（精简终端）。"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"{request_id}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_handler, console_handler]
    return log_path


def _dump(obj) -> str:
    """模型 / dict / 其他统一转 JSON 文本（运行记录用）。"""
    dump = getattr(obj, "model_dump_json", None)
    if callable(dump):
        return dump()
    return json.dumps(obj, ensure_ascii=False, default=str)


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


def _write_run_output(
    state: dict,
    trace: RunTrace,
    sink: TraceSink,
    error: str | None = None,
) -> Path | None:
    """运行记录落盘 output/<request_id>.md：分析过程在前、最终报告在后。

    失败运行也写入（尽力保留已产出内容），便于回溯；写入失败不影响主流程。
    """
    try:
        report = coerce_model(state.get("report"), Report)
        request_id = state.get("request_id", "") or trace.request_id
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUTPUT_DIR / f"{request_id}.md"

        duration_s = (trace.finished_at - trace.started_at).total_seconds()
        lines = [
            "# FundForge 运行记录",
            "",
            f"- request_id: `{request_id}`",
            f"- query: {state.get('user_query', '')}",
            f"- 时间: {trace.started_at:%Y-%m-%d %H:%M:%S} ~ {trace.finished_at:%H:%M:%S}（{duration_s:.1f}s）",
            f"- task_type: {state.get('task_type') or '未知'} | model: {trace.llm_model or '未配置'}",
            f"- 结果: {'失败' if error else '成功'}",
        ]
        if error:
            lines.append(f"- 错误: {error}")
        lines.append("")

        lines += ["## 1. 分析过程", "", "### 1.1 节点轨迹", ""]
        for node in trace.nodes:
            status = f"失败：{node.error}" if node.error else "ok"
            summary = json.dumps(node.output_summary, ensure_ascii=False) if node.output_summary else ""
            lines.append(f"- {node.node}（{node.duration_ms}ms，{status}）{summary}")
        lines.append("")

        lines += ["### 1.2 Tool 调用", ""]
        lines += [f"- {_dump(t)}" for t in state.get("tool_calls", [])]
        lines.append("")

        lines += ["### 1.3 LLM 输入 / 输出", ""]
        interactions = state.get("llm_interactions", []) or []
        if not interactions:
            lines += ["（本次运行无 LLM 调用）", ""]
        for i, raw in enumerate(interactions, 1):
            it = coerce_model(raw, LlmInteraction)
            status = "成功" if it.ok else f"失败：{it.error}"
            tokens = f"入 {it.input_tokens} / 出 {it.output_tokens} tok"
            lines += [
                f"#### 调用 #{i}（{it.node}，model={it.model}，{tokens}，{status}）",
                "",
                "**输入：**",
                "",
                "````text",
                it.prompt,
                "````",
                "",
                "**输出：**",
                "",
                "````text",
                it.response or "（无输出）",
                "````",
                "",
            ]

        lines += ["### 1.4 证据", ""]
        lines += [f"- {_dump(e)}" for e in state.get("evidence", [])]
        lines.append("")

        lines += ["### 1.5 数据质量问题与评估", ""]
        issues = state.get("data_quality_issues", []) or []
        lines += [f"- {issue}" for issue in issues] if issues else ["- 无"]
        lines.append("")
        evaluation = state.get("evaluation")
        if evaluation is not None:
            lines += [f"评估：{_dump(evaluation)}", ""]
        repair_actions = state.get("repair_actions", []) or []
        if repair_actions:
            lines += [f"- 修复动作: {action}" for action in repair_actions]
            lines += [f"- 修复迭代: {state.get('iteration', 0)}", ""]

        lines += ["## 2. 最终报告", ""]
        if report is not None:
            lines.append(render_markdown(report))
        else:
            lines.append("（未生成报告——运行失败或流程未到达 Synthesizer，见上文错误与日志）")
        lines.append("")

        lines += ["## 3. Trace", "", f"- Trace ID: {trace.request_id}"]
        langfuse = find_langfuse_sink(sink)
        if langfuse is not None:
            url = langfuse.trace_url(trace.request_id)
            lines.append(f"- Langfuse: {url or '已写入（URL 不可用）'}")
        trace_file_sink = find_jsonl_sink(sink)
        if trace_file_sink is not None:
            lines.append(f"- 本地 Trace 文件: {trace_file_sink.path}")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception as e:  # noqa: BLE001 —— 输出落盘失败不影响主流程
        logger.error("write run output failed: %s", e)
        return None


def _print_console(result: dict, output_path: Path | None, log_path: Path) -> None:
    """精简终端：只打印最终报告与文件路径（完整分析过程在运行记录文件中）。"""
    report = coerce_model(result.get("report"), Report)
    print()
    if report is not None:
        print(render_markdown(report))
    else:
        print("（未生成报告）")
    print()
    print(f"运行记录: {output_path if output_path else '写入失败（见日志）'}")
    print(f"日志文件: {log_path}")


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or "测试"
    request_id = uuid.uuid4().hex
    log_path = _setup_logging(request_id)
    logger.info("received query: %r", user_query)

    tracer = RunTracer()
    graph = build_graph(tracer=tracer)
    sink = make_default_trace_sink()

    state = {
        "request_id": request_id,
        "user_query": user_query,
    }

    # live tracing：span 在节点真实执行时创建/关闭（时间戳、顺序、时长即真实值）
    tracer.set_live_sink(find_live_sink(sink))
    tracer.begin_run(state["request_id"], user_query)

    try:
        try:
            result = graph.invoke(state)
        except Exception as exc:  # noqa: BLE001 —— 失败运行也保留 Trace 与运行记录后继续抛出
            run_error = f"{type(exc).__name__}: {exc}"
            logger.error("run failed: %s", run_error)
            failed_state = tracer.last_state or state
            trace = _write_trace(tracer, failed_state, sink, error=run_error)
            output_path = _write_run_output(failed_state, trace, sink, error=run_error)
            print(f"运行失败: {run_error}")
            print(f"运行记录: {output_path if output_path else '写入失败'}")
            print(f"日志文件: {log_path}")
            raise
        trace = _write_trace(tracer, result, sink)
        output_path = _write_run_output(result, trace, sink)
        _print_console(result, output_path, log_path)
    finally:
        _shutdown_sink(sink)


if __name__ == "__main__":
    main()
