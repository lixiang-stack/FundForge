"""意图分类规则引擎测试（nodes/intent.py）+ Planner 的 screening 分支。"""

import pytest

from domain.task_type import ClassificationRuleHit, TaskType
from nodes.intent import classify, extract_fund_codes
from nodes.planner import PlannerNode


class TestExtractFundCodes:
    def test_dedup_preserving_order(self):
        assert extract_fund_codes("对比 000001 和 519770，重点看 000001") == ["000001", "519770"]

    def test_ignores_non_6_digit(self):
        assert extract_fund_codes("基金 5197701 或 12345") == []

    def test_codes_adjacent_to_chinese_characters(self):
        # 回归：\b 在汉字与数字相邻处不成立，贴着中文的代码曾全部漏提
        for query, expected in (
            ("对比004237 000979两只基金", ["004237", "000979"]),
            ("对比015453、004237、004814这几只基金", ["015453", "004237", "004814"]),
            ("分析004237这只基金", ["004237"]),
        ):
            assert extract_fund_codes(query) == expected, query


class TestClassify:
    def test_r1_dual_intent_with_subject_is_research(self):
        # 核心 Case：分析 + 对比 + 强主题词 → 带 peer 的 research
        result = classify("分析基金 519770 是否适合长期持有，并与 000001、005827 比较")
        assert result.task_type == TaskType.FUND_RESEARCH
        assert result.rule_hit == ClassificationRuleHit.R1_DUAL_INTENT_SUBJECT
        assert result.confidence == pytest.approx(0.8)
        assert result.fund_ids == ["519770", "000001", "005827"]

    def test_r2_analysis_only(self):
        result = classify("分析基金 519770")
        assert result.task_type == TaskType.FUND_RESEARCH
        assert result.rule_hit == ClassificationRuleHit.R2_ANALYSIS_INTENT
        assert result.confidence == pytest.approx(0.9)

    def test_r3_comparison_only(self):
        result = classify("000001 和 519770 哪个好")
        assert result.task_type == TaskType.FUND_COMPARISON
        assert result.rule_hit == ClassificationRuleHit.R3_COMPARISON_INTENT
        assert result.confidence == pytest.approx(0.9)

    def test_r4_fallback_multi_code_weak_analysis(self):
        # 对比词 + 分析词但无强主题词 + ≥2 只代码 → 兜底 comparison
        result = classify("000001 和 519770 表现相比如何，都适合持有吗")
        assert result.task_type == TaskType.FUND_COMPARISON
        assert result.rule_hit == ClassificationRuleHit.R4_MULTI_CODE_COMPARISON
        assert result.confidence == pytest.approx(0.6)

    def test_r4_suitability_comparison_is_comparison(self):
        # 「哪个更适合长期持有」：分析词（适合/持有）+ 新对比词「哪个更」，无强主题词 → R4 对比
        result = classify("015453 和 519770 哪个更适合长期持有")
        assert result.task_type == TaskType.FUND_COMPARISON
        assert result.rule_hit == ClassificationRuleHit.R4_MULTI_CODE_COMPARISON
        assert result.confidence == pytest.approx(0.6)
        assert result.fund_ids == ["015453", "519770"]

    def test_r5_no_intent_fallback(self):
        result = classify("519770 这只基金")
        assert result.task_type == TaskType.FUND_RESEARCH
        assert result.rule_hit == ClassificationRuleHit.R5_FALLBACK
        assert result.confidence == pytest.approx(0.3)


class TestClassifyScreening:
    def test_r0_screening_keyword_without_codes(self):
        result = classify("帮我筛选几只低回撤的债券基金")
        assert result.task_type == TaskType.FUND_SCREENING
        assert result.rule_hit == ClassificationRuleHit.R0_SCREENING_INTENT
        assert result.confidence == pytest.approx(0.9)
        assert result.fund_ids == []

    def test_r0_various_screening_phrasings(self):
        for query in (
            "推荐几只指数基金",
            "帮我选几只规模大的混合基金",
            "筛选近三年收益最高的股票型基金",
            "帮我挑几只适合定投的基金",
        ):
            result = classify(query)
            assert result.task_type == TaskType.FUND_SCREENING, query

    def test_codes_present_falls_back_to_existing_rules(self):
        # 含 6 位代码 → 具体基金分析，不做 screening（避免混合意图误路由）
        result = classify("519770 适合长期持有吗，再帮我推荐几只类似的")
        assert result.task_type == TaskType.FUND_RESEARCH

    def test_comparison_with_codes_beats_screening(self):
        result = classify("对比 000001 和 519770，再推荐几只类似的")
        assert result.task_type == TaskType.FUND_COMPARISON
        assert result.rule_hit == ClassificationRuleHit.R3_COMPARISON_INTENT


class TestPlannerScreening:
    def test_screening_plan_suppresses_code_note(self):
        # 筛选任务无代码是常态（候选池来自排行表），不得误报「无法规划数据采集」
        out = PlannerNode()(
            {"user_query": "筛选低回撤的指数基金", "task_type": TaskType.FUND_SCREENING}
        )
        plan = out["research_plan"]
        assert plan.task_type == TaskType.FUND_SCREENING
        assert plan.fund_ids == []
        assert not any("未发现" in note for note in plan.notes)
