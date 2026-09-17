"""评测 Runner（Phase 10）。

数据流：Case → 按 Case 档位构图（collector=real|mock 档位，llm=real|fake）
→ graph.invoke → 硬检查（eval.checks）→ CaseResult 汇总。

与 main.py 相同的 Trace 语义：live tracing + sink 写入 + 失败也留 Trace；
Langfuse 配置存在时，把检查结果以 scores 回写到对应 trace（eval_pass /
checks_passed_ratio / claim_coverage_ratio / data_gaps_ok），供失败回溯与趋势对比。
sink 写入 / 打分失败不影响评测主流程（仅记日志）。
"""

import logging
import time
import uuid

from eval.cases import CASES
from eval.checks import run_checks
from eval.fakes import build_fake_llm
from eval.mocks import build_collector
from eval.models import CaseResult, EvalCase, SuiteResult
from graph import build_graph
from llm import make_default_llm
from observability import RunTracer, find_langfuse_sink, find_live_sink
from observability.sink import TraceSink

logger = logging.getLogger(__name__)


def _write_trace(sink: TraceSink | None, tracer: RunTracer, state: dict, error: str | None = None) -> None:
    if sink is None:
        return
    try:
        sink.write(tracer.build(state, error=error))
    except Exception as e:  # noqa: BLE001 —— 可观测性故障不影响评测
        logger.error("eval trace sink write failed: %s", e)


def _score_results(case_result: CaseResult, state: dict) -> dict[str, float | bool]:
    """检查结果 → Langfuse scores（命名与设计文档一致）。"""
    scores: dict[str, float | bool] = {"eval_pass": 1.0 if case_result.passed else 0.0}
    evaluation = state.get("evaluation")
    if evaluation is not None:
        scores["claim_coverage_ratio"] = evaluation.claim_coverage_ratio
    disclosure = next(
        (c for c in case_result.checks if c.name == "data_gaps_disclosed_if_issues"), None
    )
    if disclosure is not None:
        scores["data_gaps_ok"] = 1.0 if disclosure.passed else 0.0
    if case_result.checks:
        scores["checks_passed_ratio"] = round(
            sum(1 for c in case_result.checks if c.passed) / len(case_result.checks), 2
        )
    return scores


def _skip_reason(case: EvalCase, mode: str) -> str | None:
    """模式与档位不匹配时给出跳过原因；匹配返回 None。"""
    offline_llm = case.llm.startswith("fake")
    if mode == "offline" and not offline_llm:
        return "live 档位 Case（真实 LLM + 真实 collector），offline 模式跳过"
    if mode == "live" and offline_llm:
        return "offline 档位 Case（fake LLM），live 模式跳过"
    return None


def _write_eval_scores(
    sink: TraceSink | None, request_id: str, case_result: CaseResult, state: dict
) -> None:
    """检查结果回写 Langfuse scores；未配置或写入失败仅告警（可观测性降级，不影响评测）。"""
    langfuse = find_langfuse_sink(sink) if sink is not None else None
    if langfuse is None:
        return
    try:
        langfuse.score_run(request_id, _score_results(case_result, state))
    except Exception as e:  # noqa: BLE001
        logger.warning("eval score write failed for %s: %s", case_result.case_id, e)


def run_case(case: EvalCase, *, mode: str, sink: TraceSink | None = None) -> CaseResult:
    """执行单个 Case；跳过 / 运行失败 / 检查失败都不会抛出，统一落到 CaseResult。"""
    skip = _skip_reason(case, mode)
    if skip:
        return CaseResult(case_id=case.id, skipped=True, skip_reason=skip)

    llm = None
    if case.llm == "real":
        llm = make_default_llm()
        if llm is None:
            return CaseResult(
                case_id=case.id,
                skipped=True,
                skip_reason="LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 未配置，无法执行 real 档位",
            )
    else:
        llm = build_fake_llm(case.llm)

    client = build_collector(case.collector)
    request_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
    tracer = RunTracer()
    graph = build_graph(client=client, llm=llm, tracer=tracer)
    state = {"request_id": request_id, "user_query": case.query}

    # 与 main.py 相同的 live tracing 装配（无 live sink 时 begin_run 安全 no-op）
    if sink is not None:
        tracer.set_live_sink(find_live_sink(sink))
    tracer.begin_run(request_id, case.query)

    started = time.monotonic()
    try:
        try:
            result = graph.invoke(state)
        except Exception as exc:  # noqa: BLE001 —— 失败运行留 Trace 后落到 CaseResult
            run_error = f"{type(exc).__name__}: {exc}"
            logger.error("eval case %s run failed: %s", case.id, run_error)
            _write_trace(sink, tracer, tracer.last_state or state, error=run_error)
            return CaseResult(
                case_id=case.id,
                passed=False,
                error=run_error,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                request_id=request_id,
            )

        _write_trace(sink, tracer, result)
        check_results = run_checks(result, case)
        case_result = CaseResult(
            case_id=case.id,
            passed=all(c.passed for c in check_results),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            request_id=request_id,
            checks=check_results,
        )
        _write_eval_scores(sink, request_id, case_result, result)
        return case_result
    finally:
        client.close()


def run_suite(
    mode: str = "offline",
    *,
    tag: str | None = None,
    case_id: str | None = None,
    cases: list[EvalCase] | None = None,
    sink: TraceSink | None = None,
) -> SuiteResult:
    """执行一组 Case（全部默认）；tag / case_id 用于过滤。"""
    selected = cases or CASES
    if tag:
        selected = [c for c in selected if tag in c.tags]
    if case_id:
        selected = [c for c in selected if c.id == case_id]
        if not selected:
            raise ValueError(f"找不到 Case：{case_id!r}")

    results = [run_case(c, mode=mode, sink=sink) for c in selected]
    return SuiteResult(mode=mode, results=results)


__all__ = ["run_case", "run_suite"]
