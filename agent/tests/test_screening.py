"""基金筛选领域模型与纯函数测试（domain/screening.py、nodes/screener.py、nodes/screen_finalize.py）。"""

import pytest
from pydantic import ValidationError

from domain.screening import (
    BIAS_DISCLOSURE,
    RISK_SORT_KEYS,
    SORT_ATTRS,
    SORT_LABELS,
    ScreenResult,
    ScreenSpec,
    ScreeningMeta,
    ShortlistEntry,
    SortKey,
    anchor_fell_back,
    lookback_return_column,
)


class TestScreenSpec:
    def test_defaults(self):
        spec = ScreenSpec(raw_query="帮我选几只债券基金")
        assert spec.fund_types == []
        assert spec.exclude_types == []
        assert spec.min_period_return is None
        assert spec.lookback_years == 3
        assert spec.sort_by == "sharpe"
        assert spec.sort_order == "desc"
        assert spec.top_n == 5
        assert spec.assumptions == []
        assert spec.unsupported_requirements == []

    def test_rejects_invalid_lookback(self):
        with pytest.raises(ValidationError):
            ScreenSpec(raw_query="x", lookback_years=2)

    def test_rejects_invalid_sort_by(self):
        # 规模排序已移除（YAGNI）：aum 只做过滤
        with pytest.raises(ValidationError):
            ScreenSpec(raw_query="x", sort_by="aum")

    def test_rejects_zero_top_n(self):
        with pytest.raises(ValidationError):
            ScreenSpec(raw_query="x", top_n=0)

    def test_from_state_coerces_dict(self):
        spec = ScreenSpec.from_state({"raw_query": "x", "top_n": 3})
        assert isinstance(spec, ScreenSpec)
        assert spec.top_n == 3

    def test_from_state_passthrough_and_none(self):
        spec = ScreenSpec(raw_query="x")
        assert ScreenSpec.from_state(spec) is spec
        assert ScreenSpec.from_state(None) is None

    def test_uses_risk_metrics(self):
        assert not ScreenSpec(raw_query="x", sort_by="period_return").uses_risk_metrics()
        assert ScreenSpec(raw_query="x", sort_by="sharpe").uses_risk_metrics()
        # 回归锚定：回撤阈值本身（而非默认排序键）必须触发偏差披露要求
        assert ScreenSpec(
            raw_query="x", sort_by="period_return", max_max_drawdown=-0.2
        ).uses_risk_metrics()
        assert ScreenSpec(
            raw_query="x", sort_by="period_return", min_sharpe=1.0
        ).uses_risk_metrics()


def test_lookback_return_column_mapping():
    assert lookback_return_column(1) == "return_1y"
    assert lookback_return_column(3) == "return_3y"
    # rank 表无近5年列，回退近3年（调用方须披露）
    assert lookback_return_column(5) == "return_3y"


def test_anchor_fell_back_matches_column_mapping():
    """回退年限的披露判据必须与列映射一致：同列即回退，非同列即未回退。

    若将来 _ANCHOR_COLUMN 增加/变更某年限的列，本断言会先于文案错配而失败。
    """
    for years in (1, 3, 5):
        fell_back = anchor_fell_back(years)
        assert fell_back == (lookback_return_column(years) != f"return_{years}y")
    assert not anchor_fell_back(1)
    assert not anchor_fell_back(3)
    assert anchor_fell_back(5)


def test_bias_disclosure_constant_shared_by_finalize_and_evaluator():
    assert "样本偏差" in BIAS_DISCLOSURE
    assert RISK_SORT_KEYS == frozenset(
        {SortKey.SHARPE, SortKey.MAX_DRAWDOWN, SortKey.VOLATILITY}
    )


def test_sort_key_maps_cover_every_key_exactly_once():
    """SORT_ATTRS / SORT_LABELS 是 sort_by 的唯一定位来源，不得漏键或多余键。

    PERIOD_RETURN 走 rank 表锚点、不在指标行上，故只应出现在 SORT_LABELS。
    """
    assert set(SORT_ATTRS) | {SortKey.PERIOD_RETURN} == set(SortKey)
    assert set(SORT_LABELS) == set(SortKey)


# ---- Task 4：规则兜底解析 + 预筛纯函数（nodes/screener.py） ----

from nodes.screener import (  # noqa: E402
    _SPEC_SYSTEM_PROMPT,
    parse_percent,
    parse_screen_spec_rules,
    preselect_universe,
)


class TestParsePercent:
    def test_percent_string_to_decimal(self):
        assert parse_percent("35.60%") == pytest.approx(0.356)

    def test_bare_number_treated_as_percent(self):
        assert parse_percent(3.5) == pytest.approx(0.035)
        assert parse_percent("2") == pytest.approx(0.02)

    def test_missing_markers_return_none(self):
        assert parse_percent("--") is None
        assert parse_percent("") is None
        assert parse_percent(None) is None
        assert parse_percent("—") is None


def _rank_row(code: str, name: str, return_3y) -> dict:
    return {
        "fund_code": code,
        "fund_name": name,
        "nav_date": "2026-09-25",
        "unit_nav": 1.5,
        "return_3y": return_3y,
        "fee_rate": "0.15%",
    }


