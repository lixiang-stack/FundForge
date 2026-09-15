"""Evaluator / Repair 节点单元测试（Phase 5 验收，全确定性）。"""

import pytest

from domain.evaluation import EvaluationResult
from domain.thesis import Claim, InvestmentThesis, Strength
from nodes.evaluator import EvaluatorNode
from nodes.repair import RepairNode
from tests.test_thesis import EV1, _thesis

EV2 = "ev-bbbbbbbbbbbb"


def _evidence_state(quality_ev1: str = "complete") -> dict:
    return {
        "user_query": "分析基金 519770 是否适合长期持有",
        "evidence": [
            {"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {"a": 1}, "data_quality": quality_ev1},
            {"id": EV2, "evidence_type": "fund_data", "source": "s", "value": {"b": 2}, "data_quality": "complete"},
        ],
        "claims": [
            {"id": "claim-1", "statement": "结论 A", "claim_type": "performance", "evidence_ids": [EV1], "strength": "strong"},
        ],
    }


def _thesis_state(quality_ev1: str = "complete") -> dict:
    thesis = _thesis(
        [
            Claim(id="c1", statement="结论 A", claim_type="performance", evidence_ids=[EV1], strength="strong"),
        ],
        risks=["回撤风险"],
    )
    state = _evidence_state(quality_ev1)
    state["investment_thesis"] = thesis.model_dump(mode="json")
    return state


class TestEvaluator:
    def test_valid_state_passes(self):
        out = EvaluatorNode()(_thesis_state())
        evaluation = out["evaluation"]
        assert evaluation.status == "pass"
        assert not evaluation.critical
        assert evaluation.all_issues() == []

    def test_unknown_evidence_reference_is_critical_fail(self):
        state = _thesis_state()
        state["claims"] = [
            {"id": "claim-1", "statement": "坏引用", "claim_type": "peer", "evidence_ids": ["ev-ghost"], "strength": "weak"}
        ]
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert evaluation.critical
        assert evaluation.evidence_issues
        assert evaluation.overall_score < 1.0

    def test_missing_quality_evidence_is_factual_issue(self):
        # 故意制造缺失 Evidence：claim 引用 data_quality=missing 的证据
        out = EvaluatorNode()(_thesis_state(quality_ev1="missing"))
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert evaluation.factual_issues
        assert "missing" in evaluation.factual_issues[0]

    def test_missing_thesis_fails_completeness(self):
        state = _evidence_state()
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert any("缺少投资论点" in i for i in evaluation.missing_items)

    def test_empty_risks_fails_risk_coverage(self):
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="peer", evidence_ids=[EV1], strength="weak")],
            risks=[],
        )
        state = _evidence_state()
        state["investment_thesis"] = thesis.model_dump(mode="json")
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert evaluation.risk_issues

    def test_alignment_recorded_but_not_failing(self):
        state = _thesis_state()
        state["user_query"] = "对比 000001 和 519770"
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        # V1 Repair 无对应动作：alignment 只记录不判 FAIL
        assert evaluation.question_alignment_issues
        assert evaluation.status == "pass"

    def test_score_between_zero_and_one(self):
        out = EvaluatorNode()(_thesis_state(quality_ev1="missing"))
        assert 0.0 <= out["evaluation"].overall_score <= 1.0

    def test_coverage_ratio_hard_threshold(self):
        # 3 个 Claim 中 1 个有效绑定 → 覆盖率 33% < 50% 阈值 → 追加硬阈值 issue
        state = _thesis_state()
        state["claims"] = [
            {"id": "claim-1", "statement": "有效", "claim_type": "risk", "evidence_ids": [EV1], "strength": "strong"},
            {"id": "claim-2", "statement": "空绑定", "claim_type": "peer", "evidence_ids": [], "strength": "weak"},
            {"id": "claim-3", "statement": "坏引用", "claim_type": "peer", "evidence_ids": ["ev-x"], "strength": "weak"},
        ]
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.claim_coverage_ratio == pytest.approx(1 / 3, abs=0.01)
        assert any("硬阈值" in i for i in evaluation.evidence_issues)
        assert evaluation.status == "fail"  # 绑定失败 = 可触发 Repair 的 issue

    def test_binding_failure_is_repairable_evidence_issue(self):
        state = _thesis_state()
        state["claims"] = [
            {"id": "claim-1", "statement": "坏引用", "claim_type": "peer", "evidence_ids": ["ev-ghost"], "strength": "weak"}
        ]
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert evaluation.critical  # 全部 Claim 未有效绑定 = 严重幻觉风险
        assert evaluation.claim_coverage_ratio == 0.0

    def test_undisclosed_data_quality_issues_fail(self):
        # Phase 8 硬指标：存在数据质量问题但 thesis.data_gaps 为空 → 未披露
        state = _thesis_state()
        state["data_quality_issues"] = ["519770: 净值数据不足"]
        out = EvaluatorNode()(state)
        evaluation = out["evaluation"]
        assert evaluation.status == "fail"
        assert any("data_gaps 未披露" in i for i in evaluation.missing_items)

    def test_disclosed_data_quality_issues_pass(self):
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="risk", evidence_ids=[EV1], strength="weak")],
            data_gaps=["519770: 净值数据不足"],
        )
        state = _evidence_state()
        state["investment_thesis"] = thesis.model_dump(mode="json")
        state["data_quality_issues"] = ["519770: 净值数据不足"]
        out = EvaluatorNode()(state)
        assert out["evaluation"].status == "pass"


