"""
FundForge Collector Service - akshare 数据采集薄包装层
为 Go 主后端提供 HTTP 接口，所有业务逻辑在 Go 侧处理。
响应字段已标准化为英文命名，作为 Anti-corruption Layer 的一部分。
"""

import logging
import time
from functools import wraps

import akshare as ak
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collector")

app = FastAPI(
    title="FundForge Collector Service",
    description="akshare 数据采集服务，为 Go 后端提供标准化 HTTP 接口",
    version="0.2.0",
)


# ---- Field Name Mappings (ACL: Chinese → English) ----

FIELD_MAPS = {
    "fund_list": {
        "基金代码": "fund_code",
        "基金简称": "fund_name",
        "基金类型": "fund_type",
        "拼音缩写": "pinyin_abbr",
        "拼音全称": "pinyin_full",
    },
    "fund_nav_unit": {
        "净值日期": "nav_date",
        "单位净值": "unit_nav",
        "日增长率": "daily_return",
    },
    "fund_nav_acc": {
        "净值日期": "nav_date",
        "累计净值": "acc_nav",
    },
    "trade_calendar": {
        "trade_date": "trade_date",
    },
    "fund_dividend": {
        "基金代码": "fund_code",
        "基金简称": "fund_name",
        "权益登记日": "record_date",
        "除息日期": "ex_date",
        "每份分红": "dividend_per_unit",
        "分红发放日": "pay_date",
    },
    "fund_split": {
        "基金代码": "fund_code",
        "基金简称": "fund_name",
        "拆分折算日": "split_date",
        "拆分类型": "split_type",
        "拆分折算比例": "split_ratio",
    },
    "stock_holding": {
        "股票代码": "stock_code",
        "股票名称": "stock_name",
        "占净值比例": "hold_ratio",
        "持股数": "hold_shares",
        "持仓市值": "hold_value",
        "季度": "report_date",
    },
    "bond_holding": {
        "债券代码": "bond_code",
        "债券名称": "bond_name",
        "占净值比例": "hold_ratio",
        "持仓市值": "hold_value",
        "季度": "report_date",
    },
    "achievement": {
        "周期": "period",
        "收益率": "return_rate",
        "同类平均": "category_avg",
        "同类排名": "category_rank",
        "排名四分位": "quartile",
        "同类基金数": "fund_count",
    },
    "analysis": {
        "周期": "period",
        "较同类风险收益比": "risk_return_ratio",
        "较同类抗风险波动": "anti_risk_volatility",
        "年化波动率": "annual_volatility",
        "年化夏普比率": "annual_sharpe",
        "最大回撤": "max_drawdown",
    },
}


# ---- Helpers ----

