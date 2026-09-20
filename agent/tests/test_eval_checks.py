"""评测硬检查单元测试（Phase 10）。

不跑 graph：用最小领域对象拼 state，覆盖检查点注册表的关键通过/失败分支与防御行为
（未注册检查名 / 检查函数异常都判失败，防止静默通过）。
"""

from datetime import datetime

from domain.evidence import Evidence
from domain.evaluation import EvaluationResult, EvaluationStatus
from domain.report import Report, ReportMetadata
from domain.task_type import TaskType
from domain.thesis import Claim, InvestmentThesis
from eval.checks import run_checks
from eval.models import CheckSpec, EvalCase


def _case(checks: list[CheckSpec], **kw) -> EvalCase:
    return EvalCase(id="t", name="t", query="q", checks=checks, **kw)


def _thesis(claims=None, data_gaps=None) -> InvestmentThesis:
    return InvestmentThesis(
        summary="s",
        claims=claims
        if claims is not None
        else [
            Claim(
                id="claim-1",
                statement="c",
                claim_type="performance",
                evidence_ids=["ev-1"],
                strength="strong",
            )
        ],
        suitability="证据支持下可考虑长期持有",
        confidence=0.5,
        data_gaps=data_gaps or [],
    )


def _report(metadata: ReportMetadata | None = None, peer: str | None = None) -> Report:
    return Report(
        title="t",
        generated_at=datetime.now(),
        request_id="r",
        executive_summary="s",
        peer_comparison=peer,
        risks_and_disclaimers=[
            "历史业绩不代表未来表现",
            "本报告由程序自动生成，不构成任何投资建议。",
        ],
        metadata=metadata or ReportMetadata(),
    )


def _state(**overrides) -> dict:
    state = {
        "evidence": [Evidence(id="ev-1", evidence_type="fund_data", source="s", value={})],
        "investment_thesis": _thesis(),
        "evaluation": EvaluationResult(status=EvaluationStatus.PASS, claim_coverage_ratio=1.0),
        "report": _report(),
        "fund_ids": ["519770"],
        "task_type": TaskType.FUND_RESEARCH,
        "data_quality_issues": [],
    }
    state.update(overrides)
    return state


def _run(state: dict, specs: list[CheckSpec], **case_kw) -> dict[str, bool]:
    results = run_checks(state, _case(specs, **case_kw))
    return {r.name: r.passed for r in results}