class TestRepair:
    def test_drops_claims_with_invalid_references(self):
        evaluation = EvaluationResult(status="fail", evidence_issues=["claim-1 引用了不存在的证据"])
        thesis = _thesis(
            [
                Claim(id="c1", statement="坏引用", claim_type="peer", evidence_ids=["ev-ghost"], strength="weak"),
                Claim(id="c2", statement="好引用", claim_type="risk", evidence_ids=[EV1], strength="weak"),
            ]
        )
        state = {
            "evaluation": evaluation.model_dump(mode="json"),
            "investment_thesis": thesis.model_dump(mode="json"),
            "claims": thesis.claims,
            "evidence": [{"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {}}],
            "iteration": 0,
        }
        out = RepairNode()(state)

        assert out["iteration"] == 1
        assert [c.id for c in out["claims"]] == ["c2"]
        assert any(a.startswith("revise_claim(c1)") for a in out["repair_actions"])
        # Thesis 的 claims 与 State.claims 保持一致
        assert [c.id for c in out["investment_thesis"].claims] == ["c2"]

    def test_downgrades_strong_claims_on_factual_issues(self):
        evaluation = EvaluationResult(status="fail", factual_issues=["claim-1 引用 missing 证据"])
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="risk", evidence_ids=[EV1], strength="strong")]
        )
        state = {
            "evaluation": evaluation.model_dump(mode="json"),
            "investment_thesis": thesis.model_dump(mode="json"),
            "claims": thesis.claims,
            "evidence": [{"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {}}],
            "iteration": 0,
        }
        out = RepairNode()(state)

        assert out["claims"][0].strength == Strength.MODERATE
        assert any(a.startswith("revise_claim(c1)") for a in out["repair_actions"])
        # FAIL 触发 reduce_confidence
        assert out["investment_thesis"].confidence == thesis.confidence * 0.5
        assert any(a.startswith("reduce_confidence") for a in out["repair_actions"])

    def test_adds_risk_disclosure_when_missing(self):
        evaluation = EvaluationResult(status="fail", risk_issues=["Thesis 未给出任何风险提示"])
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="peer", evidence_ids=[EV1], strength="weak")],
            risks=[],
        )
        state = {
            "evaluation": evaluation.model_dump(mode="json"),
            "investment_thesis": thesis.model_dump(mode="json"),
            "claims": thesis.claims,
            "evidence": [{"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {}}],
            "iteration": 0,
        }
        out = RepairNode()(state)

        assert len(out["investment_thesis"].risks) == 1
        assert any(a.startswith("add_risk_disclosure") for a in out["repair_actions"])

    def test_no_thesis_repair_no_ops(self):
        evaluation = EvaluationResult(status="fail", missing_items=["缺少投资论点"])
        out = RepairNode()({"evaluation": evaluation.model_dump(mode="json"), "iteration": 0})
        assert out["iteration"] == 1
        assert out["repair_actions"] == []

    def test_repair_discloses_data_gaps(self):
        # Phase 8 硬指标对应动作：把 State 数据质量问题补进 thesis.data_gaps
        evaluation = EvaluationResult(
            status="fail", missing_items=["State 存在数据质量问题但 thesis.data_gaps 未披露"]
        )
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="risk", evidence_ids=[EV1], strength="weak")],
            data_gaps=[],
        )
        state = {
            "evaluation": evaluation.model_dump(mode="json"),
            "investment_thesis": thesis.model_dump(mode="json"),
            "claims": thesis.claims,
            "evidence": [{"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {}}],
            "data_quality_issues": ["519770: 净值数据不足"],
            "iteration": 0,
        }
        out = RepairNode()(state)

        assert out["investment_thesis"].data_gaps == ["519770: 净值数据不足"]
        assert any("thesis.data_gaps" in a for a in out["repair_actions"])

    def test_does_not_replan(self):
        # 允许动作之外不应出现任何动作类型
        evaluation = EvaluationResult(
            status="fail",
            factual_issues=["x"],
            evidence_issues=["y"],
            risk_issues=["z"],
        )
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="risk", evidence_ids=[EV1], strength="strong")],
            risks=[],
        )
        state = {
            "evaluation": evaluation.model_dump(mode="json"),
            "investment_thesis": thesis.model_dump(mode="json"),
            "claims": thesis.claims,
            "evidence": [{"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {}}],
            "iteration": 0,
        }
        out = RepairNode()(state)
        allowed = {"revise_claim", "add_risk_disclosure", "reduce_confidence",
                   "fetch_missing_data", "add_evidence"}
        for action in out["repair_actions"]:
            assert action.split("(")[0] in allowed
