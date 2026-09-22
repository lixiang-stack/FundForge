"""Fund Tools 单元测试（Phase 1 验收：Tool 返回格式正确 + data_quality 标记）。"""

from datetime import date, datetime

import httpx

from tests.conftest import FUND_CODE, make_tools, make_transport
from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools


class TestGetFundInfo:
    def test_returns_structured_fund(self, tools_and_store):
        tools, store = tools_and_store
        fund = tools.get_fund_info.invoke({"fund_id": FUND_CODE})

        assert fund.id == FUND_CODE
        assert fund.name == "交银优择回报A"
        assert fund.full_name == "交银施罗德优择回报灵活配置混合型证券投资基金"
        assert fund.fund_type == "混合型-灵活配置"
        assert fund.manager_name == "周珊珊 高扬"
        assert fund.company == "交银施罗德基金公司"
        assert fund.custodian == "中信银行股份有限公司"
        assert fund.benchmark == "50%×沪深300指数收益率+50%×中债综合全价指数收益率"
        assert fund.inception_date == date(2016, 4, 22)
        assert fund.aum == 44.16
        assert fund.currency == "CNY"
        assert fund.rating_agency is None
        assert fund.rating == "暂无评级"
        assert fund.investment_strategy is not None
        assert fund.investment_objective is not None
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
        partial = [{"item": "fund_code", "value": FUND_CODE}, {"item": "fund_name", "value": "某基金"}]
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

    def test_duplicate_nav_dates_are_deduped(self):
        # akshare 偶发同日重复行：虚增点数并在收益序列插入伪收益，必须按日期去重
        unit_rows = [
            {"nav_date": "2024-01-02", "unit_nav": 1.0, "daily_return": 0.0},
            {"nav_date": "2024-01-03", "unit_nav": 1.1, "daily_return": 1.0},
            {"nav_date": "2024-01-03", "unit_nav": 1.2, "daily_return": 0.9},
            {"nav_date": "2024-01-04", "unit_nav": 1.21, "daily_return": 0.1},
        ]
        tools, store, client = make_tools(unit_rows=unit_rows)
        try:
            perf = tools.get_fund_performance.invoke({"fund_id": FUND_CODE})
            assert perf.nav_point_count == 3
            assert perf.period_start == date(2024, 1, 2)
            assert perf.period_end == date(2024, 1, 4)
            points = store.get_nav_series(FUND_CODE)
            assert [p.unit_nav for p in points] == [1.0, 1.2, 1.21]  # 同日保留末行
        finally:
            client.close()

    def test_empty_series_marks_missing(self):
        tools, _, client = make_tools(unit_rows=[], acc_rows=[])
        try:
            perf = tools.get_fund_performance.invoke({"fund_id": FUND_CODE})
            assert perf.data_quality == "missing"
            assert perf.period_start is None
            assert perf.nav_point_count == 0
        finally:
            client.close()


class TestGetFundIndustryAlloc:
    def test_returns_structured_rows(self, tools_and_store):
        tools, store = tools_and_store
        rows = tools.get_fund_industry_alloc.invoke({"fund_id": FUND_CODE})

        assert len(rows) == 2
        assert rows[0].industry == "制造业"
        assert rows[0].nav_ratio == 68.96
        assert rows[0].report_date == "2026-06-30"
        assert len(store.get_industry(FUND_CODE)) == 2
        assert store.industry_ref(FUND_CODE) == f"store:industry/{FUND_CODE}"

    def test_empty_industry_returns_empty(self):
        tools, store, client = make_tools(industry_rows=[])
        try:
            rows = tools.get_fund_industry_alloc.invoke({"fund_id": FUND_CODE})
            assert rows == []
            assert store.get_industry(FUND_CODE) == []
        finally:
            client.close()


