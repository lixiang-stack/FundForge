"""可观测性测试（Phase 9）：RunTracer / RunTrace / TraceSink / Langfuse 映射。

Langfuse 用 Fake client 注入（含 observation 上下文栈），不触网、不需要真实 key。
"""

from datetime import datetime

import pytest

from domain.evaluation import EvaluationResult, EvaluationStatus
from domain.evidence import ToolCallRecord, TokenUsage
from observability import NullTraceSink, RunTracer
from observability.langfuse_sink import LangfuseTraceSink, make_default_trace_sink
from observability.models import GenerationTrace, NodeTrace, RunTrace


class _FakeSpanRef:
    def __init__(self, span_id: str, trace_id: str) -> None:
        self.id = span_id
        self.trace_id = trace_id


class _FakeObservationCtx:
    def __init__(self, client: "FakeLangfuseClient", kwargs: dict) -> None:
        self._client = client
        self._kwargs = kwargs
        self._index: int | None = None

    def __enter__(self):
        stack = self._client.stack
        parent = stack[-1] if stack else None
        stack.append(self._kwargs["name"])
        self._index = len(stack) - 1
        self._client.observations.append({**self._kwargs, "parent": parent})
        return _FakeSpanRef(f"span-{len(self._client.observations)}", self._client.trace_id)

    def __exit__(self, *exc):
        # OTEL 按 token 出栈：退出时移除自己的入栈项（下方元素移除会导致下标偏移，
        # 故从栈顶向下按名字查找；同节点同名并行本就不支持，末次出现即自己）
        stack = self._client.stack
        for index in range(len(stack) - 1, -1, -1):
            if stack[index] == self._kwargs["name"]:
                stack.pop(index)
                break
        return False


class FakeLangfuseClient:
    """记录调用的假 Langfuse client（含 observation 嵌套上下文）。"""

    def __init__(self) -> None:
        self.trace_id = "trace-fake"
        self.stack: list[str] = []
        self.trace_seeds: list[str | None] = []
        self.observations: list[dict] = []
        self.events: list[dict] = []
        self.scores: list[dict] = []
        self.span_updates: list[dict] = []
        self.flushed = 0

    def create_trace_id(self, seed=None):
        self.trace_seeds.append(seed)
        return "trace-" + (seed or "x")

    def start_as_current_observation(self, **kwargs):
        return _FakeObservationCtx(self, kwargs)

    def create_event(self, **kwargs):
        self.events.append({**kwargs, "parent": self.stack[-1] if self.stack else None})

    def score_current_trace(self, **kwargs):
        self.scores.append(kwargs)

    def update_current_span(self, **kwargs):
        self.span_updates.append({**kwargs, "span": self.stack[-1] if self.stack else None})

    def get_trace_url(self, trace_id=None):
        return f"https://langfuse.test/trace/{trace_id}"

    def flush(self):
        self.flushed += 1

    def shutdown(self):
        pass


def _run_trace(generations: list[GenerationTrace] | None = None, llm_calls: int = 1) -> RunTrace:
    return RunTrace(
        request_id="req123",
        user_query="分析基金 519770",
        started_at=datetime(2026, 9, 14, 10, 0, 0),
        finished_at=datetime(2026, 9, 14, 10, 0, 5),
        nodes=[
            NodeTrace(
                node="router",
                started_at=datetime(2026, 9, 14, 10, 0, 0),
                finished_at=datetime(2026, 9, 14, 10, 0, 1),
                duration_ms=1000.0,
                input_keys=["user_query"],
                output_keys=["task_type"],
                output_summary={"task_type": "fund_research"},
            ),
            NodeTrace(
                node="collector",
                started_at=datetime(2026, 9, 14, 10, 0, 1),
                finished_at=datetime(2026, 9, 14, 10, 0, 3),
                duration_ms=2000.0,
                output_summary={"funds_collected": 1},
            ),
            NodeTrace(
                node="thesis",
                started_at=datetime(2026, 9, 14, 10, 0, 3),
                finished_at=datetime(2026, 9, 14, 10, 0, 4),
                duration_ms=1000.0,
                output_summary={"claims": 2},
            ),
        ],
        tool_calls=[
            ToolCallRecord(
                tool_name="get_fund_info",
                arguments={"fund_id": "519770"},
                started_at=datetime(2026, 9, 14, 10, 0, 1),
                finished_at=datetime(2026, 9, 14, 10, 0, 2),
                success=True,
            )
        ],
        generations=generations
        if generations is not None
        else [
            GenerationTrace(
                name="thesis-llm",
                model="deepseek-v4-flash",
                input_tokens=100,
                output_tokens=50,
                input_summary={"funds": 1, "evidence": 3},
                output_summary={"claims": 2, "confidence": 0.6},
            )
        ],
        token_usage=TokenUsage(input_tokens=100, output_tokens=50, llm_calls=llm_calls),
        llm_model="deepseek-v4-flash",
        evaluation=EvaluationResult(
            status=EvaluationStatus.PASS,
            overall_score=1.0,
            claim_coverage_ratio=1.0,
        ),
    )