class TestParseScreenSpecRules:
    def test_low_drawdown_index_query(self):
        spec = parse_screen_spec_rules("帮我选几只低回撤的宽基指数基金")
        assert spec.fund_types == ["指数型"]
        assert spec.sort_by == "max_drawdown"
        assert spec.sort_order == "desc"
        assert any("低回撤" in a for a in spec.assumptions)

    def test_broad_index_assumption(self):
        spec = parse_screen_spec_rules("帮我选几只低回撤的宽基指数基金")
        assert any("宽基" in a for a in spec.assumptions)

    def test_sharpe_and_vague_aum(self):
        spec = parse_screen_spec_rules("近三年夏普高、规模别太小的主动权益")
        assert set(spec.fund_types) == {"股票型", "混合型"}
        assert spec.lookback_years == 3
        assert spec.sort_by == "sharpe"
        assert spec.min_aum == pytest.approx(10.0)
        assert any("规模" in a for a in spec.assumptions)

    def test_explicit_thresholds(self):
        spec = parse_screen_spec_rules("筛选近3年回撤小于20%、夏普大于1.0、规模大于5亿的债券基金，要前3只")
        assert spec.fund_types == ["债券型"]
        assert spec.max_max_drawdown == pytest.approx(-0.20)
        assert spec.min_sharpe == pytest.approx(1.0)
        assert spec.min_aum == pytest.approx(5.0)
        assert spec.top_n == 3

    def test_unsupported_conditions_disclosed(self):
        spec = parse_screen_spec_rules("筛选不要持仓茅台、要跑赢沪深300的混合基金")
        assert spec.fund_types == ["混合型"]
        assert any("持仓" in g for g in spec.unsupported_requirements)
        assert any("跑赢" in g or "基准" in g for g in spec.unsupported_requirements)

    def test_exclude_type_parsed_into_spec(self):
        """规则兜底须解析排除类型：否则 ScreenerNode 的候选池过滤无从生效。

        ScreenerNode 取数时按 exclude_types 从 fund_types 中扣除；若该字段为空，
        被排除的类型会照常进入候选池——「不要债券型」失效且无任何提示。
        """
        spec = parse_screen_spec_rules("筛选指数基金，不要债券型")
        assert spec.exclude_types == ["债券型"]
        assert not any("排除类型" in g for g in spec.unsupported_requirements)

    def test_exclude_type_list_all_applied(self):
        """一个动词带多个类型：须全部应用，且不误伤动词后要保留的类型。

        「不含 qdii 与 fof 的指数基金」里的指数型是保留项而非排除项——
        类型词必须紧邻动词，否则会错误缩小候选池。
        """
        spec = parse_screen_spec_rules("筛选不含 qdii 与 fof 的指数基金")
        assert spec.exclude_types == ["QDII", "FOF"]
        assert "指数型" in spec.fund_types

    def test_exclude_type_partial_list_still_disclosed(self):
        """列举中部分类型无法映射：已映射的执行，未映射的必须披露。"""
        spec = parse_screen_spec_rules("筛选指数基金，不要债券型和货币型")
        assert spec.exclude_types == ["债券型"]
        assert any("排除类型" in g for g in spec.unsupported_requirements)

    def test_exclude_type_not_taken_from_verb_distant_phrase(self):
        """"不要成立不足3年的指数基金"：排除对象非主类，指数型须保留。"""
        spec = parse_screen_spec_rules("筛选不要成立不足3年的指数基金")
        assert spec.exclude_types == []
        assert spec.fund_types == ["指数型"]

    def test_all_fund_types_excluded_disclosed(self):
        """主类被排除干净 → 可选范围为空，必须披露。

        否则报告只会给出「候选池预筛后无候选基金（条件过严或排行数据缺失）」，
        把「用户只说了要排除什么」误导成「条件太严」。
        """
        spec = parse_screen_spec_rules("筛选不要债券型的基金")
        assert spec.fund_types == ["债券型"]
        assert spec.exclude_types == ["债券型"]
        assert any("排除" in g for g in spec.unsupported_requirements)

    def test_partially_excluded_fund_types_not_disclosed_as_empty(self):
        """仍有主类留存时不得披露"范围为空"（避免误报）。"""
        spec = parse_screen_spec_rules("筛选指数和债券型，不要债券型")
        assert spec.fund_types == ["债券型", "指数型"]
        assert spec.exclude_types == ["债券型"]
        assert not any("可选范围为空" in g for g in spec.unsupported_requirements)

    def test_unmappable_exclude_type_disclosed(self):
        """排除的类型不在排行表主类枚举内：无法执行，须显式披露（不静默忽略）。"""
        spec = parse_screen_spec_rules("筛选指数基金，不要货币型")
        assert spec.exclude_types == []
        assert any("排除类型" in g for g in spec.unsupported_requirements)

    def test_holdings_exclusion_not_reported_as_type_exclusion(self):
        """"排除持仓股票" 走持仓规则，不得误报为类型排除（股票既指持仓也指主类）。"""
        spec = parse_screen_spec_rules("筛选排除掉持仓股票的混合基金")
        assert not any("排除类型" in g for g in spec.unsupported_requirements)
        assert any("持仓" in g for g in spec.unsupported_requirements)

    def test_long_term_assumption(self):
        spec = parse_screen_spec_rules("筛选适合长期持有的债券基金")
        assert spec.fund_types == ["债券型"]
        assert any("长期" in a for a in spec.assumptions)

    def test_return_threshold_sets_lookback_and_min(self):
        spec = parse_screen_spec_rules("筛选近1年收益超过10%的指数基金")
        assert spec.lookback_years == 1
        assert spec.min_period_return == pytest.approx(0.10)

    def test_non_standard_lookback_coerced_with_assumption(self):
        spec = parse_screen_spec_rules("筛选近2年收益超过10%的债券基金")
        assert spec.lookback_years == 3
        assert any("1/3/5" in a for a in spec.assumptions)


class TestPreselectUniverse:
    def _rows(self) -> list[dict]:
        return [
            _rank_row("000001", "甲基金", "30.00%"),
            _rank_row("000002", "乙基金", "50.00%"),
            _rank_row("000003", "丙基金", "10.00%"),
            _rank_row("000004", "丁基金", "--"),
            _rank_row("000005", "戊基金", 20),
        ]

    def test_sorts_desc_and_skips_missing_anchor(self):
        spec = ScreenSpec(raw_query="x", fund_types=["指数型"])
        result = preselect_universe(self._rows(), spec)
        assert [r["fund_code"] for r in result.rows] == ["000002", "000001", "000005", "000003"]
        assert result.anchor_values["000002"] == pytest.approx(0.50)
        assert result.anchor_values["000005"] == pytest.approx(0.20)
        assert result.meta.universe_size == 5
        assert result.meta.preselected_size == 4
        assert result.meta.skipped_no_anchor == 1
        assert result.meta.filtered_by_conditions == 0

    def test_preselect_limit(self):
        rows = [_rank_row(f"{i:06d}", f"基金{i}", f"{i}.00%") for i in range(40)]
        spec = ScreenSpec(raw_query="x")
        result = preselect_universe(rows, spec)
        assert result.meta.preselected_size == 30
        assert result.anchor_values["000039"] == pytest.approx(0.39)

    def test_min_period_return_filters_and_counts(self):
        spec = ScreenSpec(raw_query="x", min_period_return=0.25)
        result = preselect_universe(self._rows(), spec)
        assert [r["fund_code"] for r in result.rows] == ["000002", "000001"]
        assert result.meta.filtered_by_conditions == 2

    def test_dedup_keeps_first(self):
        rows = [*self._rows(), _rank_row("000001", "甲基金重复", "99.00%")]
        result = preselect_universe(rows, ScreenSpec(raw_query="x"))
        assert result.meta.universe_size == 5
        assert result.anchor_values["000001"] == pytest.approx(0.30)

    def test_ascending_when_period_return_sort_asc(self):
        spec = ScreenSpec(raw_query="x", sort_by="period_return", sort_order="asc")
        result = preselect_universe(self._rows(), spec)
        assert [r["fund_code"] for r in result.rows] == ["000003", "000005", "000001", "000002"]


