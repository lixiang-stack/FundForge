"""Analyzer 区间对齐测试（Phase 6 后优化：peer 对比按最短共同区间，≤10 年）。"""

from datetime import date, timedelta

from domain.fund import NAVPoint
from tests.conftest import make_transport
from nodes.analyzer import AnalyzerNode, _aligned_window
from store import FundStore
from tools.collector_client import CollectorClient


def _point(d: str, unit: float, acc: float | None = None) -> NAVPoint:
    return NAVPoint(nav_date=date.fromisoformat(d), unit_nav=unit, acc_nav=acc)


def _fund_a(store: FundStore) -> None:
    # 长历史：2020-01-01 起（窗口内含 2023-01-01、2024-01-01 两个点）
    store.put_nav_series(
        "000001",
        [_point("2020-01-01", 1.0), _point("2023-01-01", 1.2), _point("2024-01-01", 1.44)],
    )


def _fund_b(store: FundStore) -> None:
    # 短历史：2022-06-01 起 3 个点
    store.put_nav_series(
        "519770",
        [_point("2022-06-01", 1.0), _point("2023-06-01", 1.1), _point("2024-01-01", 1.21)],
    )


class TestAlignedWindow:
    def test_aligns_to_latest_start(self):
        store = FundStore()
        _fund_a(store)
        _fund_b(store)
        window = _aligned_window(
            {"000001": store.get_nav_series("000001"), "519770": store.get_nav_series("519770")}
        )
        assert window == (date(2022, 6, 1), date(2024, 1, 1))

    def test_caps_at_ten_years(self):
        store = FundStore()
        store.put_nav_series(
            "000001",
            [_point("2000-01-01", 1.0), _point("2024-06-01", 1.2)],
        )
        store.put_nav_series(
            "519770",
            [_point("2005-01-01", 1.0), _point("2024-06-01", 1.1)],
        )
        window = _aligned_window(
            {"000001": store.get_nav_series("000001"), "519770": store.get_nav_series("519770")}
        )
        start, end = window
        assert (end - start).days <= 365 * 10
        assert end == date(2024, 6, 1)
        assert start > date(2014, 1, 1)  # 被截断至 10 年内

    def test_too_short_common_window_returns_none(self):
        store = FundStore()
        store.put_nav_series("000001", [_point("2024-01-01", 1.0), _point("2024-01-10", 1.01)])
        store.put_nav_series("519770", [_point("2024-01-02", 1.0), _point("2024-01-12", 1.01)])
        window = _aligned_window(
            {"000001": store.get_nav_series("000001"), "519770": store.get_nav_series("519770")}
        )
        assert window is None


class TestAnalyzerAlignment:
    def test_peer_metrics_use_aligned_window(self):
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        store = FundStore()
        _fund_a(store)
        _fund_b(store)
        try:
            out = AnalyzerNode(store)(
                {
                    "fund_ids": ["000001", "519770"],
                    "research_plan": {
                        "task_type": "fund_comparison",
                        "primary_fund_id": "000001",
                        "fund_ids": ["000001", "519770"],
                        "peer_fund_ids": ["519770"],
                        "notes": [],
                    },
                }
            )
            analysis = out["analysis"]
            # 主基金指标与对比表同口径：对齐窗口 2022-06-01 ~ 2024-01-01
            # 窗口内 000001 的点：2023-01-01（1.2）、2024-01-01（1.44）→ complete
            assert analysis.performance.period_start == date(2023, 1, 1)
            assert analysis.performance.period_end == date(2024, 1, 1)
            assert analysis.performance.cumulative_return == 1.44 / 1.2 - 1
            assert analysis.performance.data_quality == "complete"
        finally:
            pass

    def test_alignment_window_in_evidence(self):
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        store = FundStore()
        # 两只基金完全同窗 → 对齐区间 = 自身区间
        store.put_nav_series(
            "000001",
            [_point("2022-06-01", 1.0), _point("2024-01-01", 1.44)],
        )
        store.put_nav_series(
            "519770",
            [_point("2022-06-01", 1.0), _point("2024-01-01", 1.21)],
        )
        out = AnalyzerNode(store)({"fund_ids": ["000001", "519770"], "research_plan": None})
        calc = [e for e in out["evidence"] if e.evidence_type == "calculation"]
        assert calc and calc[0].value["alignment_window"] == ["2022-06-01", "2024-01-01"]

    def test_mixed_nav_basis_forces_unit_for_all(self):
        # 一只 acc 全覆盖、另一只部分缺失 → 全组统一 unit 口径并记 data_quality issue
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        store = FundStore()
        store.put_nav_series(
            "000001",
            [_point("2022-06-01", 1.0, acc=1.0), _point("2024-01-01", 1.44, acc=1.5)],
        )
        store.put_nav_series(
            "519770",
            [_point("2022-06-01", 1.0), _point("2024-01-01", 1.21)],
        )
        out = AnalyzerNode(store)(
            {
                "fund_ids": ["000001", "519770"],
                "research_plan": {
                    "task_type": "fund_comparison",
                    "primary_fund_id": "000001",
                    "fund_ids": ["000001", "519770"],
                    "peer_fund_ids": ["519770"],
                    "notes": [],
                },
            }
        )
        calc = [e for e in out["evidence"] if e.evidence_type == "calculation"]
        assert calc and all(e.value["nav_basis"] == "unit" for e in calc)
        # 主基金按 unit 口径重算：1.0 → 1.44（而非 acc 的 1.0 → 1.5）
        assert out["analysis"].performance.cumulative_return == 1.44 / 1.0 - 1
        assert any("净值口径不一致" in i for i in out["data_quality_issues"])


class TestPeerPointCountDisclosure:
    """同窗口点数差超容忍度 → data_quality_issues 披露（对齐只统一端点不统一逐日覆盖）。"""

    @staticmethod
    def _series(start: str, days: int, skip_every: int = 0) -> list:
        base = date.fromisoformat(start)
        points = []
        for i in range(days):
            if skip_every and i % skip_every == 0:
                continue  # 中间缺披露日，模拟披露频率差异
            d = (base + timedelta(days=i)).isoformat()
            points.append(_point(d, 1.0 + i * 0.001, acc=1.0 + i * 0.001))
        return points

    def _run(self, store: FundStore) -> dict:
        return AnalyzerNode(store)(
            {
                "fund_ids": ["000001", "519770"],
                "research_plan": {
                    "task_type": "fund_comparison",
                    "primary_fund_id": "000001",
                    "fund_ids": ["000001", "519770"],
                    "peer_fund_ids": ["519770"],
                    "notes": [],
                },
            }
        )

    def test_gap_beyond_tolerance_is_disclosed(self):
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        store = FundStore()
        # 同跨度 200 天，B 缺 10 个中间披露日 → 200 vs 190 ≈ 5.3% > 1%
        store.put_nav_series("000001", self._series("2022-01-01", 200))
        store.put_nav_series("519770", self._series("2022-01-01", 200, skip_every=20))
        try:
            out = self._run(store)
            assert any("净值点数差" in i for i in out["data_quality_issues"])
        finally:
            pass

    def test_gap_within_tolerance_is_silent(self):
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        store = FundStore()
        # 同跨度 200 天，B 缺 1 个中间披露日 → 200 vs 199 ≈ 0.5% < 1%
        store.put_nav_series("000001", self._series("2022-01-01", 200, skip_every=100))
        store.put_nav_series("519770", self._series("2022-01-01", 200))
        try:
            out = self._run(store)
            assert not any("净值点数差" in i for i in out["data_quality_issues"])
        finally:
            pass
