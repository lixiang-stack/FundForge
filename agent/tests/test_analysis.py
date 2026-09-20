"""Analysis Engine 单元测试（Phase 2 验收：给定净值序列，计算结果可复现）。

期望值全部手算推导，不通过被测函数生成（避免循环验证）。
"""

import math
from datetime import date

import pytest

from analysis.engine import (
    annualized_return,
    annualized_volatility,
    compute_fund_metrics,
    cumulative_return,
    fund_concentration,
    holdings_overlap,
    max_drawdown,
    nav_value,
    sharpe_ratio,
    simple_returns,
)
from domain.fund import Holding, NAVPoint


def _point(d: str, unit: float | None = None, acc: float | None = None) -> NAVPoint:
    return NAVPoint(nav_date=date.fromisoformat(d), unit_nav=unit, acc_nav=acc)


def _h(name: str, ratio: float | None, period: str = "2026年2季度股票投资明细") -> Holding:
    return Holding(stock_code=f"c-{name}", stock_name=name, hold_ratio=ratio, report_date=period)


class TestSimpleReturns:
    def test_basic(self):
        assert simple_returns([1.0, 2.0, 2.5]) == [1.0, 0.25]

    def test_single_value_gives_empty(self):
        assert simple_returns([1.0]) == []

    def test_skips_zero_denominator(self):
        # 前值为 0 的点无法计算收益，跳过
        assert simple_returns([0.0, 1.0, 2.0]) == [1.0]


class TestCumulativeReturn:
    def test_basic(self):
        assert cumulative_return([1.0, 1.1, 1.21]) == pytest.approx(0.21)

    def test_loss(self):
        assert cumulative_return([2.0, 1.0]) == pytest.approx(-0.5)

    def test_insufficient_points(self):
        assert cumulative_return([1.0]) is None


class TestAnnualizedReturn:
    def test_one_year(self):
        # 2023-01-01 → 2024-01-01 恰好 365 天，1.0 → 1.1 → 年化 10%
        assert annualized_return([1.0, 1.1], 365) == pytest.approx(0.10)

    def test_two_years(self):
        # 730 天翻 1.21 倍 → 年化 10%
        assert annualized_return([1.0, 1.21], 730) == pytest.approx(0.10, rel=1e-9)

    def test_short_period_not_annualized(self):
        assert annualized_return([1.0, 1.1], 29) is None

    def test_insufficient_points(self):
        assert annualized_return([1.0], 365) is None


class TestAnnualizedVolatility:
    def test_two_symmetric_returns(self):
        # r = [+0.1, -0.1]，pstdev = 0.1 → 年化 = 0.1 * sqrt(252)
        assert annualized_volatility([0.1, -0.1]) == pytest.approx(0.1 * math.sqrt(252))

    def test_constant_returns(self):
        # 波动为 0（非 None）：收益恒定 → pstdev = 0 → 年化波动 0
        assert annualized_volatility([0.01, 0.01]) == 0.0

    def test_insufficient_returns(self):
        assert annualized_volatility([0.01]) is None


class TestMaxDrawdown:
    def test_known_drawdown(self):
        # 峰值 2.0 → 谷值 0.5 → 回撤 -75%
        assert max_drawdown([1.0, 2.0, 1.0, 0.5]) == pytest.approx(-0.75)

    def test_monotonic_up_has_zero_drawdown(self):
        assert max_drawdown([1.0, 2.0, 3.0]) == 0.0

    def test_multiple_peaks_takes_worst(self):
        # 两次回撤：-50% 和 -80%，取最差
        assert max_drawdown([1.0, 2.0, 1.0, 5.0, 1.0]) == pytest.approx(-0.8)

    def test_insufficient_points(self):
        assert max_drawdown([1.0]) is None


