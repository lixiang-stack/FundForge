"""评测硬检查注册表（Phase 10）。

只做「机器可判定」断言（设计原则：80% 精力在硬检查）：
Report 结构、Claim-Evidence 绑定、data_gaps 披露、免责声明、Evaluator 结论、对比披露。
检查口径对齐 Evaluator（覆盖率阈值 / data_gaps 披露 / alignment 关键词），避免两套标准。

检查函数签名统一为 (state, case, params) -> str | None：None = 通过，str = 失败原因。
Case 引用未注册的检查点名 → 判失败（fail fast，防止拼错检查名变成静默通过）。
"""

from typing import Any, Callable

from eval.models import CheckResult, CheckSpec, EvalCase

_MANDATORY_DISCLAIMER = "不构成任何投资建议"


# ---- state 取值助手（graph.invoke 返回值节点产物均为 pydantic 对象） ----

def _thesis(state: dict):
    return state.get("investment_thesis")


def _evaluation(state: dict):
    return state.get("evaluation")


def _report(state: dict):
    return state.get("report")


# ---- 检查点实现 ----

def report_exists(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    if _report(state) is None:
        return "state 中没有 report"
    return None


def has_suitability(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    thesis = _thesis(state)
    if thesis is None:
        return "investment_thesis 缺失，无 suitability"
    if not thesis.suitability.strip():
        return "suitability 为空（未回答「是否适合长期持有」）"
    return None


def min_claims(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    thesis = _thesis(state)
    if thesis is None:
        return "investment_thesis 缺失"
    minimum = int(params.get("min", 1))
    if len(thesis.claims) < minimum:
        return f"claims 数量 {len(thesis.claims)} < {minimum}"
    return None


def all_claims_have_evidence(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """对齐 Evaluator Evidence Coverage：每个 Claim 必须绑定真实存在的 Evidence。"""
    thesis = _thesis(state)
    if thesis is None:
        return "investment_thesis 缺失"
    valid_ids = {e.id for e in state.get("evidence", [])}
    bad = [
        c.id
        for c in thesis.claims
        if not c.evidence_ids or not set(c.evidence_ids) <= valid_ids
    ]
    if bad:
        return f"以下 Claim 未绑定真实 Evidence：{bad}"
    return None


def claim_coverage_min(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    evaluation = _evaluation(state)
    if evaluation is None:
        return "evaluation 缺失"
    threshold = float(params.get("min", 0.5))
    if evaluation.claim_coverage_ratio < threshold:
        return (
            f"claim_coverage_ratio {evaluation.claim_coverage_ratio} < {threshold}"
            "（Evaluator 硬阈值口径）"
        )
    return None


def evaluation_status_in(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    evaluation = _evaluation(state)
    if evaluation is None:
        return "evaluation 缺失"
    allowed = list(params.get("statuses", []))
    if evaluation.status.value not in allowed:
        return f"evaluation.status={evaluation.status.value} 不在允许集合 {allowed}"
    return None


def evaluation_critical_false(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    evaluation = _evaluation(state)
    if evaluation is None:
        return "evaluation 缺失"
    if evaluation.critical:
        return "evaluation.critical=True（存在致命问题）"
    return None


def has_disclaimer(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    report = _report(state)
    if report is None:
        return "report 缺失"
    if not any(_MANDATORY_DISCLAIMER in r for r in report.risks_and_disclaimers):
        return "报告缺少强制免责声明"
    return None


def data_gaps_disclosed_if_issues(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """存在数据质量问题时必须披露：thesis.data_gaps（有论点）或 report 元数据计数（降级）。"""
    issues = state.get("data_quality_issues", [])
    if not issues:
        return None
    thesis = _thesis(state)
    if thesis is not None and thesis.data_gaps:
        return None
    report = _report(state)
    if report is not None and report.metadata.data_quality_issue_count >= len(issues):
        return None
    return f"存在 {len(issues)} 条数据质量问题，但 thesis.data_gaps 与 report 均未披露"


def has_comparison_section(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    report = _report(state)
    if report is None:
        return "report 缺失"
    if report.peer_comparison is None:
        return "报告缺少 peer 对比部分"
    return None


def peer_mentioned_in_report(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """对比场景：peer 基金必须真正出现在对比文本中，而不是只在 query 里。"""
    if not case.peer_fund_ids:
        return "Case 未定义 peer_fund_ids，无法检查对比披露"
    report = _report(state)
    if report is None:
        return "report 缺失"
    text = report.peer_comparison or ""
    missing = [pid for pid in case.peer_fund_ids if pid not in text]
    if missing:
        return f"peer 基金未出现在报告对比部分：{missing}"
    return None


def fund_count(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    report = _report(state)
    if report is None:
        return "report 缺失"
    expected = int(params.get("count", 0))
    actual = report.metadata.fund_count
    if actual != expected:
        return f"report.metadata.fund_count={actual} != {expected}"
    return None


def evidence_count(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """精确计数（mock 同构数据口径）：防止静默增减 Evidence。"""
    report = _report(state)
    if report is None:
        return "report 缺失"
    expected = int(params.get("count", 0))
    actual = report.metadata.evidence_count
    if actual != expected:
        return f"report.metadata.evidence_count={actual} != {expected}"
    return None


def thesis_present(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    expected = bool(params.get("expected", True))
    actual = _thesis(state) is not None
    if actual != expected:
        return f"investment_thesis 存在性 {actual} != 期望 {expected}"
    return None


def fund_ids(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """planner 提取结果与 Case 期望一致（按序）。"""
    expected = list(params.get("ids", case.fund_ids))
    actual = list(state.get("fund_ids", []))
    if actual != expected:
        return f"fund_ids={actual} != 期望 {expected}"
    return None


def task_type_in(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    actual = state.get("task_type")
    actual_value = str(getattr(actual, "value", actual))
    allowed = list(params.get("types", []))
    if actual_value not in allowed:
        return f"task_type={actual_value} 不在允许集合 {allowed}"
    return None


def data_quality_issues_min(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """失败注入场景：质量问题必须被记录（而不是被吞掉）。"""
    minimum = int(params.get("min", 1))
    actual = len(state.get("data_quality_issues", []))
    if actual < minimum:
        return f"data_quality_issues 数量 {actual} < {minimum}"
    return None


def report_data_gaps_contain(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    report = _report(state)
    if report is None:
        return "report 缺失"
    keyword = str(params.get("keyword", ""))
    if keyword and not any(keyword in g for g in report.data_gaps_and_limitations):
        return f"报告 data_gaps_and_limitations 未包含关键字：{keyword!r}"
    return None


def suitability_mentions(state: dict, case: EvalCase, params: dict[str, Any]) -> str | None:
    """半硬检查（关键词级）：suitability 是否回应了 query 的持有期限维度。"""
    thesis = _thesis(state)
    if thesis is None:
        return "investment_thesis 缺失"
    keywords = list(params.get("keywords", []))
    missing = [kw for kw in keywords if kw not in thesis.suitability]
    if missing:
        return f"suitability 未包含关键字：{missing}"
    return None


REGISTRY: dict[str, Callable[[dict, EvalCase, dict[str, Any]], str | None]] = {
    "report_exists": report_exists,
    "has_suitability": has_suitability,
    "min_claims": min_claims,
    "all_claims_have_evidence": all_claims_have_evidence,
    "claim_coverage_min": claim_coverage_min,
    "evaluation_status_in": evaluation_status_in,
    "evaluation_critical_false": evaluation_critical_false,
    "has_disclaimer": has_disclaimer,
    "data_gaps_disclosed_if_issues": data_gaps_disclosed_if_issues,
    "has_comparison_section": has_comparison_section,
    "peer_mentioned_in_report": peer_mentioned_in_report,
    "fund_count": fund_count,
    "evidence_count": evidence_count,
    "thesis_present": thesis_present,
    "fund_ids": fund_ids,
    "task_type_in": task_type_in,
    "data_quality_issues_min": data_quality_issues_min,
    "report_data_gaps_contain": report_data_gaps_contain,
    "suitability_mentions": suitability_mentions,
}


def run_checks(state: dict, case: EvalCase) -> list[CheckResult]:
    """按 Case 顺序执行全部检查点；未注册检查名与检查函数异常都判失败。"""
    results: list[CheckResult] = []
    for spec in case.checks:
        fn = REGISTRY.get(spec.name)
        if fn is None:
            results.append(
                CheckResult(
                    name=spec.name,
                    passed=False,
                    detail=f"未注册的检查点：{spec.name}（可选：{sorted(REGISTRY)}）",
                )
            )
            continue
        try:
            reason = fn(state, case, spec.params)
        except Exception as e:  # noqa: BLE001 —— 检查点自身异常视为失败，不中断套件
            reason = f"检查点执行异常：{type(e).__name__}: {e}"
        results.append(CheckResult(name=spec.name, passed=reason is None, detail=reason or ""))
    return results


__all__ = ["REGISTRY", "run_checks"]
