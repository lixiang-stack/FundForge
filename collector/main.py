"""
FundForge Collector Service - akshare 数据采集薄包装层
为 Go 主后端提供 HTTP 接口，所有业务逻辑在 Go 侧处理。
响应字段已标准化为英文命名，作为 Anti-corruption Layer 的一部分。
"""

import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps

import akshare as ak
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collector")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时单线程预热一次 V8（py_mini_racer）。

    akshare 部分端点（东财净值 / 雪球详情）每次调用新建 MiniRacer 实例，
    并发下首次初始化 V8 会触发 address_pool_manager 竞争直接崩溃（实测 SIGTRAP）；
    启动时先初始化一次，后续并发的实例创建不再竞争平台初始化。
    """
    try:
        import py_mini_racer

        py_mini_racer.MiniRacer()
        logger.info("py_mini_racer warmed up")
    except Exception as e:
        logger.warning(f"py_mini_racer warmup failed (concurrent akshare calls may crash): {e}")
    yield


app = FastAPI(
    title="FundForge Collector Service",
    description="akshare 数据采集服务，为 Go 后端提供标准化 HTTP 接口",
    version="0.2.0",
    lifespan=lifespan,
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
    # 雪球 fund_individual_achievement_xq 实际返回列（年度业绩 + 阶段业绩）
    "achievement": {
        "业绩类型": "performance_type",
        "周期": "period",
        "本产品区间收益": "return_rate",
        "本产品最大回撒": "max_drawdown",
        "周期收益同类排名": "category_rank",
    },
    "analysis": {
        "周期": "period",
        "较同类风险收益比": "risk_return_ratio",
        "较同类抗风险波动": "anti_risk_volatility",
        "年化波动率": "annual_volatility",
        "年化夏普比率": "annual_sharpe",
        "最大回撤": "max_drawdown",
    },
    # 雪球 fund_individual_basic_info_xq 返回 {item, value} 键值对行：
    # 中文在 item 列的值里而非列名里，须用 df_to_kv_response 映射 item 值
    "fund_detail": {
        "基金代码": "fund_code",
        "基金名称": "fund_name",
        "基金全称": "fund_full_name",
        "成立时间": "inception_date",
        "最新规模": "aum",
        "基金经理": "fund_manager",
        "基金类型": "fund_type",
        "基金公司": "fund_company",
        "托管银行": "custodian_bank",
        "评级机构": "rating_agency",
        "基金评级": "fund_rating",
        "投资策略": "investment_strategy",
        "投资目标": "investment_objective",
        "业绩比较基准": "benchmark",
    },
    # 天天基金 fund_portfolio_industry_allocation_em 返回列（投资组合-行业配置）
    "industry_alloc": {
        "序号": "row_no",
        "行业类别": "industry",
        "占净值比例": "nav_ratio",
        "市值": "market_value",
        "截止时间": "report_date",
    },
    # 雪球 fund_individual_detail_hold_xq 返回列（资产配置，按财报日期）
    "asset_allocation": {
        "资产类型": "asset_type",
        "仓位占比": "percent",
    },
    # 天天基金 fund_rating_all 返回列（基金评级总汇）
    "fund_rating": {
        "代码": "fund_code",
        "简称": "fund_name",
        "基金经理": "fund_manager",
        "基金公司": "fund_company",
        "5星评级家数": "five_star_count",
        "上海证券": "rating_sh",
        "招商证券": "rating_zs",
        "济安金信": "rating_ja",
        "晨星评级": "rating_mx",
        "手续费": "fee_rate",
        "类型": "fund_type",
    },
}

INDEX_DAILY_COLUMNS = ["date", "close"]  # 指数日线仅保留计算超额收益所需列


# ---- Helpers ----

def df_to_response(df: pd.DataFrame, mapping_key: str = None) -> list[dict]:
    """将 DataFrame 转为 JSON 可序列化的 list[dict]，可选字段名标准化。"""
    if df is None or df.empty:
        return []
    if mapping_key and mapping_key in FIELD_MAPS:
        df = df.rename(columns=FIELD_MAPS[mapping_key])
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def df_to_kv_response(df: pd.DataFrame, mapping_key: str) -> list[dict]:
    """雪球 {item, value} 键值对端点的 item 值标准化（列名固定为 item/value，中文在值里）。"""
    if df is None or df.empty:
        return []
    mapping = FIELD_MAPS.get(mapping_key, {})
    df = df.copy()
    # 未命中的 item 原样透传：雪球源可能新增条目，消费方忽略未知键即可
    df["item"] = df["item"].map(lambda v: mapping.get(v, v))
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def akshare_call(func):
    """统一 akshare 调用包装：异常捕获 + 计时日志。

    必须保持同步函数：akshare 调用是阻塞 IO，若用 async def 包装，
    FastAPI 会把端点放在事件循环上直接执行，阻塞期间所有请求被串行化；
    同步端点才由 FastAPI 放入线程池并发执行。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
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
    return df_to_kv_response(df, "fund_detail")


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

def _holdings_df(fetch, code: str, date: str | None) -> pd.DataFrame:
    """持仓数据获取：未显式指定年份时取「最新可用披露」（当前年 → 回退上一年）。

    akshare 持仓接口按年返回全年四个季度明细；年初新一年度报告未披露时当前年
    返回空，回退上一年避免拿到空数据。显式指定年份时不回退，尊重调用方语义。
    """
    year = date or str(datetime.now().year)
    if date is not None:
        return fetch(symbol=code, date=year)
    prev = str(datetime.now().year - 1)
    try:
        df = fetch(symbol=code, date=year)
    except Exception:
        logger.warning(f"holdings {code} {year} failed, fallback to {prev}")
        return fetch(symbol=code, date=prev)
    if df is None or df.empty:
        logger.info(f"holdings {code} {year} empty, fallback to {prev}")
        return fetch(symbol=code, date=prev)
    return df


