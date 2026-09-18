"""持仓接口年份解析单测：缺省年份取当前年，空/失败回退上一年。

直接调用端点函数（不启动 HTTP 层）；FastAPI 在 query 参数缺省时会把
Query(None) 解析为 None，测试用 date=None 模拟该行为。
"""

from datetime import datetime

import pandas as pd
import pytest

import main

CURRENT = str(datetime.now().year)
PREVIOUS = str(datetime.now().year - 1)


def _df(year: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "股票代码": "600519",
                "股票名称": "贵州茅台",
                "占净值比例": 3.12,
                "持股数": 1200,
                "持仓市值": 200,
                "季度": f"{year}年1季度股票投资明细",
            }
        ]
    )


def test_default_year_uses_current_year():
    calls = []

    def fake_fetch(symbol, date):
        calls.append(date)
        return _df(date)

    df = main._holdings_df(fake_fetch, "015453", None)
    assert calls == [CURRENT]
    assert not df.empty


def test_empty_current_year_falls_back_to_previous():
    calls = []

    def fake_fetch(symbol, date):
        calls.append(date)
        return _df(date) if date == PREVIOUS else pd.DataFrame()

    df = main._holdings_df(fake_fetch, "015453", None)
    assert calls == [CURRENT, PREVIOUS]
    assert f"{PREVIOUS}年1季度" in df["季度"].iloc[0]


def test_explicit_year_empty_keeps_original_semantics():
    """显式指定年份时空返回不回退，尊重调用方语义。"""
    calls = []

    def fake_fetch(symbol, date):
        calls.append(date)
        return pd.DataFrame()

    df = main._holdings_df(fake_fetch, "015453", "2023")
    assert calls == ["2023"]
    assert df.empty


def test_current_year_error_falls_back_to_previous():
    def fake_fetch(symbol, date):
        if date == CURRENT:
            raise RuntimeError("data source boom")
        return _df(date)

    df = main._holdings_df(fake_fetch, "015453", None)
    assert f"{PREVIOUS}年1季度" in df["季度"].iloc[0]


def test_both_years_error_raises():
    def fake_fetch(symbol, date):
        raise RuntimeError("data source boom")

    with pytest.raises(RuntimeError):
        main._holdings_df(fake_fetch, "015453", None)


def test_stock_holdings_endpoint_wiring(monkeypatch):
    monkeypatch.setattr(main.ak, "fund_portfolio_hold_em", lambda symbol, date: _df(date))
    rows = main.get_stock_holdings("015453", date=None)
    assert rows[0]["stock_code"] == "600519"
    assert f"{CURRENT}年1季度" in rows[0]["report_date"]


def test_bond_holdings_endpoint_wiring(monkeypatch):
    bond_df = pd.DataFrame(
        [
            {
                "债券代码": "019547",
                "债券名称": "24国债01",
                "占净值比例": 1.5,
                "持仓市值": 100,
                "季度": f"{CURRENT}年1季度债券投资明细",
            }
        ]
    )
    monkeypatch.setattr(main.ak, "fund_portfolio_bond_hold_em", lambda symbol, date: bond_df)
    rows = main.get_bond_holdings("015453", date=None)
    assert rows[0]["bond_code"] == "019547"
    assert f"{CURRENT}年1季度" in rows[0]["report_date"]