# ---- Task 5：ScreenerNode（LLM 解析 + 候选池构建 + 预筛装配） ----

import json  # noqa: E402

import httpx  # noqa: E402

from domain.task_type import TaskType  # noqa: E402
from llm import LLMError, LLMResponse, Message  # noqa: E402
from nodes import ScreenerNode  # noqa: E402
from tests.conftest import make_tools  # noqa: E402
from tools.collector_client import CollectorClient  # noqa: E402


class _FakeLLM:
    """同步 Fake Provider：返回固定 JSON 或抛 LLMError（记录调用供断言）。"""

    model = "fake-model"

    def __init__(self, response: str | Exception):
        self._response = response
        self.calls: list[list[Message]] = []

    def generate(self, messages, *, structured_output=None):
        self.calls.append(messages)
        if isinstance(self._response, Exception):
            raise self._response
        return LLMResponse(content=self._response, input_tokens=10, output_tokens=5)


def _screener_rows() -> list[dict]:
    return [
        _rank_row("000001", "甲指数", "30.00%"),
        _rank_row("000002", "乙指数", "50.00%"),
        _rank_row("000003", "丙指数", "10.00%"),
        _rank_row("000004", "丁指数", 25),
    ]


def _screen_state(query: str) -> dict:
    return {"user_query": query, "task_type": TaskType.FUND_SCREENING}


class TestSpecPromptSchema:
    """_SPEC_SYSTEM_PROMPT 必须与 ScreenSpec 同步（schema 双写的漂移守卫）。

    当前 LLM 走 JSON Mode，provider 不下发 schema，prompt 描述是唯一的结构
    来源；ScreenSpec 加字段或改默认值而漏改 prompt 时，LLM 会照旧输出旧结构并
    被 model_validate_json 静默拒掉、退回规则兜底。
    """

    def test_every_field_name_appears_in_prompt(self):
        for name in ScreenSpec.model_fields:
            if name == "raw_query":
                continue   # 有意排除：系统回填，见下方 raw_query 专项断言
            assert f'"{name}"' in _SPEC_SYSTEM_PROMPT, f"prompt 缺少字段 {name}"

    def test_raw_query_excluded_from_shape_but_instructed_blank(self):
        """raw_query 由系统回填：不得进结构提示（否则 LLM 会自行填充），但须指示留空。"""
        assert '"raw_query"' not in _SPEC_SYSTEM_PROMPT
        assert "raw_query 留空" in _SPEC_SYSTEM_PROMPT

    def test_prompt_defaults_match_screen_spec(self):
        spec = ScreenSpec()
        defaults = {
            name: getattr(spec, name)
            for name in ScreenSpec.model_fields
            if name != "raw_query"
        }
        for name, value in defaults.items():
            rendered = json.dumps(value, ensure_ascii=False)
            assert f'"{name}": {rendered}' in _SPEC_SYSTEM_PROMPT, (
                f"prompt 中 {name} 的默认值 {rendered} 与 ScreenSpec 不一致"
            )

    def test_prompt_is_valid_json_shape_hint(self):
        """结构提示本身必须是可解析的 JSON 对象（模型照抄这段结构）。"""
        import re as _re

        block = _re.search(r"\{\"fund_types\".*?\}", _SPEC_SYSTEM_PROMPT, _re.S).group(0)
        assert json.loads(block).keys() == {
            n for n in ScreenSpec.model_fields if n != "raw_query"
        }


