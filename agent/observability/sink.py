"""TraceSink 协议与降级 / 组合实现。"""

import logging
from typing import Callable, Protocol

from observability.models import NodeChild, NodeTrace, RunTrace

logger = logging.getLogger(__name__)


class TraceSink(Protocol):
    """Trace 持久化目标（Langfuse / 本地 JSONL / 测试用内存实现）。"""

    def write(self, trace: RunTrace) -> None: ...


class LiveTraceSink(TraceSink, Protocol):
    """支持 live tracing 的 Sink：节点真实执行时创建/关闭 span（如 LangfuseTraceSink）。

    约定：begin_node/end_node 按节点名一一对应（并行分支安全；同节点同名并行不支持），
    方法失败可抛出，由 RunTracer 捕获并降级为一次性写入。
    """

    def begin_run(self, request_id: str, user_query: str) -> None: ...

    def begin_node(self, name: str) -> None: ...

    def end_node(
        self, name: str, node_trace: NodeTrace, children: list[NodeChild] | None = None
    ) -> None: ...


class NullTraceSink:
    """未配置可观测平台时的降级实现：仅记录日志，不影响功能。"""

    def write(self, trace: RunTrace) -> None:
        logger.info(
            "trace sink disabled; run request_id=%s not persisted (%d nodes)",
            trace.request_id,
            len(trace.nodes),
        )

    def shutdown(self) -> None:
        pass


class MultiTraceSink:
    """把 Trace 扇出到多个 Sink（如 Langfuse + 本地 JSONL）；单个失败不影响其余。"""

    def __init__(self, sinks: list[TraceSink]) -> None:
        self._sinks = list(sinks)

    def write(self, trace: RunTrace) -> None:
        for sink in self._sinks:
            try:
                sink.write(trace)
            except Exception as e:  # noqa: BLE001 —— 单个 Sink 故障隔离
                logger.error("trace sink %s failed: %s", type(sink).__name__, e)

    def shutdown(self) -> None:
        for sink in self._sinks:
            shutdown = getattr(sink, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception as e:  # noqa: BLE001
                    logger.warning("trace sink %s shutdown failed: %s", type(sink).__name__, e)

    @property
    def sinks(self) -> list[TraceSink]:
        return list(self._sinks)


def find_sink(sink, predicate: Callable[[object], bool]):
    """在（可能组合的）Sink 树中查找满足条件的 Sink（MultiTraceSink 展开 `sinks` 属性）。"""
    if predicate(sink):
        return sink
    for candidate in getattr(sink, "sinks", []) or []:
        if predicate(candidate):
            return candidate
    return None


def find_live_sink(sink: TraceSink) -> "LiveTraceSink | None":
    """找出支持 live tracing（begin_run/begin_node/end_node）的 Sink。"""
    return find_sink(
        sink,
        lambda s: all(hasattr(s, method) for method in ("begin_run", "begin_node", "end_node")),
    )


__all__ = ["TraceSink", "LiveTraceSink", "NullTraceSink", "MultiTraceSink", "find_sink", "find_live_sink"]
