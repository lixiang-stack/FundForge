"""Langfuse TraceSink（Phase 9 真实接入，langfuse v4 SDK）。

映射关系：
- 一次运行 → 一个 Langfuse trace（trace_id 由 request_id 派生，可回溯）
- 每个节点 → 一个 span（业务摘要 + 耗时；失败节点带 error）
- Tool 调用 → event，嵌套在 collector span 内（无 collector 时根级 + parent_node 元数据）
- LLM 调用 → generation，嵌套在其归属节点 span 内（如 thesis-llm 挂在 thesis 下）
- Evaluation → trace 级 scores（status / score / coverage / critical）
- 最终 Report 元数据 / 运行错误 → 根 span 输出（v4 中根 observation 的 IO 即 trace 级 IO；
  `set_current_trace_io` 已弃用，不再使用）

未配置 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 时，
make_default_trace_sink 返回 NullTraceSink（不影响功能）。
"""

import logging
from typing import Any

from langfuse import Langfuse

from config import langfuse_host, langfuse_public_key, langfuse_secret_key, trace_file_path
from domain.evidence import ToolCallRecord
from observability.file_sink import JsonlTraceSink
from observability.models import GenerationTrace, NodeChild, NodeTrace, RunTrace
from observability.sink import MultiTraceSink, NullTraceSink, TraceSink, find_sink

logger = logging.getLogger(__name__)


