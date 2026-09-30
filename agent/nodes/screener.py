"""Screener 节点（fund_screening，Step 1）。

职责（agent/docs/fund-screening.md §2）：
- NL → ScreenSpec：LLM 结构化输出（JSON Mode + Pydantic，先例 thesis.py），失败/无 LLM → 规则兜底；
- 候选池构建：collector 排行表按主类切分（1 类型 1 次调用，自带收益列）；
- 预筛：候选池级字段 + 锚点 → 预选集 Top M（确定性，纯函数 preselect_universe）；
- 产出：screen_spec / fund_ids=预选集 / screen_rank_rows / screening_meta。

强约束：过滤与排序不走 LLM；模糊词映射（低回撤/规模别太小）只落在规则兜底与
assumptions 披露中，不假装精确。
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple, TypedDict

from pydantic import ValidationError

from domain.evidence import LlmInteraction, TokenUsage
from domain.screening import (
    ScreenSpec,
    ScreeningMeta,
    ANCHOR_COLUMN_LABELS,
    SortKey,
    anchor_fell_back,
    lookback_return_column,
)
from limits import SCREENING_PRESELECT_LIMIT
from llm.base import LLMError, LLMProvider, Message
from state import FundForgeState, current_usage
from tools.collector_client import CollectorClient, CollectorError

logger = logging.getLogger(__name__)

# ---- 确定性解析：rank 表取值 ----

_MISSING_MARKERS = {"--", "—", "-", ""}


def parse_percent(raw: Any) -> float | None:
    """rank 表百分比字段 → 小数（"35.60%" → 0.356）。

    源表百分比均以百分数单位给出（字符串带 %，或裸数字），统一 /100；
    "--"/空/None 等缺失标记返回 None（不编造）。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) / 100
    text = str(raw).strip().replace(",", "")
    if text in _MISSING_MARKERS:
        return None
    try:
        value = float(text.rstrip("%"))
    except ValueError:
        return None
    return value / 100


# ---- 确定性解析：规则兜底（LLM 失败/不可用时） ----

# 类型别名 → rank symbol。别名表同时含 CJK（"债券"）与 ASCII（"QDII"）条目，
# 匹配统一在小写文本上进行：str.lower() 对 CJK 是恒等变换，故两类条目均正确，
# 无需按字符码位区分大小写敏感性。
_TYPE_ALIASES: tuple[tuple[str, str], ...] = (
    ("债券", "债券型"),
    ("股票", "股票型"),
    ("混合", "混合型"),
    ("指数", "指数型"),
    ("qdii", "QDII"),
    ("fof", "FOF"),
    ("lof", "LOF"),
)

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
_YEAR_CHARS = "一二两三四五0-9"

_YEAR_RE = re.compile(rf"近\s*([{_YEAR_CHARS}]+)\s*年")
_DRAWDOWN_LIMIT_RE = re.compile(r"回撤[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*%")
_SHARPE_LIMIT_RE = re.compile(r"夏普(?:比率)?[^0-9]{0,4}(\d+(?:\.\d+)?)")
_AUM_LIMIT_RE = re.compile(r"规模[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*亿")
_TOPN_RE = re.compile(r"(?:前|选|挑)\s*(\d+)\s*只")
# 排除类型解析（规则兜底）。两条约束共同决定实现形态：
# 1. 类型词必须紧邻排除动词（至多 4 字），否则「不含 qdii 的指数基金」会把
#    用户要保留的指数型误判为排除对象（错误地缩小候选池）；
# 2. 但要能吃掉「不要债券型和货币型」这类列举，否则只应用第一个类型、
#    其余静默丢弃（条件部分生效且无提示）——故类型词后允许「和/与/、/及」续接。
_TYPE_TOKEN = (
    r"(?:QDII|FOF|LOF|股票型|混合型|债券型|指数型|股票|混合|债券|指数|[\u4e00-\u9fff]{2,4}型)"
)
_EXCLUDE_TYPES_RE = re.compile(
    rf"(?:不要|剔除|不含|排除)[^，。,；;]{{0,4}}?(?<!持仓)"
    rf"({_TYPE_TOKEN}(?:\s*(?:和|与|、|及|还有)\s*{_TYPE_TOKEN})*)",
    re.IGNORECASE,
)
# 从匹配片段中逐个取出类型词
_TYPE_TOKEN_RE = re.compile(_TYPE_TOKEN, re.IGNORECASE)
_CLAUSE_SPLIT_RE = re.compile(r"[，。,；;]")
_RETURN_LIMIT_RE = re.compile(
    rf"近\s*([{_YEAR_CHARS}]+)\s*年(?:收益)?(?:超过|大于|高于|不低于)?\s*(\d+(?:\.\d+)?)\s*%"
)