def df_to_response(df: pd.DataFrame, mapping_key: str = None) -> list[dict]:
    """将 DataFrame 转为 JSON 可序列化的 list[dict]，可选字段名标准化。"""
    if df is None or df.empty:
        return []
    if mapping_key and mapping_key in FIELD_MAPS:
        df = df.rename(columns=FIELD_MAPS[mapping_key])
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def akshare_call(func):
    """统一 akshare 调用包装：异常捕获 + 计时日志。"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs) if callable(getattr(func, '__wrapped__', None)) else func(*args, **kwargs)
            elapsed = (time.time() - start) * 1000
            logger.info(f"{func.__name__} OK ({elapsed:.0f}ms)")
            return result
        except HTTPException:
            raise
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"{func.__name__} FAIL ({elapsed:.0f}ms): {e}")
            raise HTTPException(status_code=502, detail=f"Data source error: {str(e)}")
    return wrapper


# ---- Health ----

@app.get("/health")
def health():
    return {"status": "ok", "akshare_version": ak.__version__}


# ---- Fund List ----

@app.get("/api/funds")
@akshare_call
def get_fund_list():
    """全量基金列表"""
    df = ak.fund_name_em()
    return df_to_response(df, "fund_list")


# ---- Historical NAV ----

@app.get("/api/funds/{code}/nav")
@akshare_call
def get_fund_nav(
    code: str,
    indicator: str = Query("单位净值走势", description="单位净值走势 | 累计净值走势"),
    period: str = Query("成立来", description="成立来 | 近1年 | 近3年 等"),
):
    """基金历史净值"""
    df = ak.fund_open_fund_info_em(symbol=code, indicator=indicator, period=period)
    mapping = "fund_nav_unit" if "单位" in indicator else "fund_nav_acc"
    return df_to_response(df, mapping)


# ---- Realtime NAV (T-day) ----

@app.get("/api/funds/nav/realtime")
@akshare_call
def get_realtime_nav():
    """T日实时净值（全量基金，调用方按需过滤）"""
    df = ak.fund_open_fund_daily_em()
    return df_to_response(df)


# ---- NAV Estimation ----

@app.get("/api/funds/estimation")
@akshare_call
def get_nav_estimation(
    symbol: str = Query("股票型", description="基金类型: 股票型 | 混合型 | 债券型 等"),
):
    """盘中净值估算"""
    df = ak.fund_value_estimation_em(symbol=symbol)
    return df_to_response(df)


# ---- Fund Detail (Xueqiu) ----

@app.get("/api/funds/{code}/detail")
@akshare_call
def get_fund_detail(code: str):
    """基金详情（雪球源）"""
    df = ak.fund_individual_basic_info_xq(symbol=code)
    return df_to_response(df)


# ---- Fund Trading Rules (Xueqiu) ----

@app.get("/api/funds/{code}/rules")
@akshare_call
def get_fund_rules(code: str):
    """基金交易规则（雪球源）"""
    df = ak.fund_individual_detail_info_xq(symbol=code)
    return df_to_response(df)


# ---- Dividends ----

@app.get("/api/funds/dividends")
@akshare_call
def get_fund_dividends():
    """全量基金分红记录"""
    df = ak.fund_fh_em()
    return df_to_response(df, "fund_dividend")


# ---- Splits ----

@app.get("/api/funds/splits")
@akshare_call
def get_fund_splits():
    """全量基金拆分记录"""
    df = ak.fund_cf_em()
    return df_to_response(df, "fund_split")


# ---- Dividend Ranking ----

@app.get("/api/funds/dividend-rank")
@akshare_call
def get_dividend_rank():
    """基金分红排行"""
    df = ak.fund_fh_rank_em()
    return df_to_response(df)


# ---- Stock Holdings ----

@app.get("/api/funds/{code}/holdings/stock")
@akshare_call
def get_stock_holdings(code: str, date: str = Query("2024", description="年份")):
    """基金股票持仓"""
    df = ak.fund_portfolio_hold_em(symbol=code, date=date)
    return df_to_response(df, "stock_holding")


# ---- Bond Holdings ----

@app.get("/api/funds/{code}/holdings/bond")
@akshare_call
def get_bond_holdings(code: str, date: str = Query("2024", description="年份")):
    """基金债券持仓"""
    df = ak.fund_portfolio_bond_hold_em(symbol=code, date=date)
    return df_to_response(df, "bond_holding")


# ---- Achievement (Xueqiu) ----

@app.get("/api/funds/{code}/achievement")
@akshare_call
def get_fund_achievement(code: str):
    """基金业绩分析（雪球源）"""
    df = ak.fund_individual_achievement_xq(symbol=code)
    return df_to_response(df, "achievement")


# ---- Risk Analysis (Xueqiu) ----

@app.get("/api/funds/{code}/analysis")
@akshare_call
def get_fund_analysis(code: str):
    """基金风险分析（雪球源）"""
    df = ak.fund_individual_analysis_xq(symbol=code)
    return df_to_response(df, "analysis")


# ---- Money Fund Daily ----

@app.get("/api/funds/money/daily")
@akshare_call
def get_money_fund_daily():
    """货币基金当日数据（万份收益、7日年化）"""
    df = ak.fund_money_fund_daily_em()
    return df_to_response(df)


# ---- Fund Ranking ----

@app.get("/api/funds/rank")
@akshare_call
def get_fund_rank(symbol: str = Query("全部", description="基金类型")):
    """基金排行"""
    df = ak.fund_open_fund_rank_em(symbol=symbol)
    return df_to_response(df)


# ---- Trade Calendar ----

@app.get("/api/trade-calendar")
@akshare_call
def get_trade_calendar():
    """A股交易日历"""
    df = ak.tool_trade_date_hist_sina()
    return df_to_response(df, "trade_calendar")


# ---- ETF Historical (supplementary) ----

@app.get("/api/funds/etf/{code}/nav")
@akshare_call
def get_etf_nav(
    code: str,
    start_date: str = Query("20000101"),
    end_date: str = Query("20501231"),
):
    """ETF基金历史净值"""
    df = ak.fund_etf_fund_info_em(fund=code, start_date=start_date, end_date=end_date)
    return df_to_response(df)


# ---- Main ----

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
