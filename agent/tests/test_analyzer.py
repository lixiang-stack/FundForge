"""AnalyzerNode 单元测试（Phase 2 验收：结果写入 State 与 Evidence，无 LLM）。"""

from datetime import date

import pytest

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


def _comparison_state(fund_ids: list[str]) -> dict:
    return {
        "fund_ids": fund_ids,
        "research_plan": {
            "task_type": "fund_comparison",
            "primary_fund_id": fund_ids[0],
            "fund_ids": fund_ids,
            "notes": [],
        },
    }


class TestAnalyzerHoldingsComparison:
    def _collect(self, tools, codes: list[str]) -> None:
        for code in codes:
            tools.get_fund_info.invoke({"fund_id": code})
            tools.get_fund_performance.invoke({"fund_id": code})
            tools.get_fund_holdings.invoke({"fund_id": code})

    def test_comparison_enriches_rows_and_holdings(self):
        tools, store, client = make_tools()
        try:
            self._collect(tools, ["000001", FUND_CODE])
            out = AnalyzerNode(store)(_comparison_state(["000001", FUND_CODE]))

            pc = out["analysis"].peer_comparison
            # rows 补齐区间 / 累计收益 / 净值口径；对齐窗口截断至 10 年（2016 首点被切）
            assert pc.rows[0].period_start == date(2020, 1, 2)
            assert pc.rows[0].nav_point_count == 2
            assert pc.rows[0].cumulative_return == pytest.approx(5.7559 / 2.1 - 1)
            assert pc.rows[0].nav_basis == "acc"

            # 集中度：两基金同持仓（3.12 + 2.85），holding_count=2
            assert [c.fund_id for c in pc.concentration] == ["000001", FUND_CODE]
            assert all(c.top10_sum == 3.12 + 2.85 for c in pc.concentration)
            assert all(c.holding_count == 2 for c in pc.concentration)

            # 重叠：同一份持仓 → Jaccard 1.0
            assert len(pc.overlaps) == 1
            assert pc.overlaps[0].overlap_ratio == 1.0
            assert pc.overlaps[0].common_names == ["宁德时代", "贵州茅台"]

            # Evidence：2 条指标 + 2 条持仓分析 + 1 条重叠
            assert len(out["evidence"]) == 5
            kinds = {e.value.get("metric") for e in out["evidence"] if e.value.get("metric")}
            assert kinds == {"holdings_metrics", "holdings_overlap"}
            assert out["data_quality_issues"] == []
        finally:
            client.close()

    def test_research_with_peers_gets_holdings_metrics(self):
        tools, store, client = make_tools()
        try:
            self._collect(tools, ["000001", FUND_CODE])
            state = {
                "fund_ids": ["000001", FUND_CODE],
                "research_plan": {
                    "task_type": "fund_research",
                    "primary_fund_id": "000001",
                    "fund_ids": ["000001", FUND_CODE],
                    "notes": [],
                },
            }
            out = AnalyzerNode(store)(state)

            pc = out["analysis"].peer_comparison
            assert pc is not None
            # PeerComparison 持仓维度仅对比任务填充；research 走 holdings_metrics
            assert pc.concentration == []
            assert pc.overlaps == []
            # 集中度与市场分布对 research 同样计算（每基金一条持仓分析 Evidence）
            metrics = {m.fund_id: m for m in out["analysis"].holdings_metrics}
            assert set(metrics) == {"000001", FUND_CODE}
            assert all(m.top10_sum == 3.12 + 2.85 for m in metrics.values())
            assert all(m.market_split.a_share_ratio == 3.12 + 2.85 for m in metrics.values())
            # 2 条指标 Evidence + 2 条持仓分析 Evidence
            assert len(out["evidence"]) == 4
        finally:
            client.close()

    def test_comparison_without_holdings_flags_issue(self):
        # 空 store：对比任务但无任何持仓数据 → 披露而非编造
        out = AnalyzerNode(FundStore())(_comparison_state(["000001", FUND_CODE]))
        assert any("持仓数据缺失" in i for i in out["data_quality_issues"])
        # 全部持仓缺失 → 不产生持仓 Evidence
        assert all(e.value.get("metric") is None for e in out["evidence"])