class TestRunTracer:
    def test_wrap_records_node_trace(self):
        tracer = RunTracer()
        wrapped = tracer.wrap("router", lambda s: {"task_type": "fund_research", "evidence": [1, 2, 3]})
        wrapped({"user_query": "q"})

        trace = tracer.build({"request_id": "r1", "user_query": "q"})
        node_trace = trace.nodes[0]
        assert node_trace.node == "router"
        assert node_trace.input_keys == ["user_query"]
        assert node_trace.output_keys == ["evidence", "task_type"]
        # router 有业务摘要器：task_type / rule_hit
        assert node_trace.output_summary["task_type"] == "fund_research"

    def test_business_summary_for_collector(self):
        tracer = RunTracer()
        state = {
            "funds_summary": [{"id": "519770", "data_quality": "complete"}],
            "fund_ids": ["519770"],
            "evidence": [1, 2, 3],
            "tool_calls": [ToolCallRecord(
                tool_name="t", arguments={}, started_at=datetime(2026, 1, 1),
                finished_at=datetime(2026, 1, 1), success=True,
            )],
            "data_quality_issues": ["issue"],
        }
        tracer.wrap("collector", lambda s: {
            "fund_ids": ["519770"],
            "funds_summary": _summary_models(),
            "evidence": [1, 2, 3],
            "tool_calls": state["tool_calls"],
            "data_quality_issues": ["issue"],
        })(state)
        summary = tracer.build({"request_id": "r", "user_query": "q"}).nodes[0].output_summary
        assert summary["fund_ids"] == 1
        assert summary["funds_collected"] == 1
        assert summary["evidence"] == 3
        assert summary["tool_failures"] == 0
        assert summary["data_quality_issues"] == 1

    def test_failed_node_is_recorded_then_reraised(self):
        tracer = RunTracer()

        def boom(state):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            tracer.wrap("analyzer", boom)({"request_id": "r"})

        trace = tracer.build(tracer.last_state or {}, error="ValueError: boom")
        assert len(trace.nodes) == 1
        assert trace.nodes[0].node == "analyzer"
        assert "ValueError: boom" in trace.nodes[0].error
        assert trace.error == "ValueError: boom"

    def test_generation_carries_input_output_summary(self):
        tracer = RunTracer()
        tracer.llm_model = "test-model"
        state = {
            "request_id": "r2",
            "user_query": "q",
            "funds_summary": [{"id": "519770"}],
            "evidence": [1, 2, 3],
            "token_usage": {"input_tokens": 10, "output_tokens": 5, "llm_calls": 1},
            "investment_thesis": {
                "summary": "s",
                "claims": [{"id": "c1", "statement": "x", "claim_type": "risk",
                            "evidence_ids": ["ev-1"], "strength": "weak"}],
                "suitability": "适合长期持有",
                "confidence": 0.6,
            },
        }
        trace = tracer.build(state)
        assert len(trace.generations) == 1
        generation = trace.generations[0]
        assert generation.name == "thesis-llm"
        assert generation.model == "test-model"
        assert generation.input_summary["funds"] == 1
        assert generation.input_summary["evidence"] == 3
        assert generation.output_summary["claims"] == 1
        assert generation.output_summary["suitability"] == "适合长期持有"
        assert generation.output_summary["confidence"] == 0.6


def _summary_models():
    from domain.fund import FundSummary

    return [FundSummary(id="519770", name="n", as_of=datetime(2026, 1, 1), data_quality="complete")]


class TestNullSink:
    def test_write_is_noop(self):
        NullTraceSink().write(_run_trace())  # 不抛错即可