class TestScreenerNode:
    def test_rules_path_without_llm(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        try:
            out = ScreenerNode(client, llm=None)(_screen_state("筛选近三年收益超过20%的指数基金"))
            spec = out["screen_spec"]
            assert spec.fund_types == ["指数型"]
            assert spec.min_period_return == pytest.approx(0.20)
            assert spec.lookback_years == 3
            assert out["fund_ids"] == ["000002", "000001", "000004"]
            meta = out["screening_meta"]
            assert meta.anchor == "近3年收益降序（M=30）"
            assert meta.filtered_by_conditions == 1
            assert out["screen_rank_rows"]["000002"]["anchor_return"] == pytest.approx(0.50)
            assert out["screen_rank_rows"]["000002"]["fund_name"] == "乙指数"
        finally:
            client.close()

    def test_exclude_type_applied_to_universe_fetch(self):
        """端到端：被排除的主类不得发起排行表请求（否则排除条件形同虚设）。

        ScreenerNode 取数时按 exclude_types 从 fund_types 中扣除；规则兜底若
        不填该字段，被排除的类型会照常进入候选池。
        """
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.params.get("symbol", ""))
            return httpx.Response(200, json=_screener_rows())

        client = CollectorClient(
            base_url="http://collector.test", transport=httpx.MockTransport(handler)
        )
        try:
            out = ScreenerNode(client, llm=None)(_screen_state("筛选指数基金，不要债券型"))
            assert requested == ["指数型"]
            assert out["screen_spec"].exclude_types == ["债券型"]
        finally:
            client.close()

    def test_llm_structured_output_path(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(
            json.dumps(
                {
                    "raw_query": "",
                    "fund_types": ["债券型"],
                    "top_n": 3,
                    "sort_by": "period_return",
                    "sort_order": "asc",
                }
            )
        )
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("帮我选几只债券基金"))
            spec = out["screen_spec"]
            assert spec.top_n == 3
            assert spec.raw_query == "帮我选几只债券基金"  # 系统回填
            assert out["fund_ids"] == ["000003", "000004", "000001", "000002"]  # 升序
            assert out["llm_interactions"][0].ok is True
            assert out["token_usage"].llm_calls == 1
        finally:
            client.close()

    def test_llm_failure_falls_back_to_rules(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(LLMError("boom"))
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("筛选低回撤的指数基金"))
            assert out["screen_spec"].sort_by == "max_drawdown"  # 规则兜底产物
            assert out["fund_ids"] == ["000002", "000001", "000004", "000003"]  # 浅回撤=锚点收益降序
            assert any("兜底" in issue for issue in out["data_quality_issues"])
            assert out["llm_interactions"][0].ok is False
        finally:
            client.close()

    def test_rank_fetch_failure_degrades(self):
        tools, store, client = make_tools(status=500)
        try:
            out = ScreenerNode(client, llm=None)(_screen_state("筛选低回撤的指数基金"))
            assert out["fund_ids"] == []
            assert out["screening_meta"].preselected_size == 0
            assert any("排行表" in issue for issue in out["data_quality_issues"])
        finally:
            client.close()

    def test_anchor_text_discloses_5y_fallback(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        try:
            out = ScreenerNode(client, llm=None)(_screen_state("筛选近5年收益超过10%的指数基金"))
            anchor = out["screening_meta"].anchor
            assert "回退" in anchor
            # 文案中的年限与回退列名均取自 spec / 列映射，不得手写漂移
            assert "5 年窗口无排行列，回退近3年" in anchor
        finally:
            client.close()

    def test_anchor_text_no_fallback_disclosure_for_3y(self):
        """未回退的窗口不得出现回退文案（披露与实际口径必须一致）。"""
        tools, store, client = make_tools(rank_rows=_screener_rows())
        try:
            out = ScreenerNode(client, llm=None)(_screen_state("筛选近3年收益超过10%的指数基金"))
            assert out["screening_meta"].anchor == "近3年收益降序（M=30）"
        finally:
            client.close()

    def test_unmapped_llm_type_moves_to_unsupported(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(json.dumps({"raw_query": "", "fund_types": ["量化对冲"], "top_n": 5}))
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("帮我选几只量化对冲基金"))
            spec = out["screen_spec"]
            assert spec.fund_types == []
            assert any("量化对冲" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_exclude_type_outside_universe_is_disclosed(self):
        """排除项与主类无交集：取数结果正确（候选池本就不含该类），但须披露未生效。

        _condition_lines 只渲染与主类有交集的排除项（避免"生效"的误导），故
        披露责任落在本处——否则用户无从得知自己说的排除条件被如何处理。
        """
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(
            json.dumps(
                {
                    "raw_query": "",
                    "fund_types": ["指数型"],
                    "exclude_types": ["债券型"],
                    "top_n": 5,
                }
            )
        )
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("筛选指数基金，不要债券型"))
            spec = out["screen_spec"]
            assert spec.fund_types == ["指数型"]
            assert spec.exclude_types == ["债券型"]
            assert any("排除类型" in g and "债券型" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_exclude_type_disclosed_when_all_fund_types_unmapped(self):
        """主类全部映射失败 → 退化为「全部」，排除条件无法执行，必须披露。

        原守卫检查的是归一化前的 spec.fund_types（原始值非空），故此情形
        静默通过：取数变成「全部」，被排除的类型照样进入候选池。
        """
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(
            json.dumps(
                {
                    "raw_query": "",
                    "fund_types": ["量化对冲"],
                    "exclude_types": ["债券型"],
                    "top_n": 5,
                }
            )
        )
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("帮我选量化对冲，不要债券型"))
            spec = out["screen_spec"]
            assert spec.fund_types == []
            assert spec.exclude_types == ["债券型"]
            assert any("exclude_types" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_all_fund_types_excluded_disclosed(self):
        """LLM 把同一类型同时放进 fund_types 与 exclude_types：可选范围为空，须披露。"""
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(
            json.dumps(
                {
                    "raw_query": "",
                    "fund_types": ["债券型"],
                    "exclude_types": ["债券型"],
                    "top_n": 5,
                }
            )
        )
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("筛选不要债券型的基金"))
            spec = out["screen_spec"]
            assert spec.fund_types == ["债券型"]
            assert any("排除" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_effective_exclude_type_not_disclosed_as_ineffective(self):
        """排除项与主类有交集（真的生效）：不得产生"未生效"披露，否则报告噪音化。"""
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(
            json.dumps(
                {
                    "raw_query": "",
                    "fund_types": ["指数型", "债券型"],
                    "exclude_types": ["债券型"],
                    "top_n": 5,
                }
            )
        )
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("筛选指数和债券型，不要债券型"))
            spec = out["screen_spec"]
            assert spec.exclude_types == ["债券型"]
            assert not any("不在筛选主类内" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_unmapped_llm_exclude_type_moves_to_unsupported(self):
        # exclude_types 必须与 fund_types 同一套归一化：映射不上 → unsupported，不静默失效
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(json.dumps({"raw_query": "", "fund_types": ["混合型"], "exclude_types": ["量化对冲"], "top_n": 5}))
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("帮我选几只量化对冲的混合基金"))
            spec = out["screen_spec"]
            assert spec.exclude_types == []
            assert any("量化对冲" in g for g in spec.unsupported_requirements)
        finally:
            client.close()

    def test_mapped_llm_exclude_type_normalized(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        llm = _FakeLLM(json.dumps({"raw_query": "", "fund_types": ["股票型", "混合型", "债券型"], "exclude_types": ["债券"], "top_n": 5}))
        try:
            out = ScreenerNode(client, llm=llm)(_screen_state("帮我选几只基金"))
            spec = out["screen_spec"]
            assert spec.exclude_types == ["债券型"]  # 「债券」→ 债券型，取数层面生效
        finally:
            client.close()


# ---- Task 6：Collector 筛选降级分支（仅 info + performance） ----

from nodes import CollectorNode  # noqa: E402
from domain.plan import ResearchPlan  # noqa: E402
from tests.conftest import FUND_CODE  # noqa: E402


class TestCollectorScreening:
    def test_screening_collects_info_and_nav_only(self):
        tools, store, client = make_tools(rank_rows=_screener_rows())
        try:
            out = CollectorNode(tools)(
                {"task_type": TaskType.FUND_SCREENING, "fund_ids": ["000001", "000002"]}
            )
            assert out["fund_ids"] == ["000001", "000002"]
            assert len(out["funds_summary"]) == 2
            # 轻量采集：每基金恰好 2 次 Tool 调用（info + performance），无持仓/费率/评级/基准
            assert len(out["tool_calls"]) == 4
            sources = {
                e.source if not isinstance(e, dict) else e["source"] for e in out["evidence"]
            }
            assert not any(
                "/holdings" in s or "/fees" in s or "/rating" in s or "/index/" in s
                for s in sources
            )
        finally:
            client.close()

    def test_screening_empty_preselected_degrades(self):
        tools, store, client = make_tools()
        try:
            out = CollectorNode(tools)({"task_type": TaskType.FUND_SCREENING, "fund_ids": []})
            assert out["fund_ids"] == []
            assert any("预选集为空" in issue for issue in out["data_quality_issues"])
        finally:
            client.close()

    def test_research_path_still_full_suite(self):
        tools, store, client = make_tools()
        try:
            plan = ResearchPlan(fund_ids=[FUND_CODE])
            out = CollectorNode(tools)({"research_plan": plan, "fund_ids": [FUND_CODE]})
            # 全量套件：info/performance/holdings/industry/allocation/fees/achievement/rating（+基准）
            assert len(out["tool_calls"]) >= 8
        finally:
            client.close()


# ---- Task 7：Analyzer 筛选分支（per-fund trailing 窗口，无跨基金对齐） ----

from datetime import date  # noqa: E402

from nodes import AnalyzerNode  # noqa: E402
from store import FundStore  # noqa: E402
from domain.fund import NAVPoint  # noqa: E402
from domain.evidence import EvidenceType  # noqa: E402


def _store_two_funds() -> FundStore:
    """基金甲历史长、基金乙历史短：若发生跨基金对齐，甲的区间会被拉齐到乙。"""
    store = FundStore()
    store.put_nav_series(
        "000001",
        [
            NAVPoint(nav_date=date(2024, 1, 2), unit_nav=1.0),
            NAVPoint(nav_date=date(2025, 6, 30), unit_nav=1.4),
            NAVPoint(nav_date=date(2026, 9, 8), unit_nav=2.0),
        ],
    )
    store.put_nav_series(
        "000002",
        [
            NAVPoint(nav_date=date(2026, 6, 1), unit_nav=1.0),
            NAVPoint(nav_date=date(2026, 9, 8), unit_nav=1.1),
        ],
    )
    return store


def _analyzer_state(lookback: int = 3) -> dict:
    return {
        "task_type": TaskType.FUND_SCREENING,
        "fund_ids": ["000001", "000002"],
        "screen_spec": ScreenSpec(raw_query="x", lookback_years=lookback).model_dump(),
    }


class TestAnalyzerScreening:
    def test_per_fund_window_no_cross_fund_alignment(self):
        out = AnalyzerNode(_store_two_funds())(_analyzer_state())
        rows = out["analysis"].peer_comparison.rows
        assert [r.fund_id for r in rows] == ["000001", "000002"]
        # 甲按自身历史起点计算（2024-01-02），未被对齐到乙的起点（2026-06-01）
        assert rows[0].period_start == date(2024, 1, 2)
        assert rows[1].period_start == date(2026, 6, 1)
        # 筛选路径不计算持仓集中度
        assert out["analysis"].holdings_metrics == []

    def test_window_trailing_lookback_filters_old_points(self):
        store = FundStore()
        store.put_nav_series(
            "000001",
            [
                NAVPoint(nav_date=date(2016, 4, 22), unit_nav=1.0),
                NAVPoint(nav_date=date(2026, 6, 1), unit_nav=1.5),
                NAVPoint(nav_date=date(2026, 9, 8), unit_nav=1.8),
            ],
        )
        out = AnalyzerNode(store)(_analyzer_state(lookback=3))
        row = out["analysis"].peer_comparison.rows[0]
        # lookback=3：2016 年的点被窗口过滤（窗口起点 ≈ 2023-09）
        assert row.period_start == date(2026, 6, 1)

    def test_calculation_evidence_per_fund_appended(self):
        evidence_before = 0
        out = AnalyzerNode(_store_two_funds())(_analyzer_state())
        calc = [e for e in out["evidence"] if (e.evidence_type if not isinstance(e, dict) else e["evidence_type"]) == EvidenceType.CALCULATION]
        assert len(calc) == 2 + evidence_before
        values = [e.value if not isinstance(e, dict) else e["value"] for e in calc]
        assert {v["fund_id"] for v in values} == {"000001", "000002"}

    def test_insufficient_nav_recorded_as_issue(self):
        store = FundStore()
        store.put_nav_series("000003", [NAVPoint(nav_date=date(2026, 9, 8), unit_nav=1.0)])
        out = AnalyzerNode(store)(
            {
                "task_type": TaskType.FUND_SCREENING,
                "fund_ids": ["000003"],
                "screen_spec": ScreenSpec(raw_query="x", lookback_years=3).model_dump(),
            }
        )
        assert any("000003" in issue and "净值数据不足" in issue for issue in out["data_quality_issues"])


# ---- Task 8：screen_finalize（硬过滤 + 排序 + 披露装配） ----

from datetime import datetime, timedelta  # noqa: E402

from nodes import ScreenFinalizeNode  # noqa: E402
from domain.analysis import (  # noqa: E402
    AnalysisResult,
    PeerComparison,
    PeerMetricsRow,
    PerformanceAnalysis,
    RiskAnalysis,
)
from domain.fund import Fund  # noqa: E402
from domain.fund import FundSummary  # noqa: E402
from domain.screening import BIAS_DISCLOSURE, ScreeningMeta  # noqa: E402


def _prow(
    fund_id: str,
    *,
    sharpe: float | None = 1.0,
    mdd: float | None = -0.15,
    vol: float | None = 0.20,
    annualized: float | None = 0.10,
    start: date = date(2023, 9, 8),
    end: date = date(2026, 9, 8),
) -> PeerMetricsRow:
    return PeerMetricsRow(
        fund_id=fund_id,
        period_start=start,
        period_end=end,
        nav_point_count=500,
        cumulative_return=0.30,
        annualized_return=annualized,
        annual_volatility=vol,
        max_drawdown=mdd,
        sharpe=sharpe,
    )


def _summary(fund_id: str, aum: float | None = 20.0) -> FundSummary:
    return FundSummary(id=fund_id, name=f"基金{fund_id}", aum=aum, as_of=datetime(2026, 9, 26))


def _finalize_state(
    spec: ScreenSpec,
    rows: list[PeerMetricsRow],
    *,
    rank_rows: dict[str, dict] | None = None,
    meta: ScreeningMeta | None = None,
    store: FundStore | None = None,
) -> dict:
    store = store if store is not None else FundStore()
    # 默认全历史 ≥ 3 年（历史充分性按 Store 全历史跨度判定）；个别用例可覆盖为短历史
    for r in rows:
        if store.get_nav_series(r.fund_id):
            continue
        store.put_nav_series(
            r.fund_id,
            [
                NAVPoint(nav_date=date(2020, 1, 2), unit_nav=1.0),
                NAVPoint(nav_date=date(2023, 3, 8), unit_nav=1.5),
                NAVPoint(nav_date=date(2026, 9, 8), unit_nav=2.0),
            ],
        )
    rank_rows = rank_rows if rank_rows is not None else {
        r.fund_id: {"fund_name": f"基金{r.fund_id}", "anchor_column": "return_3y", "anchor_return": 0.3}
        for r in rows
    }
    meta = meta or ScreeningMeta(universe_size=1000, preselected_size=len(rows), anchor="近3年收益降序（M=30）", anchor_column="return_3y")
    analysis = None
    if rows:
        analysis = AnalysisResult(
            performance=PerformanceAnalysis(fund_id=rows[0].fund_id),
            risk=RiskAnalysis(fund_id=rows[0].fund_id),
            peer_comparison=PeerComparison(base_fund_id=rows[0].fund_id, rows=rows),
        )
    state = {
        "task_type": TaskType.FUND_SCREENING,
        "screen_spec": spec.model_dump(),
        "screening_meta": meta.model_dump(),
        "screen_rank_rows": rank_rows,
        "funds_summary": [s.model_dump() for s in [_summary(r.fund_id) for r in rows]],
        "data_quality_issues": [],
    }
    if analysis is not None:
        state["analysis"] = analysis.model_dump()
    return state


class TestScreenFinalize:
    def _run_finalize(self, spec, rows, *, store=None, **kw):
        """单一 store 流：helper 向同一 store 写默认全历史，节点与检查共用它。"""
        store = store if store is not None else FundStore()
        state = _finalize_state(spec, rows, store=store, **kw)
        return ScreenFinalizeNode(store)(state)

    def test_hard_filter_sort_and_bias_disclosure(self):
        spec = ScreenSpec(raw_query="x", min_sharpe=0.5, sort_by="sharpe", sort_order="desc", unsupported_requirements=["「跑赢沪深300」暂不支持"])
        rows = [_prow("000002", sharpe=1.4), _prow("000001", sharpe=0.9)]
        out = self._run_finalize(spec, rows)
        result = out["screening_result"]
        assert [e.fund_id for e in result.entries] == ["000002", "000001"]
        assert result.entries[0].sharpe == pytest.approx(1.4)
        assert "夏普" in result.entries[0].rationale
        assert BIAS_DISCLOSURE in result.data_gaps
        assert "「跑赢沪深300」暂不支持" in result.data_gaps
        assert result.empty_reason is None

    def test_insufficient_history_excluded_and_disclosed(self):
        spec = ScreenSpec(raw_query="x", lookback_years=3)
        rows = [_prow("000001"), _prow("000002")]
        store = FundStore()
        state = _finalize_state(spec, rows, store=store)
        # 000002 全历史只有 ~99 天（< 3 年）→ 剔除并披露
        store.put_nav_series(
            "000002",
            [
                NAVPoint(nav_date=date(2026, 6, 1), unit_nav=1.0),
                NAVPoint(nav_date=date(2026, 9, 8), unit_nav=1.1),
            ],
        )
        out = ScreenFinalizeNode(store)(state)
        result = out["screening_result"]
        assert [e.fund_id for e in result.entries] == ["000001"]
        assert any("历史不足" in gap and "000002" in gap for gap in result.data_gaps)

    def test_drawdown_filter(self):
        spec = ScreenSpec(raw_query="x", max_max_drawdown=-0.20)
        rows = [_prow("000001", mdd=-0.10), _prow("000002", mdd=-0.30)]
        out = self._run_finalize(spec, rows)
        assert [e.fund_id for e in out["screening_result"].entries] == ["000001"]

    def test_aum_filter_and_missing_aum_excluded(self):
        spec = ScreenSpec(raw_query="x", min_aum=10.0)
        rows = [_prow("000001"), _prow("000002")]
        store = FundStore()
        state = _finalize_state(spec, rows, store=store)
        state["funds_summary"] = [
            _summary("000001", aum=44.0).model_dump(),
            _summary("000002", aum=None).model_dump(),
        ]
        result = ScreenFinalizeNode(store)(state)["screening_result"]
        assert [e.fund_id for e in result.entries] == ["000001"]
        assert any("规模缺失" in gap for gap in result.data_gaps)

    def test_inception_years_filter(self):
        spec = ScreenSpec(raw_query="x", min_inception_years=3.0)
        store = FundStore()
        store.put_fund(Fund(id="000001", name="老基金", source="test", as_of=datetime(2026, 9, 26), inception_date=date(2016, 4, 22)))
        store.put_fund(Fund(id="000002", name="新基金", source="test", as_of=datetime(2026, 9, 26), inception_date=date(2025, 9, 1)))
        rows = [_prow("000001"), _prow("000002")]
        state = _finalize_state(spec, rows, store=store)
        out = ScreenFinalizeNode(store)(state)
        assert [e.fund_id for e in out["screening_result"].entries] == ["000001"]

    def test_sort_by_period_return_uses_rank_anchor(self):
        spec = ScreenSpec(raw_query="x", sort_by="period_return", sort_order="asc")
        rows = [_prow("000001"), _prow("000002")]
        rank_rows = {
            "000001": {"fund_name": "基金000001", "anchor_column": "return_3y", "anchor_return": 0.5},
            "000002": {"fund_name": "基金000002", "anchor_column": "return_3y", "anchor_return": 0.2},
        }
        out = self._run_finalize(spec, rows, rank_rows=rank_rows)
        entries = out["screening_result"].entries
        assert [e.fund_id for e in entries] == ["000002", "000001"]
        assert entries[0].period_return == pytest.approx(0.2)

    def test_top_n_slices(self):
        spec = ScreenSpec(raw_query="x", top_n=1)
        rows = [_prow("000001", sharpe=0.5), _prow("000002", sharpe=1.5)]
        out = self._run_finalize(spec, rows)
        assert [e.fund_id for e in out["screening_result"].entries] == ["000002"]

    def test_missing_sort_key_excluded(self):
        spec = ScreenSpec(raw_query="x", sort_by="sharpe")
        rows = [_prow("000001", sharpe=None), _prow("000002", sharpe=1.0)]
        out = self._run_finalize(spec, rows)
        result = out["screening_result"]
        assert [e.fund_id for e in result.entries] == ["000002"]
        assert any("排序键缺失" in gap and "000001" in gap for gap in result.data_gaps)

    def test_zero_survivors_reports_hardest_condition(self):
        spec = ScreenSpec(raw_query="x", min_sharpe=5.0, max_max_drawdown=-0.01)
        rows = [_prow("000001", sharpe=1.0, mdd=-0.5), _prow("000002", sharpe=0.5, mdd=-0.6)]
        out = self._run_finalize(spec, rows)
        result = out["screening_result"]
        assert result.entries == []
        assert result.empty_reason and "无可满足条件的基金" in result.empty_reason
        assert any("夏普" in gap for gap in result.data_gaps)

    def test_zero_preselected_reports_prefilter_cause(self):
        # 候选池级条件把预选集滤空：与「数据源失败」区分表述
        spec = ScreenSpec(raw_query="x", min_period_return=0.99)
        meta = ScreeningMeta(universe_size=4, preselected_size=0, anchor="近3年收益降序（M=30）", anchor_column="return_3y", filtered_by_conditions=4)
        out = self._run_finalize(spec, [], meta=meta)
        result = out["screening_result"]
        assert result.entries == []
        assert "预筛" in result.empty_reason
        assert any("4 只未满足候选池级条件" in gap for gap in result.data_gaps)

    def test_no_risk_metrics_no_bias_disclosure(self):
        spec = ScreenSpec(raw_query="x", sort_by="period_return", sort_order="desc")
        rows = [_prow("000001")]
        out = self._run_finalize(spec, rows)
        assert BIAS_DISCLOSURE not in out["screening_result"].data_gaps

    def test_condition_lines_only_render_effective_excludes(self):
        # 排除项与候选池主类无交集时未生效，不得渲染「排除类型」误导报告
        spec = ScreenSpec(raw_query="x", fund_types=["混合型"], exclude_types=["债券型"])
        rows = [_prow("000001")]
        out = self._run_finalize(spec, rows)
        conditions = "\n".join(out["screening_result"].conditions)
        assert "排除类型" not in conditions

    def test_condition_lines_render_effective_excludes(self):
        spec = ScreenSpec(raw_query="x", fund_types=["股票型", "债券型"], exclude_types=["债券型"])
        rows = [_prow("000001")]
        out = self._run_finalize(spec, rows)
        conditions = "\n".join(out["screening_result"].conditions)
        assert "排除类型：债券型" in conditions

    def test_universe_skip_disclosure_from_meta(self):
        spec = ScreenSpec(raw_query="x")
        rows = [_prow("000001")]
        meta = ScreeningMeta(universe_size=500, preselected_size=1, anchor="近3年收益降序（M=30）", anchor_column="return_3y", skipped_no_anchor=7)
        out = self._run_finalize(spec, rows, meta=meta)
        assert any("未参与预筛" in gap and "7" in gap for gap in out["screening_result"].data_gaps)


# ---- Task 9：Evaluator 的 screening 检查分支 ----

from nodes import EvaluatorNode  # noqa: E402
from domain.evaluation import EvaluationStatus  # noqa: E402


def _entry(fund_id: str, *, sharpe: float | None = 1.4) -> ShortlistEntry:
    return ShortlistEntry(
        fund_id=fund_id,
        annualized_return=0.2,
        max_drawdown=-0.1,
        sharpe=sharpe,
        rationale="满足全部筛选条件",
    )


def _result(
    entries: list[ShortlistEntry],
    spec: ScreenSpec,
    *,
    data_gaps: list[str] | None = None,
    top_n: int | None = None,
    universe_size: int = 100,
) -> ScreenResult:
    return ScreenResult(
        universe_size=universe_size,
        preselected_size=30,
        anchor="近3年收益降序（M=30）",
        sort_by=spec.sort_by,
        sort_order=spec.sort_order,
        top_n=top_n if top_n is not None else spec.top_n,
        entries=entries,
        data_gaps=data_gaps if data_gaps is not None else [],
    )


def _eval_state(result: ScreenResult, spec: ScreenSpec) -> dict:
    return {
        "task_type": TaskType.FUND_SCREENING,
        "user_query": "筛选基金",
        "screen_spec": spec.model_dump(),
        "screening_result": result.model_dump(),
    }


class TestEvaluatorScreening:
    def test_pass_when_disclosures_complete(self):
        spec = ScreenSpec(raw_query="x", min_sharpe=1.0, unsupported_requirements=["「跑赢沪深300」暂不支持"])
        result = _result(
            [_entry("000001", sharpe=1.4)],
            spec,
            data_gaps=["「跑赢沪深300」暂不支持", BIAS_DISCLOSURE],
        )
        out = EvaluatorNode()(_eval_state(result, spec))
        assert out["evaluation"].status == EvaluationStatus.PASS

    def test_fail_when_unsupported_not_disclosed(self):
        spec = ScreenSpec(raw_query="x", unsupported_requirements=["「跑赢沪深300」暂不支持"])
        result = _result([_entry("000001")], spec, data_gaps=[])
        out = EvaluatorNode()(_eval_state(result, spec))
        evaluation = out["evaluation"]
        assert evaluation.status == EvaluationStatus.FAIL
        assert any("「跑赢沪深300」暂不支持" in item for item in evaluation.missing_items)

    def test_fail_when_bias_disclosure_missing(self):
        spec = ScreenSpec(raw_query="x", min_sharpe=1.0)
        result = _result([_entry("000001")], spec, data_gaps=[])
        out = EvaluatorNode()(_eval_state(result, spec))
        evaluation = out["evaluation"]
        assert evaluation.status == EvaluationStatus.FAIL
        assert any("样本偏差" in item for item in evaluation.missing_items)

    def test_pass_without_risk_metrics_needs_no_bias_disclosure(self):
        spec = ScreenSpec(raw_query="x", sort_by="period_return")
        result = _result([_entry("000001")], spec, data_gaps=[])
        out = EvaluatorNode()(_eval_state(result, spec))
        assert out["evaluation"].status == EvaluationStatus.PASS

    def test_fail_when_entry_metrics_missing(self):
        spec = ScreenSpec(raw_query="x")
        result = _result([_entry("000001", sharpe=None)], spec, data_gaps=[])
        out = EvaluatorNode()(_eval_state(result, spec))
        assert out["evaluation"].status == EvaluationStatus.FAIL

    def test_fail_when_row_count_exceeds_top_n(self):
        spec = ScreenSpec(raw_query="x")
        result = _result([_entry("000001"), _entry("000002")], spec, top_n=1)
        out = EvaluatorNode()(_eval_state(result, spec))
        assert out["evaluation"].status == EvaluationStatus.FAIL

    def test_fail_when_ordering_mismatches_spec(self):
        spec = ScreenSpec(raw_query="x", sort_by="sharpe", sort_order="desc")
        result = _result([_entry("000001", sharpe=0.9), _entry("000002", sharpe=1.4)], spec)
        out = EvaluatorNode()(_eval_state(result, spec))
        evaluation = out["evaluation"]
        assert evaluation.status == EvaluationStatus.FAIL
        assert any("排序" in item for item in evaluation.question_alignment_issues)

    def test_fail_when_screening_result_missing(self):
        spec = ScreenSpec(raw_query="x")
        out = EvaluatorNode()(
            {"task_type": TaskType.FUND_SCREENING, "screen_spec": spec.model_dump()}
        )
        assert out["evaluation"].status == EvaluationStatus.FAIL


# ---- Task 11：报告渲染（短名单一等公民）+ Synthesizer screening 分支 ----

from domain.report import Report, ReportMetadata, render_markdown  # noqa: E402
from nodes import SynthesizerNode  # noqa: E402
from domain.plan import ResearchPlan as _RP  # noqa: E402


def _screening_report() -> Report:
    spec = ScreenSpec(raw_query="x", fund_types=["指数型"], min_sharpe=1.0)
    result = _result(
        [_entry("000001")],
        spec,
        data_gaps=["「跑赢沪深300」暂不支持", BIAS_DISCLOSURE],
        top_n=5,
    )
    result.conditions = ["类型：指数型", "夏普 ≥ 1"]
    return Report(
        title="FundForge 基金筛选报告（Top 5）",
        generated_at=datetime(2026, 9, 26),
        request_id="t",
        executive_summary="筛选候选池 100 只，预选集 30 只。",
        fund_overview=[],
        screening_result=result,
        metadata=ReportMetadata(task_type="fund_screening"),
    )


class TestScreeningReportRendering:
    def test_renders_conditions_and_shortlist(self):
        md = render_markdown(_screening_report())
        assert "## 筛选条件（系统理解）" in md
        assert "类型：指数型" in md
        assert "## 推荐短名单" in md
        assert "满足全部筛选条件" in md
        assert "## 投资论点" not in md

    def test_empty_result_renders_reason(self):
        report = _screening_report()
        report.screening_result.entries = []
        report.screening_result.empty_reason = "无可满足条件的基金（剔除最多的条件：夏普低于 5，30 只）"
        md = render_markdown(report)
        assert "## 筛选结果" in md
        assert "无可满足条件的基金" in md

    def test_research_report_has_no_screening_sections(self):
        report = Report(
            title="t", generated_at=datetime(2026, 9, 26), request_id="t", executive_summary="s"
        )
        assert "## 筛选条件" not in render_markdown(report)


class TestSynthesizerScreening:
    def test_builds_screening_report_from_state(self):
        spec = ScreenSpec(
            raw_query="帮我选基金",
            fund_types=["指数型"],
            min_sharpe=1.0,
            assumptions=["「低回撤」按回撤升序"],
        )
        result = _result([_entry("000001")], spec, data_gaps=[BIAS_DISCLOSURE])
        state = {
            "request_id": "t10",
            "user_query": "帮我选基金",
            "task_type": TaskType.FUND_SCREENING,
            "screen_spec": spec.model_dump(),
            "screening_result": result.model_dump(),
            "research_plan": _RP(task_type=TaskType.FUND_SCREENING).model_dump(),
            "evaluation": {"status": "pass", "claim_coverage_ratio": 1.0, "overall_score": 1.0},
        }
        report = SynthesizerNode()(state)["report"]
        assert report.metadata.task_type == "fund_screening"
        assert report.metadata.thesis_generated is False
        assert report.fund_overview == []
        assert report.screening_result is not None
        assert report.investment_thesis is None
        assert BIAS_DISCLOSURE in report.data_gaps_and_limitations
        assert any(g.startswith("假设：") for g in report.data_gaps_and_limitations)
        assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)
        md = render_markdown(report)
        assert "## 筛选条件（系统理解）" in md
        assert "## 推荐短名单" in md


class TestScreenResultModels:
    def test_meta_defaults(self):
        meta = ScreeningMeta()
        assert meta.universe_size == 0
        assert meta.skipped_no_anchor == 0

    def test_result_holds_entries_and_gaps(self):
        entry = ShortlistEntry(fund_id="001594", sharpe=1.2, rationale="满足全部条件")
        result = ScreenResult(
            universe_size=100,
            preselected_size=30,
            anchor="近3年收益降序（M=30）",
            sort_by="sharpe",
            sort_order="desc",
            top_n=5,
            entries=[entry],
            data_gaps=["「不要持仓茅台」：暂无持仓剔除能力"],
        )
        assert result.entries[0].fund_id == "001594"
        assert result.empty_reason is None

    def test_result_zero_case(self):
        result = ScreenResult(
            universe_size=10,
            preselected_size=10,
            anchor="近3年收益降序（M=30）",
            sort_by="sharpe",
            sort_order="desc",
            top_n=5,
            empty_reason="无可满足条件的基金：夏普 ≥ 1.0 为剔除最多的条件",
        )
        assert result.entries == []
        assert result.empty_reason