class TestSharpe:
    def test_zero_mean_returns(self):
        # r = [+0.01, -0.01]，mean = 0 → 夏普 0
        assert sharpe_ratio([0.01, -0.01]) == 0.0

    def test_known_ratio(self):
        # r = [0.01, 0.03]：mean = 0.02，pstdev = 0.01 → 夏普 = 2 * sqrt(252)
        assert sharpe_ratio([0.01, 0.03]) == pytest.approx(2 * math.sqrt(252))

    def test_zero_volatility_gives_none(self):
        assert sharpe_ratio([0.02, 0.02]) is None

    def test_with_risk_free(self):
        # r = [0.03, 0.03+0.02]，rf = 0.01 → excess = [0.02, 0.02]... 用非对称序列验证平移
        # r = [0.01, 0.03], rf = 0.01 → excess = [0.0, 0.02], mean = 0.01, pstdev(excess) = 0.01
        assert sharpe_ratio([0.01, 0.03], risk_free_daily=0.01) == pytest.approx(math.sqrt(252))

    def test_insufficient_returns(self):
        assert sharpe_ratio([0.01]) is None


class TestNavValue:
    def test_acc_basis_returns_acc(self):
        assert nav_value(_point("2024-01-01", unit=1.0, acc=1.5), "acc") == 1.5

    def test_acc_basis_missing_acc_is_none(self):
        # 指定 acc 口径时缺失即无效点，不做逐点回退
        assert nav_value(_point("2024-01-01", unit=1.0), "acc") is None

    def test_unit_basis_returns_unit(self):
        assert nav_value(_point("2024-01-01", unit=1.0, acc=1.5), "unit") == 1.0

    def test_both_none(self):
        assert nav_value(_point("2024-01-01"), "unit") is None


class TestComputeFundMetrics:
    def test_complete_series(self):
        points = [
            _point("2023-01-01", unit=1.0, acc=1.0),
            _point("2023-06-01", unit=1.2, acc=1.3),
            _point("2024-01-01", unit=1.1, acc=1.21),
        ]
        m = compute_fund_metrics(points)
        # acc 全覆盖 → acc 口径：序列 [1.0, 1.3, 1.21]
        assert m.nav_basis == "acc"
        assert m.period_start == date(2023, 1, 1)
        assert m.period_end == date(2024, 1, 1)
        assert m.nav_point_count == 3
        assert m.cumulative_return == pytest.approx(0.21)
        # 2023-01-01 → 2024-01-01 恰好 365 天，累计 21% → 年化 21%
        assert m.annualized_return == pytest.approx(0.21, rel=1e-9)
        # 峰值 1.3 → 末值 1.21 → 回撤 1.21/1.3 - 1
        assert m.max_drawdown == pytest.approx(1.21 / 1.3 - 1)
        assert m.data_quality == "complete"

    def test_single_point_is_partial(self):
        m = compute_fund_metrics([_point("2024-01-01", unit=1.0)])
        assert m.data_quality == "partial"
        assert m.cumulative_return is None
        assert m.annualized_return is None

    def test_empty_is_missing(self):
        m = compute_fund_metrics([])
        assert m.data_quality == "missing"
        assert m.period_start is None

    def test_ignores_none_nav_points(self):
        points = [
            _point("2024-01-01"),
            _point("2023-01-01", unit=1.0),
            _point("2024-01-01", unit=1.1),
        ]
        m = compute_fund_metrics(points)
        assert m.nav_point_count == 2
        assert m.data_quality == "complete"


