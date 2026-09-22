"""节点单元测试：Planner 提取与 Collector 节点行为。"""

import threading
import time
from datetime import datetime

import httpx

from tests.conftest import FUND_CODE, make_tools, make_transport
from nodes.collector import CollectorNode
from nodes.planner import PlannerNode, extract_fund_codes
from nodes.router import RouterNode
from domain.task_type import TaskType
from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools


class _TrackingTransport(httpx.BaseTransport):
    """包装内层 transport，统计最大并发在途请求数（验证 Tool 级并发）。"""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            # mock 请求本身过快，留出重叠窗口才能观测到并发
            time.sleep(0.05)
            return self._inner.handle_request(request)
        finally:
            with self._lock:
                self._in_flight -= 1


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

            # info/performance/holdings/行业配置/资产配置/费率/业绩排名/评级 各 1 条 + 基准指数 1 条
            assert len(out["evidence"]) == 9
            types = {e.evidence_type for e in out["evidence"]}
            assert types == {"fund_data"}
            assert all(e.raw_ref for e in out["evidence"])

            # ToolCallRecord：8 个基金 Tool + 1 个基准指数 Tool，全部成功
            assert len(out["tool_calls"]) == 9
            assert all(t.success for t in out["tool_calls"])
            assert {t.tool_name for t in out["tool_calls"]} == {
                "get_fund_info",
                "get_fund_performance",
                "get_fund_holdings",
                "get_fund_industry_alloc",
                "get_fund_asset_allocation",
                "get_fund_fees",
                "get_fund_achievement",
                "get_fund_rating",
                "get_index_data",
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

    def test_tools_within_fund_run_concurrently(self):
        tracking = _TrackingTransport(make_transport())
        client = CollectorClient(base_url="http://collector.test", transport=tracking)
        node = CollectorNode(make_fund_tools(client, FundStore()))
        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {"task_type": "fund_research", "fund_ids": [FUND_CODE], "notes": []},
            }
            out = node(state)

            assert len(out["tool_calls"]) == 9
            assert all(t.success for t in out["tool_calls"])
            # 多个 Tool 并发执行：在途峰值应 ≥ 2（顺序执行恒为 1）
            assert tracking.max_in_flight >= 2
        finally:
            client.close()

    def test_multi_fund_result_order_preserved(self):
        node, _, client = self._node()
        try:
            state = {
                "user_query": f"对比 {FUND_CODE} 和 000001",
                "research_plan": {
                    "task_type": "fund_research",
                    "fund_ids": [FUND_CODE, "000001"],
                    "notes": [],
                },
            }
            out = node(state)

            assert out["fund_ids"] == [FUND_CODE, "000001"]
            assert [s.id for s in out["funds_summary"]] == [FUND_CODE, "000001"]
            # 并发不改变记录顺序：先第一只基金的 8 次调用，再第二只；指数调用附于其后
            fund_calls = [t for t in out["tool_calls"] if t.arguments.get("fund_id")]
            index_calls = [t for t in out["tool_calls"] if t.tool_name == "get_index_data"]
            assert [t.arguments["fund_id"] for t in fund_calls] == [FUND_CODE] * 8 + ["000001"] * 8
            assert [t.tool_name for t in index_calls] == ["get_index_data"]
        finally:
            client.close()

    def test_holdings_evidence_latest_period_and_top10(self):
        year = datetime.now().year
        rows = [
            # 旧季度行：不得混入 top_holdings
            {"stock_code": "600519", "stock_name": "贵州茅台", "hold_ratio": 9.9,
             "report_date": f"{year - 1}年4季度股票投资明细"},
            # 最新报告期 12 行：验证取前 10 且按权重降序
            *[
                {"stock_code": f"{i:06d}", "stock_name": f"s{i}", "hold_ratio": float(i),
                 "report_date": f"{year}年1季度股票投资明细"}
                for i in range(12)
            ],
        ]
        tools, store, client = make_tools(holdings_rows=rows)
        node = CollectorNode(tools)
        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {"task_type": "fund_research", "fund_ids": [FUND_CODE], "notes": []},
            }
            out = node(state)

            holdings_ev = [e for e in out["evidence"] if "holdings" in e.source][0]
            assert holdings_ev.value["latest_report_period"] == f"{year}年1季度股票投资明细"
            assert f"最新报告期 {year}年1季度" in holdings_ev.source_detail
            top = holdings_ev.value["top_holdings"]
            assert len(top) == 10
            assert top[0]["stock_name"] == "s11"  # 最新季度内权重最高
            assert all(h["stock_name"] != "贵州茅台" for h in top)
        finally:
            client.close()

    def test_stale_holdings_report_period_raises_issue(self):
        tools, store, client = make_tools(
            holdings_rows=[
                {"stock_code": "600519", "stock_name": "贵州茅台", "hold_ratio": 1.0,
                 "report_date": "2020年1季度股票投资明细"},
            ]
        )
        node = CollectorNode(tools)
        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {"task_type": "fund_research", "fund_ids": [FUND_CODE], "notes": []},
            }
            out = node(state)
            assert any("非当前年度披露" in i for i in out["data_quality_issues"])
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
            assert len(out["tool_calls"]) == 8
            # 7 个直连 collector 的 Tool 全部失败；资产配置因无持仓报告期依据
            # 短路返回空列表（未发起请求），属正常降级
            failed = [t for t in out["tool_calls"] if not t.success]
            succeeded = [t for t in out["tool_calls"] if t.success]
            assert len(failed) == 7
            assert all(t.error for t in failed)
            assert [t.tool_name for t in succeeded] == ["get_fund_asset_allocation"]
            assert any("完全失败" in i for i in out["data_quality_issues"])
        finally:
            client.close()
