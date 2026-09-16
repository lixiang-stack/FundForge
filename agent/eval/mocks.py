"""评测用 collector mock 档位（Phase 10）。

档位数据形态与 tests/conftest 一致（路径式 mock，同一份行数据服务任意基金代码），
但独立维护：评测是正式能力，不反向依赖测试夹具。

档位：
- mock_ok             标准三基金同构数据（正常路径基准）
- mock_fail_all       全部接口 500（采集完全失败 → 降级链路）
- mock_empty_holdings 空股票持仓（债基正常披露，不算质量问题）
- mock_empty_detail   基金基本信息为空（数据源异常 → 质量降级 + issue）
"""

from collections.abc import Callable

import httpx

from tools.collector_client import CollectorClient

FUND_CODES = ["519770", "004814", "015453"]

DETAIL_ROWS = [
    {"item": "基金代码", "value": "519770"},
    {"item": "基金名称", "value": "交银优择回报A"},
    {"item": "成立时间", "value": "2016-04-22"},
    {"item": "最新规模", "value": "44.16亿"},
    {"item": "基金经理", "value": "周珊珊 高扬"},
    {"item": "基金类型", "value": "混合型-灵活配置"},
    {"item": "基金公司", "value": "交银施罗德基金公司"},
]

UNIT_ROWS = [
    {"nav_date": "2016-04-22", "unit_nav": 1.0, "daily_return": 0.0},
    {"nav_date": "2020-01-02", "unit_nav": 2.0, "daily_return": 1.5},
    {"nav_date": "2026-09-08", "unit_nav": 5.7559, "daily_return": -0.65},
]

ACC_ROWS = [
    {"nav_date": "2016-04-22", "acc_nav": 1.0},
    {"nav_date": "2020-01-02", "acc_nav": 2.1},
    {"nav_date": "2026-09-08", "acc_nav": 5.7559},
]

HOLDINGS_ROWS = [
    {"stock_code": "600519", "stock_name": "贵州茅台", "hold_ratio": 3.12, "report_date": "2025-06-30"},
    {"stock_code": "300750", "stock_name": "宁德时代", "hold_ratio": 2.85, "report_date": "2025-06-30"},
]

FUND_LIST_ROWS = [
    {"fund_code": "519770", "fund_name": "交银优择回报A", "fund_type": "混合型-灵活配置", "pinyin_abbr": "jyyzhbA"},
    {"fund_code": "004814", "fund_name": "中欧潜力价值灵活配置A", "fund_type": "混合型", "pinyin_abbr": "zoqljzA"},
    {"fund_code": "015453", "fund_name": "中证500指数增强A", "fund_type": "指数型-股票", "pinyin_abbr": "zz500zjqA"},
]


def _transport(
    *,
    status: int = 200,
    detail_rows: list | None = None,
    unit_rows: list | None = None,
    acc_rows: list | None = None,
    holdings_rows: list | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"detail": "mock failure"})
        path = request.url.path
        if path.endswith("/detail"):
            return httpx.Response(200, json=DETAIL_ROWS if detail_rows is None else detail_rows)
        if path.endswith("/nav"):
            indicator = request.url.params.get("indicator", "")
            if "累计" in indicator:
                rows = ACC_ROWS if acc_rows is None else acc_rows
            else:
                rows = UNIT_ROWS if unit_rows is None else unit_rows
            return httpx.Response(200, json=rows)
        if path.endswith("/holdings/stock"):
            return httpx.Response(200, json=HOLDINGS_ROWS if holdings_rows is None else holdings_rows)
        if path == "/api/funds":
            return httpx.Response(200, json=FUND_LIST_ROWS)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


# 档位名 → transport 工厂（每次构建新实例，Case 之间互不污染）
PROFILES: dict[str, Callable[[], httpx.MockTransport]] = {
    "mock_ok": lambda: _transport(),
    "mock_fail_all": lambda: _transport(status=500),
    "mock_empty_holdings": lambda: _transport(holdings_rows=[]),
    "mock_empty_detail": lambda: _transport(detail_rows=[]),
}


def build_collector(source: str) -> CollectorClient:
    """按 Case 档位构建 collector 客户端；"real" 使用环境配置（需运行中服务）。"""
    if source == "real":
        return CollectorClient()
    factory = PROFILES.get(source)
    if factory is None:
        raise ValueError(f"未知 collector 档位：{source!r}（可选：real / {sorted(PROFILES)}）")
    return CollectorClient(base_url="http://collector.mock", transport=factory())


__all__ = ["PROFILES", "build_collector"]