def _to_year(text: str) -> int:
    """「3」/「三」/「两」→ 年数；无法解析返回 0（调用方按不支持处理）。"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    return _CN_DIGITS.get(text[:1], 0)


def _extract_types(query: str) -> list[str]:
    """主类提取：NL 词 → rank symbol；「主动权益」展开为股票型+混合型。"""
    types: list[str] = []
    if "权益" in query:
        types.extend(["股票型", "混合型"])
    for alias, symbol in _TYPE_ALIASES:
        if symbol not in types and alias in query.lower():
            types.append(symbol)
    return types


# 主类被排除条件剔除干净 → 取数为空、可选范围为空。规则兜底与 LLM 两条路径
# 共用同一判据与文案，避免同一事实在不同路径下说法不一。
# 不尝试改为「全部减 X」：排行表按 symbol 取数，"全部"是单次调用拿全市场，
# 无处可减；如实披露即可（正则兜底的能力边界，不做过度优化）。
EMPTY_UNIVERSE_EXCLUDE_DISCLOSURE = "筛选主类均被排除条件剔除，可选范围为空"


def _is_universe_emptied(fund_types: list[str], exclude_types: list[str]) -> bool:
    """主类是否全被排除条件剔除（取数将退化为空候选池）。"""
    return bool(fund_types) and bool(exclude_types) and set(fund_types) <= set(exclude_types)


def _extract_exclude_types(query: str) -> tuple[list[str], list[str]]:
    """排除类型提取：NL 排除子句 → (rank symbol 列表, 无法映射的类型词)。

    以标点切分子句并在子句内按「动词 + 邻近类型（可列举）」匹配：
    子句提及「持仓」时整句交给持仓规则。
    返回两段而非一段：映射不上的类型必须交给调用方进
    unsupported_requirements（同 _normalize_spec 的 LLM 路径处理），不得静默丢弃。
    """
    symbols: list[str] = []
    unmapped: list[str] = []
    for clause in _CLAUSE_SPLIT_RE.split(query):
        # 子句提及「持仓」时整句交给持仓规则：「股票/债券/指数」既可指持仓也可
        # 指主类，按句判定比按词判定更少误报
        if "持仓" in clause:
            continue
        for match in _EXCLUDE_TYPES_RE.finditer(clause):
            for token in _TYPE_TOKEN_RE.findall(match.group(1)):
                symbol = _match_type_alias(token)
                if symbol is None:
                    if token not in unmapped:
                        unmapped.append(token)
                elif symbol not in symbols:
                    symbols.append(symbol)
    return symbols, unmapped


def parse_screen_spec_rules(query: str) -> ScreenSpec:
    """规则兜底：关键词/数字 → ScreenSpec。

    只落地确定性可提取的条件；模糊词（低回撤/规模别太小）映射为默认阈值或
    排序意图并写入 assumptions，无法落地的条件写入 unsupported_requirements。
    """
    fund_types = _extract_types(query)
    # 排除类型：fund_types 保持含被排除项，由 ScreenerNode 取数时按 exclude_types
    # 扣除（screen_finalize 也依赖 fund_types 与 exclude_types 的交集渲染披露，
    # 故不在此处移除）。LLM 路径的 exclude_types 由 _normalize_spec 归一化填写。
    exclude_types, unmapped_excludes = _extract_exclude_types(query)
    assumptions: list[str] = []
    unsupported: list[str] = []

    # 回溯窗口：仅支持 1/3/5 年（rank 表收益列决定）；中文数字（近三年）等价处理
    lookback = 3
    year_match = _YEAR_RE.search(query)
    if year_match:
        years = _to_year(year_match.group(1))
        if years in (1, 3, 5):
            lookback = years
        else:
            assumptions.append(f"仅支持 1/3/5 年窗口，近{years}年已按 3 年处理")

    # 区间收益阈值：近N年收益超过 x%（候选池级唯一收益条件）
    min_period_return: float | None = None
    return_match = _RETURN_LIMIT_RE.search(query)
    if return_match:
        years = _to_year(return_match.group(1))
        if years in (1, 3, 5):
            lookback = years
        min_period_return = float(return_match.group(2)) / 100

    # 回撤：数字 → 硬过滤（不深于该值）；「低回撤」无数字 → 回撤排序意图
    max_max_drawdown: float | None = None
    drawdown_match = _DRAWDOWN_LIMIT_RE.search(query)
    if drawdown_match:
        max_max_drawdown = -float(drawdown_match.group(1)) / 100
    sort_by = SortKey.SHARPE
    if max_max_drawdown is None and "回撤" in query:
        sort_by = SortKey.MAX_DRAWDOWN
        assumptions.append("「低回撤」按回撤升序（浅回撤优先）排序，未给具体阈值")

    # 夏普：数字 → 硬过滤；「夏普高」即为默认排序，无需处理
    min_sharpe: float | None = None
    sharpe_match = _SHARPE_LIMIT_RE.search(query)
    if sharpe_match:
        min_sharpe = float(sharpe_match.group(1))

    # 规模：数字 → 硬过滤（亿元）；「别太小」→ 默认 ≥10 亿（披露假设）
    min_aum: float | None = None
    aum_match = _AUM_LIMIT_RE.search(query)
    if aum_match:
        min_aum = float(aum_match.group(1))
    elif "规模" in query:
        min_aum = 10.0
        assumptions.append("「规模别太小」默认按 ≥10 亿处理（可给出具体数值）")

    # 持有期限 / 细分语义词 → 披露假设
    if "长期" in query:
        assumptions.append("「长期」以 3 年回溯窗口与风险指标优先体现")
    if "宽基" in query:
        assumptions.append("「宽基」未细分：按主类筛选，含行业指数")

    # 无法落地的条件 → unsupported_requirements（进 data_gaps，不装作满足）
    if re.search(r"(不要|剔除|不含|排除).{0,8}持仓", query):
        unsupported.append("持仓剔除条件暂不支持（候选池级排行表无持仓列）")
    if unmapped_excludes:
        # 枚举外主类（如"不要货币型"）：无法映射到排行表主类，条件不生效
        unsupported.append("排除类型条件未落地（该类型不在排行表主类枚举内）")
    if _is_universe_emptied(fund_types, exclude_types):
        unsupported.append(EMPTY_UNIVERSE_EXCLUDE_DISCLOSURE)
    if "跑赢" in query or "跑输" in query:
        unsupported.append("跑赢/跑输基准（超额收益）条件暂不支持（无基准超额筛选能力）")
    if "年化" in query and return_match is None:
        unsupported.append("年化收益条件未落地：候选池级仅支持区间收益（近1/3/5年列）")

    top_n = 5
    topn_match = _TOPN_RE.search(query)
    if topn_match:
        top_n = max(1, min(int(topn_match.group(1)), 10))

    return ScreenSpec(
        fund_types=fund_types,
        exclude_types=exclude_types,
        min_period_return=min_period_return,
        lookback_years=lookback,
        min_sharpe=min_sharpe,
        max_max_drawdown=max_max_drawdown,
        min_aum=min_aum,
        sort_by=sort_by,
        top_n=top_n,
        raw_query=query,
        assumptions=assumptions,
        unsupported_requirements=unsupported,
    )


# ---- 确定性预筛：候选池 → 预选集 ----


class RankRow(NamedTuple):
    """排行表一行 + 其锚点列收益（小数）。"""

    row: dict[str, Any]
    anchor_return: float


@dataclass
class PreselectResult:
    """预筛产出：预选集原始行 + 锚点收益值 + 过程元信息。"""

    rows: list[dict[str, Any]] = field(default_factory=list)
    anchor_values: dict[str, float] = field(default_factory=dict)  # fund_code → 锚点收益（小数）
    meta: ScreeningMeta = field(default_factory=ScreeningMeta)


def preselect_universe(
    rows: list[dict[str, Any]],
    spec: ScreenSpec,
    preselect_limit: int = SCREENING_PRESELECT_LIMIT,
) -> PreselectResult:
    """确定性预筛：按锚点列（lookback 对应收益列）过滤 + 排序 → Top M。

    - 缺锚点值的行无法排序/验证 → 跳过并计数（skipped_no_anchor）；
    - min_period_return 在锚点列上过滤（同一列，见 spec 字段注释）；
    - 排序方向：默认降序；sort_by=period_return 且 sort_order=asc 时升序。
    """
    column = lookback_return_column(spec.lookback_years)
    seen: set[str] = set()
    parsed: list[RankRow] = []
    skipped = 0
    for row in rows:
        code = str(row.get("fund_code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        value = parse_percent(row.get(column))
        if value is None:
            skipped += 1
            continue
        parsed.append(RankRow(row, value))

    universe_size = len(seen)
    filtered = 0
    if spec.min_period_return is not None:
        before = len(parsed)
        parsed = [p for p in parsed if p.anchor_return >= spec.min_period_return]
        filtered = before - len(parsed)

    ascending = spec.sort_by == SortKey.PERIOD_RETURN and spec.sort_order == "asc"
    parsed.sort(key=lambda p: p.anchor_return, reverse=not ascending)
    chosen = parsed[:preselect_limit]

    meta = ScreeningMeta(
        universe_size=universe_size,
        preselected_size=len(chosen),
        anchor_column=column,
        skipped_no_anchor=skipped,
        filtered_by_conditions=filtered,
    )
    return PreselectResult(
        rows=[p.row for p in chosen],
        anchor_values={str(p.row.get("fund_code")): p.anchor_return for p in chosen},
        meta=meta,
    )


# ---- 节点 ----

class ScreenerOutput(TypedDict, total=False):
    """Screener 节点输出（screen_spec / fund_ids / screen_rank_rows / screening_meta + LLM 记录）。"""

    screen_spec: ScreenSpec
    fund_ids: list[str]
    screen_rank_rows: dict[str, dict]
    screening_meta: ScreeningMeta
    llm_interactions: list[LlmInteraction]
    token_usage: TokenUsage
    data_quality_issues: list[str]


_COLUMN_LABELS = ANCHOR_COLUMN_LABELS

_TYPE_SYMBOLS = {"股票型", "混合型", "债券型", "指数型", "QDII", "FOF", "LOF"}


def _spec_shape_hint() -> str:
    """给 LLM 的结构提示：字段名与默认值取自 ScreenSpec 本身，避免双写漂移。

    不用 ScreenSpec.model_json_schema()：当前 LLM 走 JSON Mode
    （response_format=json_object，见 llm/openai_compat.py 模块 docstring），
    provider 不下发 schema，只能靠 prompt 描述 + 调用方 Pydantic 校验；
    且 json_schema 的 $ref/$defs 结构会显著抬高 token 与模型出错率。
    """
    spec = ScreenSpec()
    fields = {
        name: getattr(spec, name)
        for name in ScreenSpec.model_fields
        if name != "raw_query"   # raw_query 由系统回填（规则 5）
    }
    return json.dumps(fields, ensure_ascii=False)


_SPEC_SYSTEM_PROMPT = f"""你是基金筛选条件解析器，把用户的自然语言筛选需求转为结构化 JSON（ScreenSpec）。

