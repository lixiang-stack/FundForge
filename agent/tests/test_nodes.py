"""节点单元测试：Planner 提取与 Collector 节点行为。"""

from tests.conftest import FUND_CODE, make_tools
from nodes.collector import CollectorNode
from nodes.planner import PlannerNode, extract_fund_codes
from nodes.router import RouterNode
from domain.task_type import TaskType


class TestPlanner:
    def test_extracts_fund_codes(self):
        assert extract_fund_codes("分析基金 519770 是否适合长期持有") == [FUND_CODE]

    def test_extracts_multiple_codes_dedup_preserving_order(self):
        assert extract_fund_codes("对比 000001 和 519770，重点看 000001") == ["000001", FUND_CODE]

    def test_ignores_non_6_digit_numbers(self):
        assert extract_fund_codes("基金代码 5197701 或 12345 都无效") == []

    def test_no_code_yields_empty_plan_with_note(self):
        result = PlannerNode()({"user_query": "帮我推荐基金"})
        plan = result["research_plan"]
        assert plan.fund_ids == []
        assert plan.primary_fund_id is None
        assert plan.notes


class TestPlannerPrimary:
    def test_first_code_is_primary(self):
        result = PlannerNode()({"user_query": "对比 000001 和 519770"})
        plan = result["research_plan"]
        assert plan.fund_ids == ["000001", "519770"]
        assert plan.primary_fund_id == "000001"


class TestRouterClassification:
    def test_pure_comparison_intent(self):
        out = RouterNode()({"user_query": "000001 和 519770 哪个好"})
        assert out["task_type"] == TaskType.FUND_COMPARISON

    def test_analysis_intent_with_comparison_is_research(self):
        # 「分析A并与B比较」= 带 peer 的 fund_research（V1 核心 Case）
        out = RouterNode()({"user_query": "分析基金 519770 是否适合长期持有，并与 000001 比较"})
        assert out["task_type"] == TaskType.FUND_RESEARCH

    def test_plain_analysis_intent(self):
        out = RouterNode()({"user_query": "分析基金 519770"})
        assert out["task_type"] == TaskType.FUND_RESEARCH


class TestPlannerTaskType:
    def test_comparison_task_with_two_codes(self):
        state = {"user_query": "000001 和 519770 哪个好", "task_type": TaskType.FUND_COMPARISON}
        out = PlannerNode()(state)
        assert out["task_type"] == TaskType.FUND_COMPARISON
        plan = out["research_plan"]
        assert plan.task_type == TaskType.FUND_COMPARISON
        assert plan.primary_fund_id == "000001"
        assert plan.peer_fund_ids == ["519770"]
        assert out["peer_fund_ids"] == ["519770"]

    def test_comparison_downgraded_when_single_code(self):
        state = {"user_query": "对比 519770", "task_type": TaskType.FUND_COMPARISON}
        out = PlannerNode()(state)
        assert out["task_type"] == TaskType.FUND_RESEARCH
        plan = out["research_plan"]
        assert plan.task_type == TaskType.FUND_RESEARCH
        assert plan.peer_fund_ids == []
        assert any("不足 2 只" in n for n in plan.notes)

    def test_research_with_peers_records_note(self):
        out = PlannerNode()({"user_query": "分析基金 519770，并与 000001、005827 比较"})
        assert out["task_type"] == TaskType.FUND_RESEARCH
        plan = out["research_plan"]
        assert plan.primary_fund_id == "519770"
        assert plan.peer_fund_ids == ["000001", "005827"]
        assert any("对比基金" in n for n in plan.notes)


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

            # 至少 1 条 Evidence（info + performance + holdings 共 3 条）
            assert len(out["evidence"]) == 3
            types = {e.evidence_type for e in out["evidence"]}
            assert types == {"fund_data"}
            assert all(e.raw_ref for e in out["evidence"])

            # ToolCallRecord：info + performance + holdings 各一次，全部成功
            assert len(out["tool_calls"]) == 3
            assert all(t.success for t in out["tool_calls"])
            assert {t.tool_name for t in out["tool_calls"]} == {
                "get_fund_info",
                "get_fund_performance",
                "get_fund_holdings",
            }

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
            assert len(out["tool_calls"]) == 3
            assert all(not t.success for t in out["tool_calls"])
            assert all(t.error for t in out["tool_calls"])
            assert any("完全失败" in i for i in out["data_quality_issues"])
        finally:
            client.close()
