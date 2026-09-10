"""节点单元测试：Planner 提取与 Collector 节点行为。"""

from tests.conftest import FUND_CODE, make_tools
from nodes.collector import CollectorNode
from nodes.planner import extract_fund_codes, planner


class TestPlanner:
    def test_extracts_fund_codes(self):
        assert extract_fund_codes("分析基金 519770 是否适合长期持有") == [FUND_CODE]

    def test_extracts_multiple_codes_dedup_preserving_order(self):
        assert extract_fund_codes("对比 000001 和 519770，重点看 000001") == ["000001", FUND_CODE]

    def test_ignores_non_6_digit_numbers(self):
        assert extract_fund_codes("基金代码 5197701 或 12345 都无效") == []

    def test_no_code_yields_empty_plan_with_note(self):
        result = planner({"user_query": "帮我推荐基金"})
        plan = result["research_plan"]
        assert plan.fund_ids == []
        assert plan.notes


class TestCollectorNode:
    def _node(self):
        tools, store, client = make_tools()
        return CollectorNode(tools), store, client

    def test_collects_summary_evidence_and_records(self):
        node, store, client = self._node()
        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {"task_type": "fund_research", "fund_ids": [FUND_CODE], "notes": []},
            }
            out = node(state)

            assert out["fund_ids"] == [FUND_CODE]
            assert len(out["funds_summary"]) == 1
            summary = out["funds_summary"][0]
            assert summary.id == FUND_CODE
            assert summary.name == "交银优择回报A"

            # 至少 1 条 Evidence（info + performance 共 2 条）
            assert len(out["evidence"]) == 2
            types = {e.evidence_type for e in out["evidence"]}
            assert types == {"fund_data"}
            assert all(e.raw_ref for e in out["evidence"])

            # ToolCallRecord：info + performance 各一次，全部成功
            assert len(out["tool_calls"]) == 2
            assert all(t.success for t in out["tool_calls"])
            assert {t.tool_name for t in out["tool_calls"]} == {"get_fund_info", "get_fund_performance"}

            # 完整数据写入外部 Store
            assert store.get_fund(FUND_CODE) is not None
            assert len(store.get_nav_series(FUND_CODE)) == 3

            assert out["data_quality_issues"] == []
        finally:
            client.close()

    def test_empty_plan_reports_issue(self):
        node, _, client = self._node()
        try:
            out = node({"user_query": "无代码"})
            assert out["fund_ids"] == []
            assert out["funds_summary"] == []
            assert out["evidence"] == []
            assert out["data_quality_issues"]
        finally:
            client.close()

    def test_collector_failure_degrades_and_records(self):
        # collector 全部返回 500 → 记录失败且不产生摘要
        tools, store, client = make_tools(status=500)
        node = CollectorNode(tools)
        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {"task_type": "fund_research", "fund_ids": [FUND_CODE], "notes": []},
            }
            out = node(state)
            assert out["funds_summary"] == []
            assert len(out["tool_calls"]) == 2
            assert all(not t.success for t in out["tool_calls"])
            assert all(t.error for t in out["tool_calls"])
            assert any("完全失败" in i for i in out["data_quality_issues"])
        finally:
            client.close()