规则：
1. 只输出符合以下结构的 JSON，禁止编造字段或额外文本。字段与默认值：
{_spec_shape_hint()}
   其中 fund_types / exclude_types 的取值只能是：{"、".join(sorted(_TYPE_SYMBOLS))}。
2. 收益/回撤/波动均为小数：区间收益 20% → 0.20；回撤阈值 20% → -0.20（回撤为负值，语义「不深于该值」）。
3. 无法落地的条件（如不要持仓某股、跑赢某基准、年化收益）写入 unsupported_requirements，不要假装可筛。
4. 模糊词（低回撤/规模别太小/长期持有）写入 assumptions 并给出你采用的默认值。
5. lookback_years 只能取 1/3/5；raw_query 留空，由系统回填。
"""


def _prompt_text(messages: list[Message]) -> str:
    """把 messages 展开为可读全文（本地运行记录用）。"""
    return "\n\n".join(f"[{m.role}]\n{m.content}" for m in messages)


def _match_type_alias(text: str) -> str | None:
    """按别名表匹配首个 rank symbol；无匹配返回 None。

    统一在 lowered 上匹配（CJK 经 lower() 恒等，见 _TYPE_ALIASES 注释）。
    """
    lowered = text.lower()
    for alias, symbol in _TYPE_ALIASES:
        if alias in lowered:
            return symbol
    return None


def _normalize_type(name: str) -> str | None:
    """LLM 输出的类型词 → rank symbol；无法映射返回 None（进 unsupported）。"""
    text = str(name).strip()
    if text in _TYPE_SYMBOLS:
        return text
    return _match_type_alias(text)


def _anchor_text(spec: ScreenSpec, meta: ScreeningMeta) -> str:
    """预筛锚点描述（随报告强制披露；5 年窗口回退须显式披露）。"""
    label = _COLUMN_LABELS.get(meta.anchor_column, meta.anchor_column)
    direction = "升序" if (spec.sort_by == SortKey.PERIOD_RETURN and spec.sort_order == "asc") else "降序"
    text = f"{label}收益{direction}（M={SCREENING_PRESELECT_LIMIT}）"
    if anchor_fell_back(spec.lookback_years):
        text += f"；{spec.lookback_years} 年窗口无排行列，回退{_COLUMN_LABELS[meta.anchor_column]}"
    return text


class ScreenerNode:
    """Screener 节点：NL→ScreenSpec（LLM+规则兜底）→ 候选池构建 → 预筛。"""

    def __init__(self, client: CollectorClient, llm: LLMProvider | None) -> None:
        self._client = client
        self._llm = llm

    def __call__(self, state: FundForgeState) -> ScreenerOutput:
        query = state.get("user_query", "")
        spec, interactions, usage, issues = self._parse_spec(query)

        # 候选池构建：主类逐个取排行表（exclude_types 在取数层面执行）；
        # 未指定主类 → 全部（1 次调用）；全部类型被排除 → 不取数，候选池为空
        if spec.fund_types:
            symbols = [t for t in spec.fund_types if t not in set(spec.exclude_types)]
        else:
            symbols = ["全部"]
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                rows.extend(self._client.get_fund_rank(symbol))
            except CollectorError as e:
                issues.append(f"排行表获取失败（{symbol}）：{e}")

        result = preselect_universe(rows, spec)
        meta = result.meta.model_copy(update={"anchor": _anchor_text(spec, result.meta)})

        rank_rows: dict[str, dict[str, Any]] = {}
        for row in result.rows:
            code = str(row.get("fund_code"))
            rank_rows[code] = {
                "fund_name": row.get("fund_name"),
                "anchor_column": meta.anchor_column,
                "anchor_return": result.anchor_values[code],
                "fee_rate": row.get("fee_rate"),
            }

        logger.info(
            "screener: universe=%d preselected=%d anchor=%s",
            meta.universe_size,
            meta.preselected_size,
            meta.anchor,
        )
        output = ScreenerOutput(
            screen_spec=spec,
            fund_ids=[str(row.get("fund_code")) for row in result.rows],
            screen_rank_rows=rank_rows,
            screening_meta=meta,
            data_quality_issues=[*state.get("data_quality_issues", []), *issues],
        )
        if interactions:
            output["llm_interactions"] = [*state.get("llm_interactions", []), *interactions]
            output["token_usage"] = current_usage(state).merged(usage)
        return output

    # ---- 解析（LLM 结构化输出，失败 → 规则兜底） ----

    def _parse_spec(
        self, query: str
    ) -> tuple[ScreenSpec, list[LlmInteraction], TokenUsage, list[str]]:
        if self._llm is None:
            return parse_screen_spec_rules(query), [], TokenUsage(), []

        interactions: list[LlmInteraction] = []
        model_name = getattr(self._llm, "model", None)
        messages = [Message("system", _SPEC_SYSTEM_PROMPT), Message("user", query)]
        prompt_text = _prompt_text(messages)
        response_text: str | None = None
        try:
            response = self._llm.generate(messages, structured_output=ScreenSpec)
            response_text = response.content
            usage = TokenUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                llm_calls=1,
            )
            spec = ScreenSpec.model_validate_json(response.content)
            interactions.append(
                LlmInteraction(
                    node="screener",
                    model=model_name,
                    prompt=prompt_text,
                    response=response_text,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    ok=True,
                )
            )
        except (LLMError, ValidationError, ValueError) as e:
            interactions.append(
                LlmInteraction(
                    node="screener",
                    model=model_name,
                    prompt=prompt_text,
                    response=response_text or (e.content if isinstance(e, LLMError) else None),
                    input_tokens=e.input_tokens if isinstance(e, LLMError) else 0,
                    output_tokens=e.output_tokens if isinstance(e, LLMError) else 0,
                    ok=False,
                    error=f"{type(e).__name__}: {e}",
                )
            )
            issue = f"ScreenSpec LLM 解析失败，已按规则兜底：{type(e).__name__}: {e}"
            logger.warning("screener: %s", issue)
            return parse_screen_spec_rules(query), interactions, TokenUsage(), [issue]

        if not spec.raw_query:
            spec = spec.model_copy(update={"raw_query": query})
        return self._normalize_spec(spec), interactions, usage, []

    def _normalize_spec(self, spec: ScreenSpec) -> ScreenSpec:
        """LLM 产物归一化：类型词映射到 rank symbol；无法映射 → unsupported（不装作可筛）。"""
        types: list[str] = []
        unsupported = list(spec.unsupported_requirements)
        for name in spec.fund_types:
            symbol = _normalize_type(name)
            if symbol is None:
                unsupported.append(f"基金类型「{name}」无法映射到排行表主类，已忽略")
                continue
            if symbol not in types:
                types.append(symbol)
        # exclude_types 与 fund_types 同一套归一化：映射不上的排除条件不得静默失效
        excludes: list[str] = []
        for name in spec.exclude_types:
            symbol = _normalize_type(name)
            if symbol is None:
                unsupported.append(f"排除类型「{name}」无法映射到排行表主类，已忽略")
                continue
            if symbol not in excludes:
                excludes.append(symbol)
        if excludes and not types:
            # 判据用归一化后的 types：主类可能全部映射失败（types 归空）而
            # exclude_types 仍非空——此时取数退化为「全部」，排除条件无对象可扣，
            # 属静默失效，必须披露。用原始 spec.fund_types 判断会漏掉此情形。
            unsupported.append("未指定主类时 exclude_types 无法在排行表层面执行，已忽略")
        elif excludes:
            # 排除项与主类无交集：取数结果正确（候选池本就不含该类），但报告的
            # 条件复述只渲染生效的排除项，故未生效的事实须在此披露
            ineffective = [t for t in excludes if t not in set(types)]
            if ineffective:
                unsupported.append(
                    f"排除类型「{'、'.join(ineffective)}」不在筛选主类内，"
                    "条件未生效（候选池本就不含该类型）"
                )
        if _is_universe_emptied(types, excludes):
            unsupported.append(EMPTY_UNIVERSE_EXCLUDE_DISCLOSURE)
        updates: dict[str, Any] = {"fund_types": types, "exclude_types": excludes}
        if unsupported != spec.unsupported_requirements:
            updates["unsupported_requirements"] = unsupported
        return spec.model_copy(update=updates)


__all__ = [
    "ScreenerNode",
    "ScreenerOutput",
    "parse_percent",
    "parse_screen_spec_rules",
    "preselect_universe",
    "PreselectResult",
]