class TestCheckRegistry:
    def test_green_state_passes_core_checks(self):
        state = _state(
            report=_report(
                metadata=ReportMetadata(fund_count=1, evidence_count=4),
                peer="- 519770: ...",
            ),
            data_quality_issues=["issue"],
        )
        passed = _run(
            state,
            [
                CheckSpec(name="report_exists"),
                CheckSpec(name="has_suitability"),
                CheckSpec(name="min_claims", params={"min": 1}),
                CheckSpec(name="all_claims_have_evidence"),
                CheckSpec(name="claim_coverage_min", params={"min": 0.5}),
                CheckSpec(name="has_disclaimer"),
                CheckSpec(name="fund_count", params={"count": 1}),
                CheckSpec(name="evidence_count", params={"count": 4}),
                CheckSpec(name="fund_ids", params={"ids": ["519770"]}),
                CheckSpec(name="task_type_in", params={"types": ["fund_research"]}),
                CheckSpec(name="suitability_mentions", params={"keywords": ["长期"]}),
                CheckSpec(name="evaluation_status_in", params={"statuses": ["pass"]}),
                CheckSpec(name="evaluation_critical_false"),
                CheckSpec(name="peer_mentioned_in_report"),
            ],
            peer_fund_ids=["519770"],
        )
        assert all(passed.values()), passed

    def test_unknown_check_name_fails(self):
        results = run_checks(_state(), _case([CheckSpec(name="no_such_check")]))
        assert len(results) == 1
        assert not results[0].passed
        assert "未注册" in results[0].detail

    def test_claim_without_real_evidence_fails(self):
        state = _state(
            investment_thesis=_thesis(
                claims=[
                    Claim(id="c1", statement="x", claim_type="risk", evidence_ids=[], strength="weak"),
                    Claim(
                        id="c2",
                        statement="y",
                        claim_type="peer",
                        evidence_ids=["ev-nonexistent"],
                        strength="weak",
                    ),
                ]
            )
        )
        passed = _run(state, [CheckSpec(name="all_claims_have_evidence")])
        assert not passed["all_claims_have_evidence"]

    def test_min_claims_fails_on_empty_claims(self):
        state = _state(investment_thesis=_thesis(claims=[]))
        passed = _run(state, [CheckSpec(name="min_claims", params={"min": 1})])
        assert not passed["min_claims"]

    def test_missing_thesis_fails_thesis_checks(self):
        state = _state(investment_thesis=None)
        passed = _run(
            state,
            [
                CheckSpec(name="has_suitability"),
                CheckSpec(name="min_claims"),
                CheckSpec(name="thesis_present", params={"expected": True}),
                CheckSpec(name="thesis_present", params={"expected": False}),
            ],
        )
        assert passed["thesis_present"] is True  # expected=False：thesis 缺失即通过
        assert not passed["has_suitability"]
        assert not passed["min_claims"]

    def test_data_gaps_disclosure_branches(self):
        # 无质量问题 → 直接通过
        assert _run(_state(), [CheckSpec(name="data_gaps_disclosed_if_issues")])[
            "data_gaps_disclosed_if_issues"
        ]
        # 有质量问题 + thesis.data_gaps 已披露 → 通过
        state = _state(
            data_quality_issues=["x: 基金数据获取完全失败"],
            investment_thesis=_thesis(data_gaps=["x: 基金数据获取完全失败"]),
        )
        assert _run(state, [CheckSpec(name="data_gaps_disclosed_if_issues")])[
            "data_gaps_disclosed_if_issues"
        ]
        # 有质量问题 + thesis 缺失 + report 元数据计数一致 → 通过（降级披露渠道）
        state = _state(
            data_quality_issues=["a", "b"],
            investment_thesis=None,
            report=_report(metadata=ReportMetadata(data_quality_issue_count=2)),
        )
        assert _run(state, [CheckSpec(name="data_gaps_disclosed_if_issues")])[
            "data_gaps_disclosed_if_issues"
        ]
        # 有质量问题 + 全部未披露 → 失败
        state = _state(
            data_quality_issues=["a", "b"],
            investment_thesis=None,
            report=_report(metadata=ReportMetadata(data_quality_issue_count=0)),
        )
        assert not _run(state, [CheckSpec(name="data_gaps_disclosed_if_issues")])[
            "data_gaps_disclosed_if_issues"
        ]

    def test_evaluation_status_in_fails_on_unexpected_status(self):
        state = _state(
            evaluation=EvaluationResult(status=EvaluationStatus.FAIL, claim_coverage_ratio=1.0)
        )
        passed = _run(state, [CheckSpec(name="evaluation_status_in", params={"statuses": ["pass"]})])
        assert not passed["evaluation_status_in"]

    def test_peer_check_requires_case_peer_ids(self):
        passed = _run(_state(), [CheckSpec(name="peer_mentioned_in_report")])
        assert not passed["peer_mentioned_in_report"]

    def test_check_exception_counts_as_failure(self):
        # report 类型异常（如意外为 str）→ 检查函数抛 AttributeError → 判失败而非崩溃
        passed = _run(_state(report="not-a-report"), [CheckSpec(name="fund_count")])
        assert not passed["fund_count"]

    def test_report_data_gaps_contain(self):
        report = _report()
        report.data_gaps_and_limitations.append("query 中未发现 6 位基金代码，无法规划数据采集")
        passed = _run(
            _state(report=report),
            [CheckSpec(name="report_data_gaps_contain", params={"keyword": "基金代码"})],
        )
        assert passed["report_data_gaps_contain"]