@app.get("/api/funds/{code}/holdings/stock")
@akshare_call
def get_stock_holdings(code: str, date: str | None = Query(None, description="年份，缺省取最新可用披露")):
    """基金股票持仓"""
    df = _holdings_df(ak.fund_portfolio_hold_em, code, date)
    return df_to_response(df, "stock_holding")


# ---- Bond Holdings ----

@app.get("/api/funds/{code}/holdings/bond")
@akshare_call
def get_bond_holdings(code: str, date: str | None = Query(None, description="年份，缺省取最新可用披露")):
    """基金债券持仓"""
    df = _holdings_df(ak.fund_portfolio_bond_hold_em, code, date)
    return df_to_response(df, "bond_holding")


# ---- Industry Allocation ----

@app.get("/api/funds/{code}/industry")
@akshare_call
def get_industry_allocation(code: str, date: str | None = Query(None, description="年份，缺省取最新可用披露")):
    """基金行业配置（天天基金-投资组合-行业配置）"""
    df = _holdings_df(ak.fund_portfolio_industry_allocation_em, code, date)
    return df_to_response(df, "industry_alloc")


# ---- Asset Allocation (Xueqiu) ----

@app.get("/api/funds/{code}/allocation")
@akshare_call
def get_asset_allocation(code: str, date: str = Query(..., description="财报日期 YYYYMMDD")):
    """基金资产配置：股票/债券/现金等仓位占比（雪球源，按财报日期）"""
    df = ak.fund_individual_detail_hold_xq(symbol=code, date=date)
    return df_to_response(df, "asset_allocation")


# ---- Operating Fees ----

def _parse_fee_percent(raw) -> float | None:
    """「1.00%（每年）」→ 1.00；无数字返回 None。"""
    if raw is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(raw))
    return float(m.group()) if m else None


@app.get("/api/funds/{code}/fees")
@akshare_call
def get_fund_fees(code: str):
    """基金运作费用：管理费率/托管费率/销售服务费率（天天基金源，单位 %）。

    akshare 返回单行宽表（列 0..5 交替为费率名称与数值），此处规整为结构化记录。
    """
    df = ak.fund_fee_em(symbol=code, indicator="运作费用")
    if df is None or df.empty or df.shape[1] < 6:
        return []
    row = df.iloc[0].tolist()
    return [
        {
            "management_fee_rate": _parse_fee_percent(row[1]),
            "custodian_fee_rate": _parse_fee_percent(row[3]),
            "service_fee_rate": _parse_fee_percent(row[5]),
        }
    ]


# ---- Fund Rating ----

_RATING_TTL_SECONDS = 24 * 3600  # 评级为季度级低频数据，按天刷新足够
_rating_cache: pd.DataFrame | None = None
_rating_fetched_at: float = 0.0


def _rating_df() -> pd.DataFrame:
    """评级总汇带 TTL 的进程内缓存：fund_rating_all 为全市场全量拉取，逐请求拉取代价过高。

    缓存按 _RATING_TTL_SECONDS 过期重拉，进程长驻时数据最多滞后一个 TTL；
    重拉失败时降级返回旧缓存（低频数据，旧值优于请求失败），无旧缓存则抛出。
    """
    global _rating_cache, _rating_fetched_at
    now = time.time()
    if _rating_cache is not None and now - _rating_fetched_at < _RATING_TTL_SECONDS:
        return _rating_cache
    try:
        df = ak.fund_rating_all()
        _rating_cache = df
        _rating_fetched_at = now
        return df
    except Exception as e:
        if _rating_cache is not None:
            logger.warning(f"fund_rating_all refresh failed, serving stale cache: {e}")
            return _rating_cache
        raise


@app.get("/api/funds/{code}/rating")
@akshare_call
def get_fund_rating(code: str):
    """基金评级（天天基金评级总汇：上海证券/招商证券/济安金信/晨星），无评级返回空列表"""
    df = _rating_df()
    rows = df[df["代码"] == code]
    if rows.empty:
        return []
    return df_to_response(rows, "fund_rating")


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


# ---- Index Daily ----

def _index_daily_sina(code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """新浪指数日线（无日期参数，全量返回）→ 按 YYYYMMDD 闭区间裁剪。"""
    df = ak.stock_zh_index_daily(symbol=code)
    if df is None or df.empty:
        return df
    dates = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
    return df[(dates >= start_date) & (dates <= end_date)]


@app.get("/api/index/{code}/daily")
@akshare_call
def get_index_daily(
    code: str,
    start_date: str = Query("19900101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20500101", description="结束日期 YYYYMMDD"),
):
    """指数日线行情（code 需带市场前缀，如 sh000905 中证500）。

    东财 push2his 对连续请求反爬断连（实测连续请求即被服务端断开，秒级重试无效），
    主用东财，失败或空结果时回退新浪源。
    """
    try:
        df = ak.stock_zh_index_daily_em(symbol=code, start_date=start_date, end_date=end_date)
    except Exception as e:
        logger.warning(f"index daily em failed, fallback to sina: {code} ({e})")
        df = None
    if df is None or df.empty:
        df = _index_daily_sina(code, start_date, end_date)
    if df is None or df.empty:
        return []
    df = df[INDEX_DAILY_COLUMNS].rename(columns={"date": "trade_date"})
    return df_to_response(df)


# ---- Main ----

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
