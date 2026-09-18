"""domain.fund 报告期解析 / top_holdings 纯函数测试（P0 持仓时效）。"""

from domain.fund import Holding, latest_report_period, parse_report_period, top_holdings


def _h(code: str, ratio: float | None, period: str | None) -> Holding:
    return Holding(stock_code=code, stock_name=code, hold_ratio=ratio, report_date=period)


class TestParseReportPeriod:
    def test_akshare_quarter_string(self):
        assert parse_report_period("2024年1季度股票投资明细") == (2024, 1)
        assert parse_report_period("2026年4季度") == (2026, 4)

    def test_none_or_unparseable_returns_none(self):
        assert parse_report_period(None) is None
        assert parse_report_period("") is None
        # 合同漂移期的旧日期格式不是季度原文，解析不出（宁缺勿编）
        assert parse_report_period("2025-06-30") is None


class TestLatestReportPeriod:
    def test_multi_quarter_picks_latest(self):
        holdings = [
            _h("1", 1.0, "2024年1季度股票投资明细"),
            _h("2", 1.0, "2024年4季度股票投资明细"),
            _h("3", 1.0, "2024年2季度股票投资明细"),
        ]
        assert latest_report_period(holdings) == "2024年4季度股票投资明细"

    def test_no_period_returns_none(self):
        assert latest_report_period([_h("1", 1.0, None)]) is None
        assert latest_report_period([]) is None


class TestTopHoldings:
    def test_latest_quarter_only_sorted_desc(self):
        holdings = [
            _h("A", 1.0, "2024年1季度股票投资明细"),
            _h("B", 5.0, "2024年2季度股票投资明细"),
            _h("C", 3.0, "2024年2季度股票投资明细"),
            _h("D", None, "2024年2季度股票投资明细"),
        ]
        top = top_holdings(holdings)
        # 最新季度 + 降序 + None 排最后；旧季度行不混入
        assert [h.stock_code for h in top] == ["B", "C", "D"]

    def test_limit_n(self):
        holdings = [_h(str(i), float(i), "2024年1季度股票投资明细") for i in range(20)]
        assert len(top_holdings(holdings, n=10)) == 10
        assert top_holdings(holdings)[0].stock_code == "19"

    def test_unparseable_periods_treat_all_rows_as_one_bucket(self):
        holdings = [_h("A", 2.0, "2025-06-30"), _h("B", 1.0, "2025-06-30")]
        assert [h.stock_code for h in top_holdings(holdings)] == ["A", "B"]
