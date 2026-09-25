"""Analysis Engine — 确定性金融计算纯函数（§9）。

简化口径（V1，全部在此显式声明）：
- 收益序列：r_t = v_t / v_{t-1} - 1（简单收益，非对数收益）；
- 净值口径：整个序列统一取 acc_nav（累计净值）或 unit_nav，不逐点混用；
  acc 在有效点内全覆盖时用 acc，否则整序列回退 unit。
  已知简化：累计净值为分红简单加总（非复权、不含分红再投资）；
- 年化收益：(1 + cumulative) ** (365 / 区间自然日) - 1，区间不足 30 个自然日不年化；
- 年化波动：日收益总体标准差（pstdev）* sqrt(252)；
- 最大回撤：max(v_t / run_max - 1)，结果 ≤ 0（无回撤时为 0.0）；
- 夏普（简化）：mean(r) / pstdev(r) * sqrt(252)，无风险利率取 0，波动为 0 时返回 None；
- Sortino（简化）：mean(r) / 下行偏差 * sqrt(252)，下行偏差 = sqrt(mean(min(r, 0)^2))
  （分母为全样本的标准口径），无风险利率取 0，下行偏差为 0 时返回 None；
- 分年度收益：自然年内首末有效净值点的累计收益，年内不足 2 个有效点的年份不列入；
- 回撤修复期：最大回撤谷底到净值首次收复峰值的自然日数，截至期末未修复返回 None；
- 滚动收益：滚动 252 个交易日窗口的累计收益分布（min/median/max），不足一个窗口返回 None；
- 区间（尾部）收益：最近 21/63/126/252 个交易日的累计收益，近似 近1月/近3月/近6月/近1年，
  有效收益不足窗口长度的为 None（不编造）。

不满足计算条件（有效净值点不足）时返回 None，由调用方标记 data_quality。

持仓分析维度（集中度 / 重叠度 / 市场分布）同样为确定性纯函数：
- 集中度：最新报告期前十大持仓占净值比例合计（%）；
- 重叠度：两基金最新报告期持仓（按股票名）的 Jaccard 重叠率；
- 市场分布：按股票代码形态分类（6 位数字=A股、5 位数字=港股、字母=美股等海外），
  各类占净值比例合计（%）——代码形态为启发式，无法识别的归入 other。
"""

import math
import re
import statistics

from domain.analysis import (
    FundConcentration,
    FundMetrics,
    HoldingsOverlap,
    MarketSplit,
    RollingReturnSummary,
)
from domain.fund import (
    Holding,
    IndexPoint,
    NAVPoint,
    latest_report_period,
    top_holdings,
)
from domain.shared import DataQuality

TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365
_MIN_DAYS_FOR_ANNUALIZATION = 30
_MAX_COMMON_NAMES = 10
_ROLLING_WINDOW_DAYS = 252

_A_SHARE_RE = re.compile(r"^\d{6}$")
_HK_SHARE_RE = re.compile(r"^\d{5}$")
_OVERSEAS_RE = re.compile(r"^[A-Za-z][A-Za-z.\-]*$")


def nav_value(point: NAVPoint, basis: str) -> float | None:
    """指定口径下的单点净值；该口径缺失即为无效点，不做逐点回退（避免口径混用）。"""
    return point.acc_nav if basis == "acc" else point.unit_nav


def _select_basis(points: list[NAVPoint]) -> str:
    """序列级净值口径：有效点 acc 全覆盖用 acc，否则整序列回退 unit。"""
    valid = [p for p in points if p.has_value]
    return "acc" if valid and all(p.acc_nav is not None for p in valid) else "unit"


def simple_returns(values: list[float]) -> list[float]:
    """简单收益序列 r_t = v_t / v_{t-1} - 1（n 个值 → n-1 个收益）。"""
    return [
        values[i] / values[i - 1] - 1
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]


def cumulative_return(values: list[float]) -> float | None:
    """区间累计收益 v_n / v_1 - 1；少于 2 个点返回 None。"""
    if len(values) < 2 or values[0] == 0:
        return None
    return values[-1] / values[0] - 1


def annualized_return(values: list[float], days: int) -> float | None:
    """几何年化收益；区间不足 30 个自然日时年化无意义，返回 None。"""
    cum = cumulative_return(values)
    if cum is None or days < _MIN_DAYS_FOR_ANNUALIZATION:
        return None
    return (1.0 + cum) ** (DAYS_PER_YEAR / days) - 1.0


