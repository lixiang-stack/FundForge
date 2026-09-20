"""Evaluator 节点（Node 合同 §4，全确定性实现，不调用 LLM）。

检查维度与实现：
- Factuality：claim 引用的 evidence 数据质量不得为 missing（引用失效即潜在幻觉）；
- Evidence Coverage：每个 claim 的 evidence_ids 必须真实存在于 State；
- Completeness：有证据时必须有 Thesis / claims / suitability；
- Risk Coverage：thesis.risks 不得为空；
- Question Alignment：关键词规则（如 query 要求对比但无 peer 数据）；
- Data Quality：State 的 data_quality_issues 透传记录。

失败语义（可修复优先）：
- factual / evidence / missing / risk 任一非空 → FAIL（Repair 有对应动作）；
- alignment / data_quality 仅记录不判 FAIL（V1 Repair 无对应修复动作，
  判 FAIL 只会空耗修复循环；Phase 6 fetch_missing_data 落地后再评估）。
"""

import logging
from typing import TypedDict

from domain.analysis import AnalysisResult
from domain.evaluation import EvaluationResult, EvaluationStatus
from domain.evidence import Evidence
from domain.shared import DataQuality, coerce_model
from domain.task_type import COMPARISON_INTENT_KEYWORDS, TaskType
from domain.thesis import Claim, InvestmentThesis
from state import FundForgeState

logger = logging.getLogger(__name__)

_LONG_TERM_KEYWORD = "长期持有"
_MIN_CLAIM_COVERAGE_RATIO = 0.5


class EvaluatorOutput(TypedDict, total=False):
    """Evaluator 节点输出（§4：evaluation）。"""

    evaluation: EvaluationResult


