"""基金筛选领域模型（fund_screening，Step 1）。

ScreenSpec 由自然语言解析产出（nodes/screener.py：LLM 结构化输出 + 规则兜底），
ScreenResult 由 screen_finalize 确定性产出。术语见根目录 CONTEXT.md。

执行层规则（agent/docs/fund-screening.md §4）：
- 候选池级字段在预筛执行（rank 表列直接可筛）；
- 预选集级字段在 finalize 执行（analyzer 对 M 只计算后硬过滤）；
- 任一字段无数据来源 → unsupported_requirements → data_gaps（诚实披露，不装作满足）。
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from domain.shared import coerce_model


class SortKey(StrEnum):
    """排序键。以 StrEnum 定义为唯一来源，避免到处使用裸字符串。"""

    PERIOD_RETURN = "period_return"   # rank 表锚点区间收益（不在指标行上，见 SORT_ATTRS）
    SHARPE = "sharpe"
    MAX_DRAWDOWN = "max_drawdown"
    VOLATILITY = "volatility"


# 依赖预选集级风险指标的排序键（触发偏差披露：风险指标仅在预选集内计算）
RISK_SORT_KEYS = frozenset({SortKey.SHARPE, SortKey.MAX_DRAWDOWN, SortKey.VOLATILITY})

# 排序键 → 指标字段名。PeerMetricsRow 与 ShortlistEntry 三者同名单一来源，
# 供 finalize 排序与 evaluator 排序一致性校验共用；PERIOD_RETURN 不在此表
# （其值取自 rank 表锚点而非指标行）。
SORT_ATTRS: dict[SortKey, str] = {
    SortKey.SHARPE: "sharpe",
    SortKey.MAX_DRAWDOWN: "max_drawdown",
    SortKey.VOLATILITY: "annual_volatility",
}

# 排序键 → 报告文案（条件复述章节）
SORT_LABELS: dict[SortKey, str] = {
    SortKey.PERIOD_RETURN: "锚点区间收益",
    SortKey.SHARPE: "夏普",
    SortKey.MAX_DRAWDOWN: "最大回撤（浅回撤优先）",
    SortKey.VOLATILITY: "年化波动",
}

# 回溯年限 → rank 表收益列：5 年无对应列（rank 表最深为近3年），回退近3年且须披露
_ANCHOR_COLUMN: dict[int, str] = {1: "return_1y", 3: "return_3y", 5: "return_3y"}

# 无对应收益列、只能回退的年限。披露文案以此为唯一判据，避免调用方重述
# "哪一年限发生了回退"（原 _anchor_text 手写 lookback_years == 5 判断，
# 与本映射表可能不同步）。
_ANCHOR_FALLBACK_YEARS: frozenset[int] = frozenset({5})

# 锚点列 → 展示名（screener 锚点文案 / finalize 理由与缺口披露共用）
ANCHOR_COLUMN_LABELS: dict[str, str] = {"return_1y": "近1年", "return_3y": "近3年"}


def lookback_return_column(lookback_years: int) -> str:
    """回溯年限 → rank 表收益列名（无对应列的年限回退，见 anchor_fell_back）。"""
    return _ANCHOR_COLUMN[lookback_years]


def anchor_fell_back(lookback_years: int) -> bool:
    """该回溯年限是否走了回退列（须在报告中显式披露样本口径降级）。"""
    return lookback_years in _ANCHOR_FALLBACK_YEARS


# 偏差披露固定文案：finalize 写入 data_gaps，evaluator 校验其存在（共用单一来源防漂移）
BIAS_DISCLOSURE = "风险指标仅在按预筛锚点选出的预选集内计算，相对全候选池存在样本偏差"


class ScreenSpec(BaseModel):
    """筛选规约：自然语言 → 结构化筛选契约（硬过滤 + 排序 + 缺口声明）。"""

    # ---- 候选池级（rank 表列直接可筛） ----
    fund_types: list[str] = Field(default_factory=list)      # 主类，映射 rank symbol
    exclude_types: list[str] = Field(default_factory=list)   # 在按类型取数层面执行
    min_period_return: float | None = None   # 区间收益率（小数），作用于 lookback 对应列
    lookback_years: Literal[1, 3, 5] = 3

    # ---- 预选集级（analyzer 计算后 finalize 硬过滤） ----
    min_sharpe: float | None = None
    max_max_drawdown: float | None = None    # 回撤 ≤0；条件语义为「不深于该值」
    max_volatility: float | None = None
    min_aum: float | None = None             # 亿元；仅过滤不排序（YAGNI）
    max_aum: float | None = None
    min_inception_years: float | None = None

    # ---- 排序（统一在 finalize 执行） ----
    sort_by: SortKey = SortKey.SHARPE
    sort_order: Literal["asc", "desc"] = "desc"
    top_n: int = Field(default=5, ge=1)

    # ---- 解释用 ----
    raw_query: str = ""
    assumptions: list[str] = Field(default_factory=list)
    unsupported_requirements: list[str] = Field(default_factory=list)

    @classmethod
    def from_state(cls, value: "ScreenSpec | dict | None") -> "ScreenSpec | None":
        """State 归一化入口（LangGraph 回传可能是 dict）。"""
        return coerce_model(value, cls)

    def uses_risk_metrics(self) -> bool:
        """是否使用预选集级风险指标（决定偏差披露是否必须出现）。"""
        return (
            self.sort_by in RISK_SORT_KEYS
            or self.min_sharpe is not None
            or self.max_max_drawdown is not None
            or self.max_volatility is not None
        )


class ScreeningMeta(BaseModel):
    """预筛过程元信息（报告披露与 evaluator 校验的数据来源）。

    universe_size 字段名沿用旧术语 universe 未改（State 合同的一部分，改名需
    同步 state / 合同测试），其领域术语已统一为「候选池」，见 CONTEXT.md。
    """

    universe_size: int = 0
    preselected_size: int = 0
    anchor: str = ""            # 预筛锚点描述（随报告强制披露）
    anchor_column: str = ""     # rank 表收益列名
    skipped_no_anchor: int = 0          # 缺锚点列值而未参与预筛的行数
    filtered_by_conditions: int = 0     # 被候选池级条件（如 min_period_return）剔除的行数


class ShortlistEntry(BaseModel):
    """短名单单条：指标 + 一句话理由（Step 1 为确定性模板，Step 2 绑 Evidence）。"""

    fund_id: str
    name: str | None = None
    fund_type: str | None = None
    annualized_return: float | None = None
    max_drawdown: float | None = None
    annual_volatility: float | None = None
    sharpe: float | None = None
    period_return: float | None = None   # 预筛锚点口径（rank 表区间收益，小数）
    aum: float | None = None             # 亿元
    inception_years: float | None = None
    rationale: str = ""


class ScreenResult(BaseModel):
    """筛选最终结果：短名单 + 全部披露（evaluator 校验对象）。"""

    universe_size: int
    preselected_size: int
    anchor: str
    sort_by: SortKey
    sort_order: Literal["asc", "desc"]
    top_n: int
    conditions: list[str] = Field(default_factory=list)   # 人类可读条件复述（报告渲染）
    entries: list[ShortlistEntry] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    empty_reason: str | None = None      # 0 只时的明确原因（绝不放宽阈值）


__all__ = [
    "SortKey",
    "RISK_SORT_KEYS",
    "SORT_ATTRS",
    "SORT_LABELS",
    "lookback_return_column",
    "anchor_fell_back",
    "ANCHOR_COLUMN_LABELS",
    "BIAS_DISCLOSURE",
    "ScreenSpec",
    "ScreeningMeta",
    "ShortlistEntry",
    "ScreenResult",
]
