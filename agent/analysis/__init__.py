"""确定性量化分析包（Analysis Engine，docs/TechnicalContract.md §9）。

纯函数集合：deterministic、testable、reproducible，不依赖 LLM。
计算结果以 calculation 类型 Evidence 写入 State。
"""

from analysis.engine import (
    annualized_return,
    annualized_volatility,
    compute_fund_metrics,
    cumulative_return,
    max_drawdown,
    sharpe_ratio,
    simple_returns,
)

__all__ = [
    "simple_returns",
    "cumulative_return",
    "annualized_return",
    "annualized_volatility",
    "max_drawdown",
    "sharpe_ratio",
    "compute_fund_metrics",
]