class LangfuseTraceSink:
    """把 RunTrace 写入 Langfuse（client 可注入以便单测，不触网）。

    支持两种模式：
    - **live tracing**（推荐）：`begin_run` / `begin_node` / `end_node` 在节点真实执行时
      创建/关闭 span —— 时间戳、顺序与时长均为真实值；`write` 仅收尾（scores/IO/flush）。
    - **一次性写入**：直接 `write(trace)`（测试或未启用 live 时），span 时间戳为写入时刻。
    """

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str,
        client: Any | None = None,
    ) -> None:
        self._client = client or Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        self._root_cm: Any | None = None
        # 按节点名索引（并行分支安全；同节点同名并行不支持）
        self._node_cms: dict[str, Any] = {}
        self._live = False
        self._live_tools = 0
        self._live_generations = 0
        self._trace_id: str | None = None
        self._root_span_id: str | None = None

    def _reset_live_state(self) -> None:
        """清空 live 状态（begin/enter 失败或收尾后调用，避免孤儿 context 泄漏）。"""
        self._root_cm = None
        self._node_cms.clear()
        self._trace_id = None
        self._root_span_id = None
        self._live = False
        self._live_tools = 0
        self._live_generations = 0

    # ---- live tracing ----

    def begin_run(self, request_id: str, user_query: str) -> None:
        """开启运行根 span（真实开始时间）；失败时清理状态后原样抛出（调用方降级）。"""
        trace_id = self._client.create_trace_id(seed=request_id)
        root_cm = self._client.start_as_current_observation(
            name="fundforge-run",
            as_type="chain",
            trace_context={"trace_id": trace_id},
            input={"user_query": user_query},
            metadata={"request_id": request_id},
        )
        try:
            root_span = root_cm.__enter__()
        except Exception:
            self._reset_live_state()
            raise
        # 记录根 span 身份：节点可能在线程池中执行，需显式指定父 span（OTEL 上下文为线程本地）
        self._root_cm = root_cm
        self._trace_id = getattr(root_span, "trace_id", trace_id)
        self._root_span_id = getattr(root_span, "id", None)
        self._live = True

    def begin_node(self, name: str) -> None:
        """开启节点 span（真实开始时间；显式挂到根 span 下以跨线程保序）。"""
        trace_context = None
        if self._trace_id and self._root_span_id:
            trace_context = {"trace_id": self._trace_id, "parent_span_id": self._root_span_id}
        cm = self._client.start_as_current_observation(
            name=name, as_type="span", trace_context=trace_context
        )
        cm.__enter__()  # 失败则不入栈（未进入的 context 无需退出），由调用方降级
        self._node_cms[name] = cm

    def end_node(
        self, name: str, node_trace: NodeTrace, children: list[NodeChild] | None = None
    ) -> None:
        """在节点 span 内写入子元素（tool/generation）与 IO，然后关闭（真实结束时间）。"""
        for child in children or []:
            if child["kind"] == "tool":
                self._write_tool_call(child["call"])
                self._live_tools += 1
            elif child["kind"] == "generation":
                self._write_generation(child["generation"])
                self._live_generations += 1
        self._client.update_current_span(
            input={"input_keys": node_trace.input_keys},
            output={"output_keys": node_trace.output_keys, "summary": node_trace.output_summary},
            metadata={"duration_ms": node_trace.duration_ms, "error": node_trace.error},
            level="ERROR" if node_trace.error else None,
        )
        cm = self._node_cms.pop(name, None)
        if cm is not None:
            cm.__exit__(None, None, None)

    # ---- 写入 / 收尾 ----

    def write(self, trace: RunTrace) -> None:
        if self._live and self._root_cm is not None:
            self._finish_live_run(trace)
        else:
            self._write_all_at_once(trace)

    def _finish_live_run(self, trace: RunTrace) -> None:
        """live 模式收尾：补写未在 live 中输出的子元素，写 scores/IO，关闭根 span。"""
        for call in trace.tool_calls[self._live_tools:]:
            self._write_tool_call(call, parent_node="collector")
        for generation in trace.generations[self._live_generations:]:
            self._write_generation(generation, parent_node=generation.node)
        self._write_unattributed_llm_note(trace)
        self._write_scores(trace)
        self._client.update_current_span(
            output={
                "evaluation_status": trace.evaluation.status.value if trace.evaluation else None,
                "report_metadata": (
                    trace.report_metadata.model_dump(mode="json") if trace.report_metadata else None
                ),
                "error": trace.error,
            },
            metadata={"unattributed_llm_calls": self._unattributed_llm_calls(trace)},
        )
        # 节点中途 live 失败时 end_node 未被调用，此处兜底关闭，避免 span 悬挂
        for name in list(self._node_cms):
            leftover = self._node_cms.pop(name)
            try:
                leftover.__exit__(None, None, None)
            except Exception as e:  # noqa: BLE001 —— 收尾尽力而为
                logger.warning("closing leftover node span %s failed: %s", name, e)
        self._root_cm.__exit__(None, None, None)
        self._reset_live_state()
        self._flush_client()

    def _write_all_at_once(self, trace: RunTrace) -> None:
        trace_id = self._client.create_trace_id(seed=trace.request_id)
        with self._client.start_as_current_observation(
            name="fundforge-run",
            as_type="chain",
            trace_context={"trace_id": trace_id},
            input={"user_query": trace.user_query},
            metadata={
                "request_id": trace.request_id,
                "error": trace.error,
                "unattributed_llm_calls": self._unattributed_llm_calls(trace),
            },
        ):
            self._write_nodes(trace)
            self._write_unattributed_llm_note(trace)
            self._write_scores(trace)
            # trace 级 IO 由根 span 承载（set_current_trace_io 已弃用，v4 用根 observation 的 IO）
            self._client.update_current_span(
                output={
                    "evaluation_status": trace.evaluation.status.value if trace.evaluation else None,
                    "report_metadata": (
                        trace.report_metadata.model_dump(mode="json") if trace.report_metadata else None
                    ),
                    "error": trace.error,
                }
            )
        self._flush_client()

    @staticmethod
    def _unattributed_llm_calls(trace: RunTrace) -> int:
        """未登记 generation 的 LLM 调用数（未来新增 LLM 调用未接入 tracer 时的提示信号）。"""
        return max(trace.token_usage.llm_calls - sum(g.calls for g in trace.generations), 0)

    def _write_nodes(self, trace: RunTrace) -> None:
        """节点 span；tool 事件与 LLM generation 嵌套在各自归属节点 span 内。"""
        tools_written = False
        generations_written: set[int] = set()
        for node in trace.nodes:
            with self._client.start_as_current_observation(
                name=node.node,
                as_type="span",
                input={"input_keys": node.input_keys},
                output={"output_keys": node.output_keys, "summary": node.output_summary},
                metadata={"duration_ms": node.duration_ms, "error": node.error},
                level="ERROR" if node.error else None,
            ):
                if node.node == "collector" and trace.tool_calls:
                    for call in trace.tool_calls:
                        self._write_tool_call(call)
                    tools_written = True
                for index, generation in enumerate(trace.generations):
                    if generation.node == node.node:
                        self._write_generation(generation)
                        generations_written.add(index)
        # 无归属节点 span（如短路/失败早退）时退化为根级，并标注归属
        if trace.tool_calls and not tools_written:
            for call in trace.tool_calls:
                self._write_tool_call(call, parent_node="collector")
        for index, generation in enumerate(trace.generations):
            if index not in generations_written:
                self._write_generation(generation, parent_node=generation.node)

    def _write_tool_call(self, call: ToolCallRecord, parent_node: str | None = None) -> None:
        self._client.create_event(
            name=f"tool:{call.tool_name}",
            input=call.arguments,
            metadata={
                "success": call.success,
                "error": call.error,
                "started_at": call.started_at.isoformat(),
                "finished_at": call.finished_at.isoformat(),
                "parent_node": parent_node,
            },
        )

    def _write_generation(self, generation: GenerationTrace, parent_node: str | None = None) -> None:
        metadata = {"parent_node": parent_node} if parent_node else None
        with self._client.start_as_current_observation(
            name=generation.name,
            as_type="generation",
            model=generation.model,
            input=generation.input_summary,
            output=generation.output_summary,
            metadata=metadata,
            usage_details={
                "input": generation.input_tokens,
                "output": generation.output_tokens,
            },
        ):
            pass

    def _write_unattributed_llm_note(self, trace: RunTrace) -> None:
        unattributed = self._unattributed_llm_calls(trace)
        if unattributed > 0:
            # 未来新增 LLM 调用但未登记 generation 时的显式提示
            with self._client.start_as_current_observation(
                name="llm-calls-unattributed",
                as_type="generation",
                metadata={"unattributed_calls": unattributed},
            ):
                pass

    def _flush_client(self) -> None:
        """flush 有界性：SDK 内部各路径均受 LANGFUSE_TIMEOUT（默认 5s）约束
        （OTLP 导出带硬 deadline；score/media 消费者重试上界 3 次），
        最坏 ~30s 后必然返回，无需在 sink 层再包超时。"""
        self._client.flush()

    def _write_scores(self, trace: RunTrace) -> None:
        evaluation = trace.evaluation
        if evaluation is None:
            return
        self._client.score_current_trace(
            name="evaluation_status", value=evaluation.status.value, data_type="CATEGORICAL"
        )
        self._client.score_current_trace(
            name="overall_score", value=evaluation.overall_score, data_type="NUMERIC"
        )
        self._client.score_current_trace(
            name="claim_coverage_ratio", value=evaluation.claim_coverage_ratio, data_type="NUMERIC"
        )
        self._client.score_current_trace(
            name="critical", value=evaluation.critical, data_type="BOOLEAN"
        )

    def trace_url(self, request_id: str) -> str | None:
        """按 request_id 回溯的 Langfuse 页面地址。"""
        return self._client.get_trace_url(
            trace_id=self._client.create_trace_id(seed=request_id)
        )

    def score_run(self, request_id: str, scores: dict[str, float | bool]) -> None:
        """评测集打分（Phase 10）：按 request_id 派生 trace_id 显式提交，不依赖 live 上下文。

        单条打分失败仅告警（可观测性降级设计），不中断评测主流程。
        """
        trace_id = self._client.create_trace_id(seed=request_id)
        for name, value in scores.items():
            try:
                if isinstance(value, bool):
                    self._client.create_score(
                        trace_id=trace_id, name=name, value=value, data_type="BOOLEAN"
                    )
                else:
                    self._client.create_score(
                        trace_id=trace_id, name=name, value=float(value), data_type="NUMERIC"
                    )
            except Exception as e:  # noqa: BLE001 —— 打分失败不影响评测
                logger.warning("eval score %s=%s write failed: %s", name, value, e)

    def shutdown(self) -> None:
        self._client.shutdown()