class TestComputeFundMetricsBasis:
    def test_auto_full_acc_coverage_uses_acc(self):
        points = [
            _point("2023-01-01", unit=1.0, acc=1.0),
            _point("2024-01-01", unit=1.2, acc=1.44),
        ]
        m = compute_fund_metrics(points)
        assert m.nav_basis == "acc"
        assert m.cumulative_return == pytest.approx(0.44)

    def test_auto_partial_acc_falls_back_to_unit_whole_series(self):
        # acc 部分缺失 → 整序列回退 unit，不与 acc 逐点混用
        points = [
            _point("2023-01-01", unit=1.0),
            _point("2024-01-01", unit=1.2, acc=1.5),
        ]
        m = compute_fund_metrics(points)
        assert m.nav_basis == "unit"
        assert m.cumulative_return == pytest.approx(0.2)

    def test_forced_unit_ignores_acc(self):
        points = [
            _point("2023-01-01", unit=1.0, acc=1.0),
            _point("2024-01-01", unit=1.2, acc=1.5),
        ]
        m = compute_fund_metrics(points, basis="unit")
        assert m.nav_basis == "unit"
        assert m.cumulative_return == pytest.approx(0.2)

    def test_auto_acc_covered_despite_unit_gaps(self):
        # acc 全覆盖（部分点 unit 缺失）→ acc 口径，这些点仍有效
        points = [
            _point("2023-01-01", acc=1.0),
            _point("2024-01-01", unit=1.2, acc=1.5),
        ]
        m = compute_fund_metrics(points)
        assert m.nav_basis == "acc"
        assert m.nav_point_count == 2
        assert m.data_quality == "complete"

    def test_acc_only_points_dropped_under_forced_unit(self):
        # 强制 unit 口径时，仅 acc 存在的点为无效点
        points = [
            _point("2023-01-01", acc=1.0),
            _point("2024-01-01", unit=1.2, acc=1.5),
        ]
        m = compute_fund_metrics(points, basis="unit")
        assert m.nav_basis == "unit"
        assert m.nav_point_count == 1
        assert m.data_quality == "partial"


class TestFundConcentration:
    def test_top10_sum_only_latest_period(self):
        # 12 只最新报告期持仓（权重 1..12）+ 更早报告期行 → 只合计最新期前十大
        holdings = [_h(f"股{i}", float(i)) for i in range(1, 13)]
        holdings += [_h("旧股", 5.0, period="2025年4季度股票投资明细")]
        c = fund_concentration(holdings, "000001")
        assert c.fund_id == "000001"
        assert c.top10_sum == pytest.approx(3.0 + 4.0 + 5.0 + 6.0 + 7.0 + 8.0 + 9.0 + 10.0 + 11.0 + 12.0)
        assert c.holding_count == 12

    def test_no_valid_ratios_gives_none(self):
        holdings = [_h("股A", None), _h("股B", None)]
        assert fund_concentration(holdings, "000001").top10_sum is None

    def test_empty_holdings(self):
        c = fund_concentration([], "000001")
        assert c.top10_sum is None
        assert c.holding_count == 0


class TestHoldingsOverlap:
    def test_jaccard_exact(self):
        # {甲乙丙丁} ∩ {乙丙戊} = 2，并集 5 → 0.4
        a = [_h("甲", 2.0), _h("乙", 1.5), _h("丙", 1.2), _h("丁", 1.0)]
        b = [_h("乙", 9.0), _h("丙", 5.0), _h("戊", 3.0)]
        r = holdings_overlap(a, b, "000001", "519770")
        assert r.fund_a == "000001"
        assert r.fund_b == "519770"
        assert r.overlap_ratio == pytest.approx(0.4)
        assert r.common_names == ["丙", "乙"]  # 按名称排序

    def test_older_period_rows_excluded(self):
        a = [_h("甲", 2.0), _h("乙", 1.0), _h("旧甲", 1.0, period="2025年4季度股票投资明细")]
        b = [_h("旧甲", 2.0), _h("丙", 1.0)]
        assert holdings_overlap(a, b, "000001", "519770").overlap_ratio == pytest.approx(0.0)

    def test_empty_side_gives_none(self):
        r = holdings_overlap([_h("甲", 1.0)], [], "000001", "519770")
        assert r.overlap_ratio is None
        assert r.common_names == []

    def test_common_names_capped(self):
        names = [f"股{i}" for i in range(15)]
        a = [_h(n, 1.0) for n in names]
        b = [_h(n, 1.0) for n in names]
        r = holdings_overlap(a, b, "000001", "519770")
        assert r.overlap_ratio == pytest.approx(1.0)
        assert len(r.common_names) == 10
