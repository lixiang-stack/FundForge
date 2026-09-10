"""测试公共夹具：用 httpx.MockTransport 模拟 collector service 响应。"""

import httpx
import pytest

from store import FundStore
from tools.collector_client import CollectorClient
from tools.fund_tools import make_fund_tools

FUND_CODE = "519770"

DETAIL_ROWS = [
    {"item": "基金代码", "value": FUND_CODE},
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
        if path == "/api/funds":
            return httpx.Response(200, json=fund_rows if fund_rows is not None else FUND_LIST_ROWS)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def make_tools(
    detail_rows: list | None = None,
    unit_rows: list | None = None,
    acc_rows: list | None = None,
    fund_rows: list | None = None,
    status: int = 200,
):
    """构建 (tools, store, client) 三元组，client 使用 mock transport。"""
    client = CollectorClient(
        base_url="http://collector.test",
        transport=make_transport(detail_rows, unit_rows, acc_rows, fund_rows, status),
    )
    store = FundStore()
    return make_fund_tools(client, store), store, client


@pytest.fixture
def tools_and_store():
    tools, store, client = make_tools()
    yield tools, store
    client.close()