class TestComparisonChecks:
    """对比报告一等公民检查：标题覆盖 / 章节对称 / 跨基金 claim。"""

    FUNDS = ["000001", "519770"]

    def _comparison_report(
        self,
        title: str = "FundForge 基金对比报告：000001 A vs 519770 B",
        performance: str = "000001 …、519770 …",
        risk: str = "000001 …、519770 …",
    ) -> Report:
        return Report(
            title=title,
            generated_at=datetime.now(),
            request_id="r",
            executive_summary="s",
            performance_analysis=performance,
            risk_analysis=risk,
            peer_comparison="…",
            risks_and_disclaimers=["本报告由程序自动生成，不构成任何投资建议。"],
            metadata=ReportMetadata(),
        )

    def _comparison_state(
        self,
        report: Report,
        evidence: list[Evidence],
        claim_evidence_ids: list[str] | None = None,
    ) -> dict:
        return _state(
            report=report,
            evidence=evidence,
            fund_ids=self.FUNDS,
            task_type=TaskType.FUND_COMPARISON,
            investment_thesis=_thesis(
                claims=[
                    Claim(
                        id="claim-1",
                        statement="c",
                        claim_type="performance",
                        evidence_ids=claim_evidence_ids or ["ev-1"],
                        strength="strong",
                    )
                ]
            ),
        )

    def _run_comparison(self, state: dict, names: list[str]) -> dict[str, bool]:
        specs = [CheckSpec(name=n) for n in names]
        return _run(state, specs, fund_ids=self.FUNDS)

    def test_title_covers_funds(self):
        passed = self._run_comparison(
            self._comparison_state(self._comparison_report(), _state()["evidence"]),
            ["comparison_title_covers_funds"],
        )
        assert passed["comparison_title_covers_funds"]

        one_sided = self._comparison_report(title="FundForge 基金研究报告：000001 A")
        passed = self._run_comparison(
            self._comparison_state(one_sided, _state()["evidence"]),
            ["comparison_title_covers_funds"],
        )
        assert not passed["comparison_title_covers_funds"]

    def test_performance_sections_symmetric(self):
        passed = self._run_comparison(
            self._comparison_state(self._comparison_report(), _state()["evidence"]),
            ["performance_sections_symmetric"],
        )
        assert passed["performance_sections_symmetric"]

        primary_only = self._comparison_report(performance="仅 000001", risk="仅 000001")
        passed = self._run_comparison(
            self._comparison_state(primary_only, _state()["evidence"]),
            ["performance_sections_symmetric"],
        )
        assert not passed["performance_sections_symmetric"]

    def test_comparative_claim_present(self):
        cross_evidence = [
            Evidence(id="ev-1", evidence_type="fund_data", source="s", value={"fund_id": "000001"}),
            Evidence(id="ev-2", evidence_type="fund_data", source="s", value={"fund_id": "519770"}),
        ]
        passed = self._run_comparison(
            self._comparison_state(self._comparison_report(), cross_evidence, ["ev-1", "ev-2"]),
            ["comparative_claim_present"],
        )
        assert passed["comparative_claim_present"]

        passed = self._run_comparison(
            self._comparison_state(self._comparison_report(), cross_evidence, ["ev-1"]),
            ["comparative_claim_present"],
        )
        assert not passed["comparative_claim_present"]

    def test_comparative_claim_raw_ref_fallback(self):
        # value 无 fund_id 时回退解析 raw_ref 末段（与 Evaluator 同口径）
        evidence = [
            Evidence(id="ev-1", evidence_type="fund_data", source="s", value={"fund_id": "000001"}),
            Evidence(id="ev-2", evidence_type="fund_data", source="s", value={}, raw_ref="store:nav/519770"),
        ]
        passed = self._run_comparison(
            self._comparison_state(self._comparison_report(), evidence, ["ev-1", "ev-2"]),
            ["comparative_claim_present"],
        )
        assert passed["comparative_claim_present"]