class EvaluatorNode:
    """Evaluator 节点：对 Thesis / Claim / Evidence 做确定性验证。"""

    def __call__(self, state: FundForgeState) -> EvaluatorOutput:
        thesis = coerce_model(state.get("investment_thesis"), InvestmentThesis)
        claims = [
            c if isinstance(c, Claim) else Claim.model_validate(c)
            for c in state.get("claims", [])
        ]
        evidence = [
            e if isinstance(e, Evidence) else Evidence.model_validate(e)
            for e in state.get("evidence", [])
        ]
        analysis = coerce_model(state.get("analysis"), AnalysisResult)
        query = state.get("user_query", "")

        factual: list[str] = []
        evidence_issues: list[str] = []
        missing: list[str] = []
        risk_issues: list[str] = []
        alignment: list[str] = []

        evidence_by_id = {e.id: e for e in evidence}

        # ---- Evidence Coverage / Factuality（针对 claims） ----
        bound_claims = 0
        for claim in claims:
            if not claim.evidence_ids:
                evidence_issues.append(f"claim {claim.id} 未绑定任何 evidence")
                continue
            unknown = [eid for eid in claim.evidence_ids if eid not in evidence_by_id]
            if unknown:
                evidence_issues.append(f"claim {claim.id} 引用了不存在的证据 {unknown}")
                continue
            bound_claims += 1
            missing_quality = [
                eid
                for eid in claim.evidence_ids
                if (
                    eid in evidence_by_id
                    and evidence_by_id[eid].data_quality == DataQuality.MISSING
                )
            ]
            if missing_quality:
                factual.append(
                    f"claim {claim.id} 引用的证据 {missing_quality} 数据质量为 missing，结论不可信"
                )

        # ---- 证据覆盖率硬阈值（Claim 数量 vs 有效绑定） ----
        # 绑定失败（空绑定 / 无效引用）即 evidence_issues，可直接触发 Repair；
        # 覆盖率 < 50% 追加硬阈值 issue，同样走 Repair（丢弃/降级 Claim 后重评）。
        coverage_ratio = round(bound_claims / len(claims), 2) if claims else 1.0
        if claims and coverage_ratio < _MIN_CLAIM_COVERAGE_RATIO:
            evidence_issues.append(
                f"证据覆盖率 {coverage_ratio:.0%} 低于 {_MIN_CLAIM_COVERAGE_RATIO:.0%} 硬阈值"
                f"（{bound_claims}/{len(claims)} 个 Claim 有效绑定）"
            )
        if claims and bound_claims == 0:
            # 全部 Claim 未有效绑定 = 严重幻觉风险
            critical_binding_failure = True
        else:
            critical_binding_failure = False

        # ---- Completeness ----
        state_quality_issues = list(state.get("data_quality_issues", []))
        if evidence and thesis is None:
            missing.append("存在已采集证据但缺少投资论点（Thesis）")
        if thesis is not None:
            if not thesis.claims:
                missing.append("Thesis 中没有任何 Claim（重要结论必须有 Claim 支撑）")
            if not thesis.suitability.strip():
                missing.append("Thesis 缺少 suitability（未回答「是否适合长期持有」）")
            # data_gaps 披露硬指标：存在数据质量问题却未披露
            if state_quality_issues and not thesis.data_gaps:
                missing.append("State 存在数据质量问题但 thesis.data_gaps 未披露")

        # ---- Risk Coverage ----
        if thesis is not None and not thesis.risks:
            risk_issues.append("Thesis 未给出任何风险提示")

        # ---- Question Alignment（任务类型 + 关键词规则） ----
        peer_expected = (
            state.get("task_type") == TaskType.FUND_COMPARISON
            or any(kw in query for kw in COMPARISON_INTENT_KEYWORDS)
        )
        if peer_expected:
            if analysis is None or analysis.peer_comparison is None:
                alignment.append("query 要求基金对比，但未生成 peer 对比数据")
            elif claims:
                comparative = [
                    c for c in claims if len(claim_fund_ids(c, evidence_by_id)) >= 2
                ]
                if not comparative:
                    alignment.append(
                        "对比任务：所有 claim 仅绑定单一基金证据，未形成跨基金对比结论"
                    )
        if _LONG_TERM_KEYWORD in query and thesis is not None and "长期" not in thesis.suitability:
            alignment.append("query 询问长期持有，但 suitability 未回应持有期限维度")

        issue_groups = [factual, evidence_issues, missing, risk_issues, alignment]
        evaluation = EvaluationResult(
            status=(
                EvaluationStatus.FAIL
                if any([factual, evidence_issues, missing, risk_issues])
                else EvaluationStatus.PASS
            ),
            factual_issues=factual,
            evidence_issues=evidence_issues,
            missing_items=missing,
            risk_issues=risk_issues,
            question_alignment_issues=alignment,
            data_quality_issues=state_quality_issues,
            overall_score=_overall_score(issue_groups),
            claim_coverage_ratio=coverage_ratio,
            critical=bool(evidence_issues) or critical_binding_failure,
        )

        logger.info(
            "evaluator: status=%s score=%.2f critical=%s issues=%d",
            evaluation.status,
            evaluation.overall_score,
            evaluation.critical,
            len(evaluation.all_issues()),
        )
        return {"evaluation": evaluation}


def claim_fund_ids(claim: Claim, evidence_by_id: dict[str, Evidence]) -> set[str]:
    """claim 绑定证据覆盖的基金集合（value.fund_id 优先，回退解析 raw_ref 末段）。"""
    funds: set[str] = set()
    for eid in claim.evidence_ids:
        e = evidence_by_id.get(eid)
        if e is None:
            continue
        value = e.value if isinstance(e.value, dict) else None
        fund_id = value.get("fund_id") if value else None
        if not fund_id and e.raw_ref:
            fund_id = e.raw_ref.rstrip("/").rsplit("/", 1)[-1]
        if fund_id:
            funds.add(str(fund_id))
    return funds


def _overall_score(issue_groups: list[list[str]]) -> float:
    """确定性评分：1 - 非空问题组占比（保留 2 位）。"""
    failed = sum(1 for group in issue_groups if group)
    return round(max(0.0, 1.0 - failed / len(issue_groups)), 2)


__all__ = ["EvaluatorNode", "EvaluatorOutput"]