def annualized_volatility(returns: list[float]) -> float | None:
    """年化波动率 = pstdev(r) * sqrt(252)；少于 2 个收益返回 None。"""
    if len(returns) < 2:
        return None
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / len(returns)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(values: list[float]) -> float | None:
    """最大回撤（≤ 0）；少于 2 个点返回 None。"""
    if len(values) < 2:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def sharpe_ratio(returns: list[float], risk_free_daily: float = 0.0) -> float | None:
    """简化夏普 = mean(r - rf) / pstdev(r - rf) * sqrt(252)；波动为 0 时返回 None。"""
    if len(returns) < 2:
        return None
    excess = [r - risk_free_daily for r in returns]
    mu = sum(excess) / len(excess)
    var = sum((e - mu) ** 2 for e in excess) / len(excess)
    if var == 0:
        return None
    return mu / math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(returns: list[float], risk_free_daily: float = 0.0) -> float | None:
    """简化 Sortino = mean(r - rf) / 下行偏差 * sqrt(252)；下行偏差为 0 时返回 None。

    下行偏差 = sqrt(mean(min(r - rf, 0)^2))，分母为全样本（标准 Sortino 口径），
    只惩罚下行波动。
    """
    if len(returns) < 2:
        return None
    excess = [r - risk_free_daily for r in returns]
    mu = sum(excess) / len(excess)
    downside = math.sqrt(sum(min(e, 0.0) ** 2 for e in excess) / len(excess))
    if downside == 0:
        return None
    return mu / downside * math.sqrt(TRADING_DAYS_PER_YEAR)


def yearly_returns(series: list[tuple]) -> dict[str, float | None]:
    """分年度收益：自然年内首末有效净值点的累计收益。

    series 为 (date, value) 序列；年内有效点不足 2 个的年份不列入（不编造）。
    """
    by_year: dict[int, list[float]] = {}
    for d, v in series:
        by_year.setdefault(d.year, []).append(v)
    return {
        str(year): cumulative_return(vals)
        for year, vals in sorted(by_year.items())
        if len(vals) >= 2
    }


def drawdown_recovery_days(series: list[tuple]) -> int | None:
    """最大回撤修复期：谷底到净值首次收复谷底对应峰值的自然日数。

    series 为 (date, value) 序列；全程无回撤返回 0，截至期末未修复返回 None。
    """
    if len(series) < 2:
        return None
    values = [v for _, v in series]
    peak = values[0]
    trough_idx: int | None = None
    trough_ratio = 1.0
    trough_peak = 0.0
    for i, v in enumerate(values):
        peak = max(peak, v)
        if peak <= 0:
            continue
        ratio = v / peak
        if ratio < trough_ratio:
            trough_idx, trough_ratio, trough_peak = i, ratio, peak
    if trough_idx is None:
        return 0
    for i in range(trough_idx + 1, len(values)):
        if values[i] >= trough_peak:
            return (series[i][0] - series[trough_idx][0]).days
    return None


def rolling_return_summary(
    returns: list[float], window: int = _ROLLING_WINDOW_DAYS
) -> RollingReturnSummary | None:
    """滚动 window 个交易日窗口的累计收益分布；不足一个窗口返回 None。"""
    if len(returns) < window:
        return None
    rolls = []
    for i in range(len(returns) - window + 1):
        cum = 1.0
        for r in returns[i : i + window]:
            cum *= 1.0 + r
        rolls.append(cum - 1.0)
    return RollingReturnSummary(
        window_days=window,
        min=min(rolls),
        median=statistics.median(rolls),
        max=max(rolls),
    )


# (标签, 窗口交易日数)：21/63/126/252 ≈ 1/3/6/12 个月
TRAILING_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1m", 21),
    ("3m", 63),
    ("6m", 126),
    ("1y", 252),
)


def trailing_returns(
    returns: list[float], windows: tuple[tuple[str, int], ...] = TRAILING_WINDOWS
) -> dict[str, float | None]:
    """区间（尾部）收益：最近 k 个交易日累计收益（21/63/126/252 ≈ 1/3/6/12 个月）。

    有效收益不足 k 个的窗口为 None（不编造），标签与 TRAILING_WINDOWS 一致。
    """
    out: dict[str, float | None] = {}
    for label, k in windows:
        if len(returns) < k:
            out[label] = None
            continue
        cum = 1.0
        for r in returns[-k:]:
            cum *= 1.0 + r
        out[label] = cum - 1.0
    return out


def benchmark_comparison(
    fund_points: list[NAVPoint],
    basis: str,
    index_points: list[IndexPoint],
) -> tuple[float | None, float | None]:
    """净值 vs 基准指数（按日期对齐）→ (超额累计收益, 近似跟踪误差年化)。

    近似跟踪误差 = 对齐日收益差（基金日收益 − 指数日收益）的年化标准差，
    替代无公开披露源的实测跟踪误差；对齐点不足 2 个返回 (None, None)。
    """
    bench = {p.nav_date: p.close for p in index_points if p.close is not None}
    pairs = [
        (p.nav_date, v)
        for p in fund_points
        if (v := nav_value(p, basis)) is not None and p.nav_date in bench
    ]
    if len(pairs) < 2:
        return None, None
    fund_navs = [v for _, v in pairs]
    bench_navs = [bench[d] for d, _ in pairs]
    fund_cum = cumulative_return(fund_navs)
    bench_cum = cumulative_return(bench_navs)
    excess = (
        fund_cum - bench_cum
        if fund_cum is not None and bench_cum is not None
        else None
    )
    fund_rets = simple_returns(fund_navs)
    bench_rets = simple_returns(bench_navs)
    daily_excess = [f - b for f, b in zip(fund_rets, bench_rets)]
    return excess, annualized_volatility(daily_excess)


