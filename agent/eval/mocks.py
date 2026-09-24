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
from datetime import datetime

import httpx

from tools.collector_client import CollectorClient

FUND_CODES = ["519770", "004814", "015453"]

# akshare 持仓的季度原文格式；用当前年避免触发时效披露（与 tests/conftest 一致）
_QUARTER = f"{datetime.now().year}年2季度股票投资明细"

DETAIL_ROWS = [
    {"item": "fund_code", "value": "519770"},
    {"item": "fund_name", "value": "交银优择回报A"},
    {"item": "inception_date", "value": "2016-04-22"},
    {"item": "aum", "value": "44.16亿"},
    {"item": "fund_manager", "value": "周珊珊 高扬"},
    {"item": "fund_type", "value": "混合型-灵活配置"},
    {"item": "fund_company", "value": "交银施罗德基金公司"},
    {"item": "benchmark", "value": "50%×沪深300指数收益率+50%×中债综合全价指数收益率"},
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
    {"stock_code": "600519", "stock_name": "贵州茅台", "hold_ratio": 3.12, "report_date": _QUARTER},
    {"stock_code": "300750", "stock_name": "宁德时代", "hold_ratio": 2.85, "report_date": _QUARTER},
]

INDUSTRY_ROWS = [
    {"row_no": 1, "industry": "制造业", "nav_ratio": 68.96, "market_value": 189389.25, "report_date": "2026-06-30"},
    {"row_no": 2, "industry": "金融业", "nav_ratio": 6.78, "market_value": 18620.89, "report_date": "2026-06-30"},
]

ALLOCATION_ROWS = [
    {"asset_type": "股票", "percent": 94.18},
    {"asset_type": "债券", "percent": 1.82},
    {"asset_type": "现金", "percent": 5.46},
]

FEES_ROWS = [
    {"management_fee_rate": 1.0, "custodian_fee_rate": 0.15, "service_fee_rate": 0.0}
]

ACHIEVEMENT_ROWS = [
    {"performance_type": "年度业绩", "period": "成立以来", "return_rate": 53.44, "max_drawdown": 27.6, "category_rank": "308/1070"},
    {"performance_type": "年度业绩", "period": "今年以来", "return_rate": 9.38, "max_drawdown": 16.45, "category_rank": "262/1070"},
]

RATING_ROWS = [
    {
        "fund_code": "519770",
        "fund_name": "交银优择回报A",
        "five_star_count": 2,
        "rating_sh": 4.0,
        "rating_zs": 5.0,
        "rating_ja": 4.0,
        "rating_mx": 5.0,
    }
]

INDEX_ROWS = [
    {"trade_date": "2016-04-22", "close": 100.0},
    {"trade_date": "2020-01-02", "close": 120.0},
    {"trade_date": "2026-09-08", "close": 150.0},
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
    industry_rows: list | None = None,
    allocation_rows: list | None = None,
    fees_rows: list | None = None,
    achievement_rows: list | None = None,
    rating_rows: list | None = None,
    index_rows: list | None = None,
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
        if path.endswith("/industry"):
            return httpx.Response(200, json=INDUSTRY_ROWS if industry_rows is None else industry_rows)
        if path.endswith("/allocation"):
            return httpx.Response(200, json=ALLOCATION_ROWS if allocation_rows is None else allocation_rows)
        if path.endswith("/fees"):
            return httpx.Response(200, json=FEES_ROWS if fees_rows is None else fees_rows)
        if path.endswith("/achievement"):
            return httpx.Response(200, json=ACHIEVEMENT_ROWS if achievement_rows is None else achievement_rows)
        if path.endswith("/rating"):
            return httpx.Response(200, json=RATING_ROWS if rating_rows is None else rating_rows)
        if "/api/index/" in path and path.endswith("/daily"):
            return httpx.Response(200, json=INDEX_ROWS if index_rows is None else index_rows)
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
