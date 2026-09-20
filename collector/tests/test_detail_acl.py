"""详情接口 ACL 单测：雪球 {item, value} 行的 item 值标准化为英文。

detail 端点的中文在 item 列的值里而非列名里，映射由 df_to_kv_response 完成；
未知 item 原样透传（雪球源可能新增条目，消费方忽略未知键）。
"""

import pandas as pd
import pytest

import main


def _detail_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item": "基金代码", "value": "519770"},
            {"item": "基金名称", "value": "交银优择回报A"},
            {"item": "基金全称", "value": "交银施罗德优择回报灵活配置混合型证券投资基金"},
            {"item": "成立时间", "value": "2016-04-22"},
            {"item": "最新规模", "value": "44.16亿"},
            {"item": "基金经理", "value": "周珊珊 高扬"},
            {"item": "基金类型", "value": "混合型-灵活配置"},
            {"item": "基金公司", "value": "交银施罗德基金公司"},
            {"item": "托管银行", "value": "中信银行股份有限公司"},
            {"item": "评级机构", "value": None},
            {"item": "基金评级", "value": "暂无评级"},
            {"item": "投资策略", "value": "灵活调整大类资产配置比例。"},
            {"item": "投资目标", "value": "力争长期稳健回报。"},
            {"item": "业绩比较基准", "value": "50%×沪深300指数收益率+50%×中债综合全价指数收益率"},
        ]
    )


def test_kv_response_maps_items_to_english():
    rows = main.df_to_kv_response(_detail_df(), "fund_detail")
    items = {r["item"]: r["value"] for r in rows}
    assert items == {
        "fund_code": "519770",
        "fund_name": "交银优择回报A",
        "fund_full_name": "交银施罗德优择回报灵活配置混合型证券投资基金",
        "inception_date": "2016-04-22",
        "aum": "44.16亿",
        "fund_manager": "周珊珊 高扬",
        "fund_type": "混合型-灵活配置",
        "fund_company": "交银施罗德基金公司",
        "custodian_bank": "中信银行股份有限公司",
        "rating_agency": None,
        "fund_rating": "暂无评级",
        "investment_strategy": "灵活调整大类资产配置比例。",
        "investment_objective": "力争长期稳健回报。",
        "benchmark": "50%×沪深300指数收益率+50%×中债综合全价指数收益率",
    }


def test_kv_response_passes_unknown_items_through():
    df = pd.DataFrame(
        [
            {"item": "新增条目", "value": "x"},
            {"item": "基金名称", "value": "某基金"},
        ]
    )
    rows = main.df_to_kv_response(df, "fund_detail")
    items = {r["item"]: r["value"] for r in rows}
    assert items == {"新增条目": "x", "fund_name": "某基金"}


def test_kv_response_empty_df_returns_empty_list():
    assert main.df_to_kv_response(pd.DataFrame(), "fund_detail") == []
    assert main.df_to_kv_response(None, "fund_detail") == []


def test_detail_endpoint_wiring(monkeypatch):
    monkeypatch.setattr(
        main.ak, "fund_individual_basic_info_xq", lambda symbol: _detail_df()
    )
    rows = main.get_fund_detail("519770")
    items = {r["item"]: r["value"] for r in rows}
    assert items["fund_name"] == "交银优择回报A"
    assert items["aum"] == "44.16亿"
    assert items["benchmark"].startswith("50%×沪深300")
