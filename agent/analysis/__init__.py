"""确定性量化分析包（Analysis Engine，docs/TechnicalContract.md §9）。

纯函数集合：deterministic、testable、reproducible，不依赖 LLM。
计算结果以 calculation 类型 Evidence 写入 State。
"""

from analysis.engine import (
    annualized_return,
    annualized_volatility,
    benchmark_comparison,
    compute_fund_metrics,
    cumulative_return,
    drawdown_recovery_days,
    fund_concentration,
    holdings_overlap,
    market_split,
    max_drawdown,
    nav_value,
    rolling_return_summary,
    sharpe_ratio,
    simple_returns,
    sortino_ratio,
    yearly_returns,
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
    "compute_fund_metrics",
    "benchmark_comparison",
    "fund_concentration",
    "holdings_overlap",
    "market_split",
]