def make_default_trace_sink() -> TraceSink:
    """按环境变量构建 TraceSink。

    - LANGFUSE_* 配置齐全 → LangfuseTraceSink
    - TRACE_FILE 配置 → JsonlTraceSink（本地 JSONL，离线分析）
    - 两者都配置 → MultiTraceSink 扇出
    - 都未配置 → NullTraceSink（不影响功能）
    """
    sinks: list[TraceSink] = []

    host, public_key, secret_key = langfuse_host(), langfuse_public_key(), langfuse_secret_key()
    if host and public_key and secret_key:
        try:
            sinks.append(LangfuseTraceSink(public_key, secret_key, host))
        except Exception as e:  # noqa: BLE001 —— 可观测性故障不影响业务，降级为仅本地 Sink
            logger.warning("langfuse sink init failed, disabled: %s", e)
    elif any((host, public_key, secret_key)):
        missing = [
            name
            for name, value in (
                ("LANGFUSE_HOST", host),
                ("LANGFUSE_PUBLIC_KEY", public_key),
                ("LANGFUSE_SECRET_KEY", secret_key),
            )
            if not value
        ]
        logger.warning("langfuse partially configured, disabled; missing: %s", ", ".join(missing))

    trace_file = trace_file_path()
    if trace_file:
        sinks.append(JsonlTraceSink(trace_file))

    if not sinks:
        logger.warning(
            "no trace sink configured (LANGFUSE_* / TRACE_FILE), tracing disabled"
        )
        return NullTraceSink()
    if len(sinks) == 1:
        return sinks[0]
    return MultiTraceSink(sinks)


def find_langfuse_sink(sink: TraceSink) -> "LangfuseTraceSink | None":
    """从（可能组合的）Sink 中找出 Langfuse Sink，用于输出回溯链接。"""
    return find_sink(sink, lambda s: isinstance(s, LangfuseTraceSink))


__all__ = ["LangfuseTraceSink", "make_default_trace_sink", "find_langfuse_sink"]