class TestLangfuseSink:
    def _sink(self):
        client = FakeLangfuseClient()
        return LangfuseTraceSink("pk", "sk", "https://langfuse.test", client=client), client

    def test_maps_run_trace_to_langfuse(self):
        sink, client = self._sink()
        sink.write(_run_trace())

        assert client.trace_seeds == ["req123"]
        names = {o["name"]: o for o in client.observations}
        assert names["fundforge-run"]["as_type"] == "chain"
        assert names["fundforge-run"]["parent"] is None
        assert names["router"]["parent"] == "fundforge-run"
        # generation 带 input/output 摘要与 token，且嵌套在归属节点 span 内
        generation = names["thesis-llm"]
        assert generation["as_type"] == "generation"
        assert generation["parent"] == "thesis"
        assert generation["input"]["funds"] == 1
        assert generation["output"]["claims"] == 2
        assert generation["usage_details"] == {"input": 100, "output": 50}
        # Tool 事件嵌套在 collector span 内
        assert client.events[0]["name"] == "tool:get_fund_info"
        assert client.events[0]["parent"] == "collector"
        # scores / trace io / flush
        score_names = {s["name"] for s in client.scores}
        assert {"evaluation_status", "overall_score", "claim_coverage_ratio", "critical"} <= score_names
        assert client.flushed == 1
        # trace 级 IO 由根 span 承载（不再使用已弃用的 set_current_trace_io）
        assert client.span_updates[-1]["span"] == "fundforge-run"
        assert "evaluation_status" in client.span_updates[-1]["output"]

    def test_failed_node_marked_error_level(self):
        sink, client = self._sink()
        trace = _run_trace()
        trace.nodes[0].error = "RuntimeError: boom"
        trace.error = "RuntimeError: boom"
        sink.write(trace)

        router = next(o for o in client.observations if o["name"] == "router")
        assert router["level"] == "ERROR"
        assert router["metadata"]["error"] == "RuntimeError: boom"

    def test_unattributed_llm_calls_flagged(self):
        sink, client = self._sink()
        sink.write(_run_trace(llm_calls=2))  # 1 条已登记 generation，另 1 次未归因
        assert any(o["name"] == "llm-calls-unattributed" for o in client.observations)
        root = next(o for o in client.observations if o["name"] == "fundforge-run")
        assert root["metadata"]["unattributed_llm_calls"] == 1

    def test_generation_falls_back_to_root_without_owner_span(self):
        # 归属节点 span 缺失（如早退）时退化为根级 generation 并标注 parent_node
        sink, client = self._sink()
        trace = _run_trace()
        trace.nodes = [n for n in trace.nodes if n.node != "thesis"]
        sink.write(trace)

        generation = next(o for o in client.observations if o["name"] == "thesis-llm")
        assert generation["parent"] == "fundforge-run"
        assert generation["metadata"] == {"parent_node": "thesis"}

    def test_generation_skipped_without_llm_calls(self):
        sink, client = self._sink()
        trace = _run_trace(generations=[], llm_calls=0)
        sink.write(trace)
        assert all(o["as_type"] != "generation" for o in client.observations)

    def test_trace_url_uses_request_id_seed(self):
        sink, _ = self._sink()
        assert sink.trace_url("req123") == "https://langfuse.test/trace/trace-req123"

    def test_default_sink_local_jsonl_when_unconfigured(self, monkeypatch, tmp_path):
        # 本地 JSONL 恒启用：Langfuse 未配置时仅含文件 Sink
        from observability.file_sink import JsonlTraceSink

        for var in ("LANGFUSE_HOST", "LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            monkeypatch.delenv(var, raising=False)
        sink = make_default_trace_sink(trace_file=tmp_path / "runs.jsonl")
        assert isinstance(sink, JsonlTraceSink)

    def test_default_sink_accepts_base_url_alias(self, monkeypatch, tmp_path):
        from observability.langfuse_sink import find_langfuse_sink
        from observability.sink import MultiTraceSink

        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://jp.cloud.langfuse.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        sink = make_default_trace_sink(trace_file=tmp_path / "runs.jsonl")
        assert isinstance(sink, MultiTraceSink)
        assert isinstance(find_langfuse_sink(sink), LangfuseTraceSink)

    def test_default_sink_degrades_when_langfuse_client_fails(self, monkeypatch, tmp_path):
        # Langfuse client 构造失败（如配置被 SDK 拒绝）→ 降级为仅本地 JSONL，不影响业务
        import observability.langfuse_sink as lf
        from observability.file_sink import JsonlTraceSink

        monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setattr(lf, "Langfuse", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bad config")))
        sink = make_default_trace_sink(trace_file=tmp_path / "runs.jsonl")
        assert isinstance(sink, JsonlTraceSink)


class TestTracerInGraph:
    def test_full_flow_traces_all_nodes_with_business_summaries(self):
        from graph import build_graph
        from tests.conftest import FUND_CODE, make_transport
        from tests.test_thesis import DynamicThesisProvider
        from tools.collector_client import CollectorClient

        client = CollectorClient(base_url="http://collector.test", transport=make_transport())
        tracer = RunTracer()
        try:
            graph = build_graph(client=client, llm=DynamicThesisProvider(), tracer=tracer)
            result = graph.invoke({"request_id": "t-trace", "user_query": f"分析基金 {FUND_CODE}"})
        finally:
            client.close()

        trace = tracer.build(result)
        assert [n.node for n in trace.nodes] == [
            "router",
            "planner",
            "collector",
            "analyzer",
            "researcher",
            "thesis",
            "evaluator",
            "synthesizer",
        ]
        by_node = {n.node: n for n in trace.nodes}
        assert by_node["collector"].output_summary["funds_collected"] == 1
        assert by_node["collector"].output_summary["evidence"] == 9
        assert by_node["analyzer"].output_summary["analysis_present"] is True
        assert by_node["thesis"].output_summary["claims"] == 1
        assert by_node["evaluator"].output_summary["status"] == "pass"
        assert by_node["evaluator"].output_summary["claim_coverage_ratio"] == 1.0
        assert len(trace.generations) == 1
        assert trace.generations[0].output_summary["claims"] == 1
        assert trace.report_metadata is not None


class TestJsonlSink:
    def test_appends_one_json_line_per_run(self, tmp_path):
        import json

        from observability import JsonlTraceSink

        path = tmp_path / "nested" / "runs.jsonl"
        sink = JsonlTraceSink(str(path))
        sink.write(_run_trace())
        sink.write(_run_trace())

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert record["request_id"] == "req123"
        assert len(record["nodes"]) == 3
        assert record["generations"][0]["name"] == "thesis-llm"
        assert record["evaluation"]["status"] == "pass"

    def test_creates_parent_directory(self, tmp_path):
        from observability import JsonlTraceSink

        path = tmp_path / "deep" / "dir" / "trace.jsonl"
        JsonlTraceSink(str(path)).write(_run_trace())
        assert path.exists()


class TestMultiSink:
    def test_fans_out_and_isolates_failures(self, tmp_path):
        from observability import JsonlTraceSink, MultiTraceSink

        class BoomSink:
            def write(self, trace):
                raise RuntimeError("boom")

            def shutdown(self):
                raise RuntimeError("boom")

        path = tmp_path / "runs.jsonl"
        sink = MultiTraceSink([BoomSink(), JsonlTraceSink(str(path))])
        sink.write(_run_trace())  # BoomSink 失败不影响 JsonlTraceSink
        sink.shutdown()
        assert path.read_text(encoding="utf-8").strip()

    def test_default_sink_combines_langfuse_and_file(self, monkeypatch, tmp_path):
        from observability import JsonlTraceSink, LangfuseTraceSink, MultiTraceSink, find_jsonl_sink, find_langfuse_sink

        monkeypatch.setenv("LANGFUSE_HOST", "https://jp.cloud.langfuse.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

        sink = make_default_trace_sink(trace_file=tmp_path / "runs.jsonl")
        assert isinstance(sink, MultiTraceSink)
        assert isinstance(find_langfuse_sink(sink), LangfuseTraceSink)
        assert isinstance(find_jsonl_sink(sink), JsonlTraceSink)


class TestLangfuseLiveMode:
    """live tracing：span 在真实执行时创建/关闭（顺序与时间戳即真实执行顺序）。"""

    def _sink(self):
        client = FakeLangfuseClient()
        return LangfuseTraceSink("pk", "sk", "https://langfuse.test", client=client), client

    def _node_trace(self, name: str) -> NodeTrace:
        return NodeTrace(
            node=name,
            started_at=datetime(2026, 9, 15, 10, 0, 0),
            finished_at=datetime(2026, 9, 15, 10, 0, 1),
            duration_ms=1000.0,
            output_keys=["x"],
            output_summary={"x": 1},
        )

    def test_begin_run_enter_failure_resets_state_and_falls_back_to_one_shot(self):
        client = FakeLangfuseClient()
        original = client.start_as_current_observation

        class BrokenCtx:
            def __enter__(self):
                raise RuntimeError("enter failed")

            def __exit__(self, *exc):
                return False

        client.start_as_current_observation = lambda **kwargs: BrokenCtx()
        sink = LangfuseTraceSink("pk", "sk", "https://langfuse.test", client=client)

        with pytest.raises(RuntimeError):
            sink.begin_run("req1", "q")
        # 失败后 live 状态必须复位，后续一次性写入不残留孤儿 context
        assert sink._live is False
        assert sink._root_cm is None
        assert client.stack == []

        client.start_as_current_observation = original
        sink.write(_run_trace())  # 降级为一次性写入，业务可继续
        names = [o["name"] for o in client.observations]
        assert names.count("fundforge-run") == 1
        assert client.flushed == 1

    def test_end_node_closes_own_span_not_last_begun(self):
        # begin A、begin B、end A：按名索引应关闭 A 的 span（LIFO 栈会错关 B）
        sink, client = self._sink()
        sink.begin_run("req1", "q")
        sink.begin_node("a")
        sink.begin_node("b")
        sink.end_node("a", self._node_trace("a"))
        assert client.stack == ["fundforge-run", "b"]

    def test_leftover_node_spans_closed_on_finish(self):
        # 中途 live 失败导致 end_node 缺席时，收尾兜底关闭遗留 span
        sink, client = self._sink()
        sink.begin_run("req1", "q")
        sink.begin_node("router")
        sink._node_cms["collector"] = client.start_as_current_observation(name="collector", as_type="span")
        sink._node_cms["collector"].__enter__()
        sink.write(_run_trace())
        assert client.stack == []

    def test_live_spans_follow_execution_order(self):
        sink, client = self._sink()
        tool_call = _run_trace().tool_calls[0]

        sink.begin_run("req1", "q")
        for name in ("router", "collector"):
            sink.begin_node(name)
            children = [{"kind": "tool", "call": tool_call}] if name == "collector" else []
            sink.end_node(name, self._node_trace(name), children)
        trace = _run_trace()
        sink.write(trace)

        names = [o["name"] for o in client.observations]
        # live 期间按真实执行顺序创建；收尾补写未 live 输出的 generation
        assert names[:3] == ["fundforge-run", "router", "collector"]
        assert names[-1] == "thesis-llm"
        # tool 事件在 collector span 打开期间写入（归属正确，无重复）
        assert [e["name"] for e in client.events] == ["tool:get_fund_info"]
        assert client.events[0]["parent"] == "collector"
        # 节点 span 显式挂到根 span 下（跨线程保序）
        root_obs = next(o for o in client.observations if o["name"] == "fundforge-run")
        node_obs = [o for o in client.observations if o["name"] in ("router", "collector")]
        root_span_id = f"span-1"
        assert all(
            (o.get("trace_context") or {}).get("parent_span_id") == root_span_id for o in node_obs
        ), "节点 span 应显式指定根 span 为父"
        # live 收尾：根 span 输出 + scores + flush，且不重复创建节点 span
        assert client.span_updates[-1]["span"] == "fundforge-run"
        assert client.span_updates[-1]["output"]["evaluation_status"] == "pass"
        assert len(client.scores) == 4
        assert client.flushed == 1
        # generation 未在 live 中输出（thesis 未 begin_node）→ 退化为根级补写
        assert any(o["name"] == "thesis-llm" for o in client.observations)

    def test_live_does_not_duplicate_children_emitted_live(self):
        sink, client = self._sink()
        trace = _run_trace()

        sink.begin_run("req1", "q")
        sink.begin_node("collector")
        sink.end_node("collector", self._node_trace("collector"), [{"kind": "tool", "call": trace.tool_calls[0]}])
        sink.begin_node("thesis")
        sink.end_node("thesis", self._node_trace("thesis"), [{"kind": "generation", "generation": trace.generations[0]}])
        sink.write(trace)

        assert len([e for e in client.events if e["name"] == "tool:get_fund_info"]) == 1
        assert len([o for o in client.observations if o["name"] == "thesis-llm"]) == 1
        assert client.observations[-1]["name"] == "thesis-llm"  # 在 thesis span 内
        assert client.observations[-1]["parent"] == "thesis"
