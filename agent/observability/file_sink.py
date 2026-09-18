"""本地 JSONL 文件 Sink（离线分析用）。

每次运行追加一行 JSON（RunTrace.model_dump_json），可直接用 jq / pandas 分析：

    uv run python main.py "分析基金 519770"
    jq -r '.nodes[] | [.node, .duration_ms] | @tsv' output/runs.jsonl

默认写入 agent/output/runs.jsonl（与运行记录同目录，均不入库），
与 Langfuse Sink 可同时启用（MultiTraceSink 扇出）。
"""

import logging
from pathlib import Path

from observability.models import RunTrace
from observability.sink import find_sink

logger = logging.getLogger(__name__)

# 本地 Trace 默认落点：agent/output/（运行记录同目录，.gitignore 已覆盖）
DEFAULT_TRACE_FILE = Path(__file__).resolve().parent.parent / "output" / "runs.jsonl"


class JsonlTraceSink:
    """把 RunTrace 追加写入 JSONL 文件（每行一次运行）。"""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, trace: RunTrace) -> None:
        line = trace.model_dump_json()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        logger.info("trace appended to %s (request_id=%s)", self._path, trace.request_id)

    @property
    def path(self) -> Path:
        return self._path

    def shutdown(self) -> None:
        """无缓冲资源，占位以统一 Sink 生命周期。"""


def find_jsonl_sink(sink) -> "JsonlTraceSink | None":
    """从（可能组合的）Sink 中找出本地 JSONL Sink。"""
    return find_sink(sink, lambda s: isinstance(s, JsonlTraceSink))


__all__ = ["JsonlTraceSink", "find_jsonl_sink", "DEFAULT_TRACE_FILE"]
