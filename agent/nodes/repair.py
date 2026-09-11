"""Repair 节点（Node 合同 §4，全确定性实现，不调用 LLM）。

原则（§4 / §10）：
- 只修复 Evaluator 明确指出的问题；
- 允许动作（V1 实现 3/5）：revise_claim | add_risk_disclosure | reduce_confidence
  （fetch_missing_data 留 Phase 6 —— 需要 collector 重入）；
- 不允许重新规划整个 Research Plan；
- iteration 硬限制 max=1，由 Graph 条件边控制，Repair 本身只负责 +1。

动作映射：
- evidence_issues → revise_claim：丢弃引用无效的 Claim（§8 强制绑定）；
- factual_issues → revise_claim（降级 strength strong → moderate）+ reduce_confidence；
- risk_issues → add_risk_disclosure：补充风险声明；
- 任何 FAIL → reduce_confidence（置信度随证据问题下降）。
"""

import logging

from domain.evaluation import EvaluationResult, EvaluationStatus, RepairAction, RepairActionType
from domain.evidence import Evidence
from domain.shared import coerce_model
from domain.thesis import Claim, InvestmentThesis, Strength
from state import FundForgeState

logger = logging.getLogger(__name__)

_RISK_DISCLOSURE = "证据覆盖存在缺口，本论点存在不确定性，请在决策前补充验证相关数据。"
_CONFIDENCE_FACTOR = 0.5
_MIN_CONFIDENCE = 0.05


class RepairNode:
    """Repair 节点：按 Evaluator 指出的问题做有限修正。"""

    def __call__(self, state: FundForgeState) -> dict:
        evaluation = coerce_model(state.get("evaluation"), EvaluationResult)
        thesis = coerce_model(state.get("investment_thesis"), InvestmentThesis)
        claims = [
            c if isinstance(c, Claim) else Claim.model_validate(c)
            for c in state.get("claims", [])
        ]
        iteration = int(state.get("iteration", 0))

        actions: list[RepairAction] = []
        updated_thesis = thesis
        updated_claims = claims

        if evaluation is None:
            logger.warning("repair: 无 evaluation，跳过")
            return {"iteration": iteration + 1}

        evidence_ids = {e.id for e in _norm_evidence(state)}

        # ---- revise_claim：丢弃无效引用 + 降级 weak 化 ----
        if evaluation.evidence_issues:
            valid_claims = []
            for claim in updated_claims:
                unknown = [eid for eid in claim.evidence_ids if eid not in evidence_ids]
                if unknown:
                    actions.append(
                        RepairAction(
                            action_type=RepairActionType.REVISE_CLAIM,
                            target=claim.id,
                            reason=f"引用不存在的证据 {unknown}，已丢弃该 Claim",
                        )
                    )
                    continue
                valid_claims.append(claim)
            updated_claims = valid_claims

        if evaluation.factual_issues and updated_thesis is not None:
            downgraded = []
            for claim in updated_claims:
                if claim.strength == Strength.STRONG:
                    actions.append(
                        RepairAction(
                            action_type=RepairActionType.REVISE_CLAIM,
                            target=claim.id,
                            reason="引用的证据数据质量为 missing，strength 由 strong 降为 moderate",
                        )
                    )
                    downgraded.append(claim.model_copy(update={"strength": Strength.MODERATE}))
                else:
                    downgraded.append(claim)
            updated_claims = downgraded

        # ---- add_risk_disclosure ----
        if evaluation.risk_issues and updated_thesis is not None:
            actions.append(
                RepairAction(
                    action_type=RepairActionType.ADD_RISK_DISCLOSURE,
                    target="thesis.risks",
                    reason="Thesis 缺少风险提示，已补充",
                )
            )
            updated_thesis = updated_thesis.model_copy(
                update={"risks": [*updated_thesis.risks, _RISK_DISCLOSURE]}
            )

        # ---- reduce_confidence ----
        if evaluation.status == EvaluationStatus.FAIL and updated_thesis is not None:
            new_confidence = max(
                _MIN_CONFIDENCE, round(updated_thesis.confidence * _CONFIDENCE_FACTOR, 2)
            )
            actions.append(
                RepairAction(
                    action_type=RepairActionType.REDUCE_CONFIDENCE,
                    target="thesis.confidence",
                    reason=f"评估未通过（{len(evaluation.all_issues())} 个问题），置信度下调",
                )
            )
            updated_thesis = updated_thesis.model_copy(update={"confidence": new_confidence})

        # Thesis 的 claims 字段与 State.claims 保持一致
        if updated_thesis is not None:
            updated_thesis = updated_thesis.model_copy(update={"claims": updated_claims})

        logger.info(
            "repair: iteration=%d, actions=%d, claims %d -> %d",
            iteration + 1,
            len(actions),
            len(claims),
            len(updated_claims),
        )
        return {
            "investment_thesis": updated_thesis,
            "claims": updated_claims,
            "repair_actions": [
                f"{a.action_type}({a.target}): {a.reason}" for a in actions
            ],
            "iteration": iteration + 1,
        }


def _norm_evidence(state: FundForgeState) -> list[Evidence]:
    return [
        e if isinstance(e, Evidence) else Evidence.model_validate(e)
        for e in state.get("evidence", [])
    ]


__all__ = ["RepairNode"]
