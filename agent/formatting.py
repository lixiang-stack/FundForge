"""数值格式化（报告与节点文案共用）。

放在顶层而非 domain/：格式化是纯表现层工具，不是领域模型；
domain 与 nodes 均可依赖本模块，且不引入任何框架依赖。
"""

__all__ = ["fmt_pct", "fmt_ratio", "TABLE_MISSING", "PROSE_MISSING"]

# 缺失值的两种呈现：表格用占位符，散文用文字，避免同一个 None 在报告里
# 依文件不同而长得不一样。
TABLE_MISSING = "—"
PROSE_MISSING = "未知"


def fmt_pct(value: float | None, missing: str = PROSE_MISSING) -> str:
    """小数 → 百分比字符串（2 位小数）；None → missing。"""
    return f"{value * 100:.2f}%" if value is not None else missing


def fmt_ratio(value: float | None, missing: str = PROSE_MISSING) -> str:
    """比率 → 2 位小数字符串（夏普 / Sortino）；None → missing。"""
    return f"{value:.2f}" if value is not None else missing
