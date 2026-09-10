"""AnalyzerNode 单元测试（Phase 2 验收：结果写入 State 与 Evidence，无 LLM）。"""

from tests.conftest import FUND_CODE, make_tools
from nodes.analyzer import AnalyzerNode
from store import FundStore


class TestAnalyzerNode:
    def _analyzed_state(self, store: FundStore, fund_ids: list[str]) -> dict:
        return AnalyzerNode(store)({"fund_ids": fund_ids})

    def test_computes_metrics_and_writes_evidence(self):
        tools, store, client = make_tools()
        try:
            # 先由 collector 采集，保证 store 有净值序列
            tools.get_fund_info.invoke({"fund_id": FUND_CODE})
            tools.get_fund_performance.invoke({"fund_id": FUND_CODE})

            out = self._analyzed_state(store, [FUND_CODE])

            analysis = out["analysis"]
            assert analysis.performance.fund_id == FUND_CODE
            assert analysis.performance.nav_point_count == 3
            # conftest 净值单调上行 [1.0, 2.0, 5.7559] → 无回撤，累计收益已知
            assert analysis.performance.cumulative_return == 5.7559 / 1.0 - 1
            assert analysis.risk.max_drawdown == 0.0
            assert analysis.risk.annual_volatility is not None
            assert analysis.risk.sharpe is not None
            assert analysis.performance.data_quality == "complete"
            assert analysis.risk.data_quality == "complete"

            # 单只基金无 peer 对比
            assert analysis.peer_comparison is None

            # calculation 类型 Evidence（独立调用时 state 无既有 evidence）
            assert len(out["evidence"]) == 1
            ev = out["evidence"][0]
            assert ev.evidence_type == "calculation"
            assert ev.value["fund_id"] == FUND_CODE
            assert ev.raw_ref == f"store:nav/{FUND_CODE}"

            assert out["data_quality_issues"] == []
        finally:
            client.close()

    def test_peer_comparison_with_two_funds(self):
        tools, store, client = make_tools()
        try:
            for code in ["000001", FUND_CODE]:
                tools.get_fund_info.invoke({"fund_id": code})
                tools.get_fund_performance.invoke({"fund_id": code})

            out = self._analyzed_state(store, ["000001", FUND_CODE])

            analysis = out["analysis"]
            assert analysis.peer_comparison is not None
            assert analysis.peer_comparison.base_fund_id == "000001"
            assert [r.fund_id for r in analysis.peer_comparison.rows] == ["000001", FUND_CODE]
            # 两条 calculation Evidence（每只基金一条）
            assert len(out["evidence"]) == 2
            assert {e.evidence_type for e in out["evidence"]} == {"calculation"}
        finally:
            client.close()

    def test_explicit_primary_fund_from_plan(self):
        tools, store, client = make_tools()
        try:
            for code in ["000001", FUND_CODE]:
                tools.get_fund_performance.invoke({"fund_id": code})

            state = {
                "fund_ids": ["000001", FUND_CODE],
                "research_plan": {
                    "task_type": "fund_research",
                    "primary_fund_id": FUND_CODE,
                    "fund_ids": ["000001", FUND_CODE],
                    "notes": [],
                },
            }
            out = AnalyzerNode(store)(state)

            # 显式指定主基金时，performance/risk 以指定者为准（而非首个）
            assert out["analysis"].performance.fund_id == FUND_CODE
            assert out["analysis"].risk.fund_id == FUND_CODE
            assert out["analysis"].peer_comparison.base_fund_id == FUND_CODE
        finally:
            client.close()

    def test_primary_not_in_fund_ids_falls_back(self):
        tools, store, client = make_tools()
        try:
            for code in ["000001", FUND_CODE]:
                tools.get_fund_performance.invoke({"fund_id": code})

            state = {
                "fund_ids": ["000001", FUND_CODE],
                "research_plan": {
                    "task_type": "fund_research",
                    "primary_fund_id": "999999",
                    "fund_ids": ["000001", FUND_CODE],
                    "notes": [],
                },
            }
            out = AnalyzerNode(store)(state)
            assert out["analysis"].performance.fund_id == "000001"
        finally:
            client.close()

    def test_missing_nav_data_flags_issue(self):
        # 空 store：fund_ids 存在但没有净值数据
        out = self._analyzed_state(FundStore(), [FUND_CODE])

        assert out["analysis"].performance.data_quality == "missing"
        assert out["analysis"].performance.cumulative_return is None
        assert out["analysis"].risk.sharpe is None
        assert any("净值数据不足" in i for i in out["data_quality_issues"])
        # calculation Evidence 仍写入，data_quality=missing
        assert out["evidence"][0].evidence_type == "calculation"
        assert out["evidence"][0].data_quality == "missing"

    def test_no_fund_ids_returns_empty(self):
        assert AnalyzerNode(FundStore())({"fund_ids": []}) == {}
