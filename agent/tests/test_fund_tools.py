"""Fund Tools 单元测试（Phase 1 验收：Tool 返回格式正确 + data_quality 标记）。"""

from datetime import date

from tests.conftest import FUND_CODE, make_tools


class TestGetFundInfo:
    def test_returns_structured_fund(self, tools_and_store):
        tools, store = tools_and_store
        fund = tools.get_fund_info.invoke({"fund_id": FUND_CODE})

        assert fund.id == FUND_CODE
        assert fund.name == "交银优择回报A"
        assert fund.fund_type == "混合型-灵活配置"
        assert fund.manager_name == "周珊珊 高扬"
        assert fund.company == "交银施罗德基金公司"
        assert fund.inception_date == date(2016, 4, 22)
        assert fund.aum == 44.16
        assert fund.currency == "CNY"
        assert fund.data_quality == "complete"
        assert fund.source.endswith(f"/api/funds/{FUND_CODE}/detail")
        assert fund.as_of is not None

    def test_writes_full_data_to_store(self, tools_and_store):
        tools, store = tools_and_store
        tools.get_fund_info.invoke({"fund_id": FUND_CODE})
        assert store.get_fund(FUND_CODE) is not None
        assert store.fund_ref(FUND_CODE) == f"store:funds/{FUND_CODE}"

    def test_empty_detail_marks_missing(self):
        tools, store, client = make_tools(detail_rows=[])
        try:
            fund = tools.get_fund_info.invoke({"fund_id": FUND_CODE})
            assert fund.data_quality == "missing"
        finally:
            client.close()

    def test_partial_fields_mark_partial(self):
        partial = [{"item": "基金代码", "value": FUND_CODE}, {"item": "基金名称", "value": "某基金"}]
        tools, _, client = make_tools(detail_rows=partial)
        try:
            fund = tools.get_fund_info.invoke({"fund_id": FUND_CODE})
            assert fund.data_quality == "partial"
            assert fund.fund_type is None
        finally:
            client.close()


class TestGetFundPerformance:
    def test_returns_structured_performance(self, tools_and_store):
        tools, store = tools_and_store
        perf = tools.get_fund_performance.invoke({"fund_id": FUND_CODE})

        assert perf.fund_id == FUND_CODE
        assert perf.period_start == date(2016, 4, 22)
        assert perf.period_end == date(2026, 9, 8)
        assert perf.nav_point_count == 3
        # Phase 1 不计算指标（Phase 2 Analyzer 负责）
        assert perf.cumulative_return is None
        assert perf.volatility is None
        assert perf.max_drawdown is None
        assert perf.sharpe is None
        assert perf.data_quality == "complete"

    def test_merges_unit_and_acc_nav_into_store(self, tools_and_store):
        tools, store = tools_and_store
        tools.get_fund_performance.invoke({"fund_id": FUND_CODE})

        points = store.get_nav_series(FUND_CODE)
        assert len(points) == 3
        assert points[0].unit_nav == 1.0
        assert points[0].acc_nav == 1.0
        assert points[-1].daily_return == -0.65

    def test_date_range_filter(self, tools_and_store):
        tools, store = tools_and_store
        perf = tools.get_fund_performance.invoke(
            {"fund_id": FUND_CODE, "start_date": "2020-01-01", "end_date": "2024-12-31"}
        )
        assert perf.period_start == date(2020, 1, 2)
        assert perf.period_end == date(2020, 1, 2)
        assert perf.nav_point_count == 1
        assert len(store.get_nav_series(FUND_CODE)) == 1

    def test_empty_series_marks_missing(self):
        tools, _, client = make_tools(unit_rows=[], acc_rows=[])
        try:
            perf = tools.get_fund_performance.invoke({"fund_id": FUND_CODE})
            assert perf.data_quality == "missing"
            assert perf.period_start is None
            assert perf.nav_point_count == 0
        finally:
            client.close()


class TestSearchFunds:
    def test_search_by_code(self, tools_and_store):
        tools, _ = tools_and_store
        results = tools.search_funds.invoke({"query": "519770"})
        assert len(results) == 1
        assert results[0].id == FUND_CODE
        assert results[0].name == "交银优择回报A"
        assert results[0].data_quality == "complete"

    def test_search_by_pinyin_case_insensitive(self, tools_and_store):
        tools, _ = tools_and_store
        results = tools.search_funds.invoke({"query": "jyyz"})
        assert len(results) == 1
        assert results[0].id == FUND_CODE

    def test_search_respects_limit(self, tools_and_store):
        tools, _ = tools_and_store
        results = tools.search_funds.invoke({"query": "混合", "limit": 1})
        assert len(results) == 1

    def test_search_no_match_returns_empty(self, tools_and_store):
        tools, _ = tools_and_store
        assert tools.search_funds.invoke({"query": "不存在999"}) == []