def _market_of(stock_code: str) -> str:
    """按代码形态归类市场：6 位数字=A股、5 位数字=港股、字母=美股等海外。"""
    code = stock_code.strip()
    if _A_SHARE_RE.match(code):
        return "a_share"
    if _HK_SHARE_RE.match(code):
        return "hk_share"
    if _OVERSEAS_RE.match(code):
        return "overseas"
    return "other"


def market_split(holdings: list[Holding]) -> MarketSplit | None:
    """最新报告期披露持仓的市场分布（各类占净值比例合计 %）；无任何有效权重返回 None。"""
    buckets: dict[str, list[float]] = {}
    for h in _latest_period_rows(holdings):
        if h.hold_ratio is None:
            continue
        buckets.setdefault(_market_of(h.stock_code), []).append(h.hold_ratio)
    if not buckets:
        return None
    ratios = {key: sum(vals) for key, vals in buckets.items()}
    return MarketSplit(
        a_share_ratio=ratios.get("a_share"),
        hk_share_ratio=ratios.get("hk_share"),
        overseas_ratio=ratios.get("overseas"),
        other_ratio=ratios.get("other"),
    )


def _quality_of(n_valid: int) -> DataQuality:
    """有效净值点数量 → 数据质量：0 missing / 1 partial / ≥2 complete。"""
    if n_valid == 0:
        return DataQuality.MISSING
    if n_valid == 1:
        return DataQuality.PARTIAL
    return DataQuality.COMPLETE


def compute_fund_metrics(points: list[NAVPoint], basis: str = "auto") -> FundMetrics:
    """对单只基金的净值序列计算全部指标（Engine 的组合入口）。

    basis："acc" / "unit" 显式指定口径；"auto" 为 acc 全覆盖则 acc，否则整序列 unit。
    """
    chosen = basis if basis in ("acc", "unit") else _select_basis(points)
    valid = [(p, v) for p in points if (v := nav_value(p, chosen)) is not None]
    navs = [v for _, v in valid]
    returns = simple_returns(navs)
    series = [(p.nav_date, v) for p, v in valid]

    period_start = valid[0][0].nav_date if valid else None
    period_end = valid[-1][0].nav_date if valid else None
    days = (period_end - period_start).days if period_start and period_end else 0

    return FundMetrics(
        period_start=period_start,
        period_end=period_end,
        nav_point_count=len(navs),
        cumulative_return=cumulative_return(navs),
        annualized_return=annualized_return(navs, days),
        annual_volatility=annualized_volatility(returns),
        max_drawdown=max_drawdown(navs),
        max_drawdown_recovery_days=drawdown_recovery_days(series),
        sharpe=sharpe_ratio(returns),
        sortino=sortino_ratio(returns),
        yearly_returns=yearly_returns(series),
        rolling_1y=rolling_return_summary(returns),
        trailing_returns=trailing_returns(returns),
        nav_basis=chosen,
        data_quality=_quality_of(len(navs)),
    )


def _latest_period_rows(holdings: list[Holding]) -> list[Holding]:
    """最新报告期的持仓行；无任何可解析报告期时返回全部行（不编造报告期）。"""
    period = latest_report_period(holdings)
    if period is None:
        return list(holdings)
    return [h for h in holdings if h.report_date == period]


def fund_concentration(holdings: list[Holding], fund_id: str) -> FundConcentration:
    """最新报告期前十大持仓集中度与持仓个股数；无有效权重数据时 top10_sum 为 None。"""
    top10 = top_holdings(holdings, 10)
    ratios = [h.hold_ratio for h in top10 if h.hold_ratio is not None]
    return FundConcentration(
        fund_id=fund_id,
        top10_sum=sum(ratios) if ratios else None,
        holding_count=len(_latest_period_rows(holdings)),
    )


def holdings_overlap(
    holdings_a: list[Holding],
    holdings_b: list[Holding],
    fund_a: str,
    fund_b: str,
) -> HoldingsOverlap:
    """两基金最新报告期持仓（按股票名）的 Jaccard 重叠率；任一侧无持仓时 ratio 为 None。"""
    names_a = {h.stock_name for h in _latest_period_rows(holdings_a)}
    names_b = {h.stock_name for h in _latest_period_rows(holdings_b)}
    if not names_a or not names_b:
        return HoldingsOverlap(fund_a=fund_a, fund_b=fund_b, overlap_ratio=None, common_names=[])
    common = names_a & names_b
    return HoldingsOverlap(
        fund_a=fund_a,
        fund_b=fund_b,
        overlap_ratio=len(common) / len(names_a | names_b),
        common_names=sorted(common)[:_MAX_COMMON_NAMES],
    )


__all__ = [
    "nav_value",
    "simple_returns",
    "cumulative_return",
    "annualized_return",
    "annualized_volatility",
    "max_drawdown",
    "sharpe_ratio",
    "sortino_ratio",
    "yearly_returns",
    "drawdown_recovery_days",
    "rolling_return_summary",
    "TRAILING_WINDOWS",
    "trailing_returns",
    "compute_fund_metrics",
    "benchmark_comparison",
    "fund_concentration",
    "holdings_overlap",
    "market_split",
]
