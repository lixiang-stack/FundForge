"""意图分类规则引擎测试（nodes/intent.py）。"""

import pytest

from domain.task_type import ClassificationRuleHit, TaskType
from nodes.intent import classify, extract_fund_codes


class TestExtractFundCodes:
    def test_dedup_preserving_order(self):
        assert extract_fund_codes("对比 000001 和 519770，重点看 000001") == ["000001", "519770"]

    def test_ignores_non_6_digit(self):
        assert extract_fund_codes("基金 5197701 或 12345") == []


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
