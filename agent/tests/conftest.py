"""测试公共夹具：用 httpx.MockTransport 模拟 collector service 响应。"""

from datetime import datetime

import httpx
import pytest

from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools

FUND_CODE = "519770"
# akshare 持仓的季度原文格式（如"2026年1季度股票投资明细"）；用当前年避免触发时效披露
_QUARTER = f"{datetime.now().year}年1季度股票投资明细"

# item 名为 collector FIELD_MAPS["fund_detail"] 标准化后的英文输出
DETAIL_ROWS = [
    {"item": "fund_code", "value": FUND_CODE},
    {"item": "fund_name", "value": "交银优择回报A"},
    {"item": "fund_full_name", "value": "交银施罗德优择回报灵活配置混合型证券投资基金"},
    {"item": "inception_date", "value": "2016-04-22"},
    {"item": "aum", "value": "44.16亿"},
    {"item": "fund_manager", "value": "周珊珊 高扬"},
    {"item": "fund_type", "value": "混合型-灵活配置"},
    {"item": "fund_company", "value": "交银施罗德基金公司"},
    {"item": "custodian_bank", "value": "中信银行股份有限公司"},
    {"item": "rating_agency", "value": None},
    {"item": "fund_rating", "value": "暂无评级"},
    {"item": "investment_strategy", "value": "本基金充分发挥基金管理人的研究优势，灵活调整大类资产配置比例。"},
    {"item": "investment_objective", "value": "力争为投资者提供长期稳健的投资回报。"},
    {"item": "benchmark", "value": "50%×沪深300指数收益率+50%×中债综合全价指数收益率"},
]

UNIT_ROWS = [
    {"nav_date": "2016-04-22", "unit_nav": 1.0, "daily_return": 0.0},
    {"nav_date": "2020-01-02", "unit_nav": 2.0, "daily_return": 1.5},
    {"nav_date": "2026-09-08", "unit_nav": 5.7559, "daily_return": -0.65},
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
        "fund_code": FUND_CODE,
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

ACC_ROWS = [
    {"nav_date": "2016-04-22", "acc_nav": 1.0},
    {"nav_date": "2020-01-02", "acc_nav": 2.1},
    {"nav_date": "2026-09-08", "acc_nav": 5.7559},
]

FUND_LIST_ROWS = [
    {
        "fund_code": FUND_CODE,
        "fund_name": "交银优择回报A",
        "fund_type": "混合型-灵活配置",
        "pinyin_abbr": "jyyzhbA",
    },
    {
        "fund_code": "000001",
        "fund_name": "华夏成长混合",
        "fund_type": "混合型",
        "pinyin_abbr": "hxczhb",
    },
]


def make_transport(
    detail_rows: list | None = None,
    unit_rows: list | None = None,
    acc_rows: list | None = None,
    fund_rows: list | None = None,
    holdings_rows: list | None = None,
    industry_rows: list | None = None,
    allocation_rows: list | None = None,
    fees_rows: list | None = None,
    achievement_rows: list | None = None,
    rating_rows: list | None = None,
    index_rows: list | None = None,
    status: int = 200,
) -> httpx.MockTransport:
    """按路径模拟 collector 响应；status 非 200 时统一返回错误。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"detail": "boom"})
        path = request.url.path
        if path.endswith("/detail"):
            return httpx.Response(200, json=detail_rows if detail_rows is not None else DETAIL_ROWS)
        if path.endswith("/nav"):
            indicator = request.url.params.get("indicator", "")
            if "累计" in indicator:
                return httpx.Response(200, json=acc_rows if acc_rows is not None else ACC_ROWS)
            return httpx.Response(200, json=unit_rows if unit_rows is not None else UNIT_ROWS)
        if path.endswith("/holdings/stock"):
            return httpx.Response(
                200, json=holdings_rows if holdings_rows is not None else HOLDINGS_ROWS
            )
        if path.endswith("/industry"):
            return httpx.Response(
                200, json=industry_rows if industry_rows is not None else INDUSTRY_ROWS
            )
        if path.endswith("/allocation"):
            return httpx.Response(
                200, json=allocation_rows if allocation_rows is not None else ALLOCATION_ROWS
            )
        if path.endswith("/fees"):
            return httpx.Response(200, json=fees_rows if fees_rows is not None else FEES_ROWS)
        if path.endswith("/achievement"):
            return httpx.Response(
                200, json=achievement_rows if achievement_rows is not None else ACHIEVEMENT_ROWS
            )
        if path.endswith("/rating"):
            return httpx.Response(200, json=rating_rows if rating_rows is not None else RATING_ROWS)
        if "/api/index/" in path and path.endswith("/daily"):
            return httpx.Response(200, json=INDEX_ROWS if index_rows is not None else INDEX_ROWS)
        if path == "/api/funds":
            return httpx.Response(200, json=fund_rows if fund_rows is not None else FUND_LIST_ROWS)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def make_tools(
    detail_rows: list | None = None,
    unit_rows: list | None = None,
    acc_rows: list | None = None,
    fund_rows: list | None = None,
    holdings_rows: list | None = None,
    industry_rows: list | None = None,
    allocation_rows: list | None = None,
    fees_rows: list | None = None,
    achievement_rows: list | None = None,
    rating_rows: list | None = None,
    index_rows: list | None = None,
    status: int = 200,
):
    """构建 (tools, store, client) 三元组，client 使用 mock transport。"""
    client = CollectorClient(
        base_url="http://collector.test",
        transport=make_transport(
            detail_rows,
            unit_rows,
            acc_rows,
            fund_rows,
            holdings_rows,
            industry_rows,
            allocation_rows,
            fees_rows,
            achievement_rows,
            rating_rows,
            index_rows,
            status,
        ),
    )
    store = FundStore()
    return make_fund_tools(client, store), store, client


@pytest.fixture
def tools_and_store():
    tools, store, client = make_tools()
    yield tools, store
    client.close()