class TestGetFundAssetAllocation:
    def test_explicit_date_passes_through(self, tools_and_store):
        tools, store = tools_and_store
        rows = tools.get_fund_asset_allocation.invoke({"fund_id": FUND_CODE, "date": "20260630"})

        assert len(rows) == 3
        assert rows[0].asset_type == "股票"
        assert rows[0].percent == 94.18
        assert len(store.get_allocation(FUND_CODE)) == 3

    def test_date_defaults_to_latest_holdings_period(self):
        # 缺省 date 取股票持仓最新报告期对应的财报月末（1 季度 → 0331）
        transport = make_transport()
        captured: dict = {}
        original = transport.handler

        def spy(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/allocation"):
                captured["date"] = request.url.params.get("date")
            return original(request)

        transport.handler = spy
        client = CollectorClient(base_url="http://collector.test", transport=transport)
        store = FundStore()
        tools = make_fund_tools(client, store)
        try:
            tools.get_fund_holdings.invoke({"fund_id": FUND_CODE})
            rows = tools.get_fund_asset_allocation.invoke({"fund_id": FUND_CODE})
            assert rows
            assert captured["date"] == f"{datetime.now().year}0331"
        finally:
            client.close()

    def test_no_holdings_period_returns_empty(self):
        # 无持仓报告期可依据 → 不编造日期，返回空列表
        tools, store, client = make_tools()
        try:
            rows = tools.get_fund_asset_allocation.invoke({"fund_id": FUND_CODE})
            assert rows == []
            assert store.get_allocation(FUND_CODE) == []
        finally:
            client.close()


class TestGetFundFees:
    def test_returns_structured_fees(self, tools_and_store):
        tools, store = tools_and_store
        fees = tools.get_fund_fees.invoke({"fund_id": FUND_CODE})

        assert fees.management_fee_rate == 1.0
        assert fees.custodian_fee_rate == 0.15
        assert fees.service_fee_rate == 0.0
        assert store.get_fees(FUND_CODE) == fees
        assert store.fees_ref(FUND_CODE) == f"store:fees/{FUND_CODE}"

    def test_empty_fees_gives_none_fields(self):
        tools, store, client = make_tools(fees_rows=[])
        try:
            fees = tools.get_fund_fees.invoke({"fund_id": FUND_CODE})
            assert fees.management_fee_rate is None
            assert fees.custodian_fee_rate is None
            assert fees.service_fee_rate is None
        finally:
            client.close()


class TestGetFundAchievement:
    def test_returns_structured_rows(self, tools_and_store):
        tools, store = tools_and_store
        rows = tools.get_fund_achievement.invoke({"fund_id": FUND_CODE})

        assert len(rows) == 2
        assert rows[0].performance_type == "年度业绩"
        assert rows[0].period == "成立以来"
        assert rows[0].return_rate == 53.44
        assert rows[0].max_drawdown == 27.6
        assert rows[0].category_rank == "308/1070"
        assert len(store.get_achievement(FUND_CODE)) == 2
        assert store.achievement_ref(FUND_CODE) == f"store:achievement/{FUND_CODE}"

    def test_empty_achievement_returns_empty(self):
        tools, store, client = make_tools(achievement_rows=[])
        try:
            assert tools.get_fund_achievement.invoke({"fund_id": FUND_CODE}) == []
            assert store.get_achievement(FUND_CODE) == []
        finally:
            client.close()


class TestGetFundRating:
    def test_returns_structured_rating(self, tools_and_store):
        tools, store = tools_and_store
        ratings = tools.get_fund_rating.invoke({"fund_id": FUND_CODE})

        assert len(ratings) == 1
        assert ratings[0].fund_code == FUND_CODE
        assert ratings[0].five_star_count == 2
        assert ratings[0].rating_sh == 4.0
        assert ratings[0].rating_zs == 5.0
        assert ratings[0].rating_ja == 4.0
        assert ratings[0].rating_mx == 5.0
        assert len(store.get_rating(FUND_CODE)) == 1
        assert store.rating_ref(FUND_CODE) == f"store:rating/{FUND_CODE}"

    def test_no_rating_returns_empty(self):
        tools, store, client = make_tools(rating_rows=[])
        try:
            ratings = tools.get_fund_rating.invoke({"fund_id": FUND_CODE})
            assert ratings == []
            assert store.get_rating(FUND_CODE) == []
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
