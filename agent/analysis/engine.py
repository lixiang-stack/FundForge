"""Analysis Engine — 确定性金融计算纯函数（§9）。

简化口径（V1，全部在此显式声明）：
- 收益序列：r_t = v_t / v_{t-1} - 1（简单收益，非对数收益）；
- 净值口径：整个序列统一取 acc_nav（累计净值）或 unit_nav，不逐点混用；
  acc 在有效点内全覆盖时用 acc，否则整序列回退 unit。
  已知简化：累计净值为分红简单加总（非复权、不含分红再投资）；
- 年化收益：(1 + cumulative) ** (365 / 区间自然日) - 1，区间不足 30 个自然日不年化；
- 年化波动：日收益总体标准差（pstdev）* sqrt(252)；
- 最大回撤：max(v_t / run_max - 1)，结果 ≤ 0（无回撤时为 0.0）；
- 夏普（简化）：mean(r) / pstdev(r) * sqrt(252)，无风险利率取 0，波动为 0 时返回 None。

不满足计算条件（有效净值点不足）时返回 None，由调用方标记 data_quality。

持仓对比维度（集中度 / 重叠度）同样为确定性纯函数：
- 集中度：最新报告期前十大持仓占净值比例合计（%）；
- 重叠度：两基金最新报告期持仓（按股票名）的 Jaccard 重叠率。
"""

import math

from domain.analysis import FundConcentration, FundMetrics, HoldingsOverlap
from domain.fund import Holding, NAVPoint, latest_report_period, top_holdings
from domain.shared import DataQuality

TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365
_MIN_DAYS_FOR_ANNUALIZATION = 30
_MAX_COMMON_NAMES = 10


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
        sharpe=sharpe_ratio(returns),
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
    "compute_fund_metrics",
    "fund_concentration",
    "holdings_overlap",
]
