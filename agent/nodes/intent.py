"""意图分类规则引擎（Router / Planner 共用，全确定性）。

规则按序命中（首个命中生效），命中记录与置信度随分类结果输出，
供 Evaluator 对齐检查与后续评测集使用：

R1 dual_intent        对比词 + 分析词 + 强主题词（分析/研究/评估）
                      → RESEARCH（带 peer 的主体研究，V1 核心 Case），conf 0.8
R2 analysis_intent    仅分析词 → RESEARCH，conf 0.9
R3 comparison_intent  仅对比词 → COMPARISON，conf 0.9
R4 multi_code_comparison 兜底：对比词 + 分析词但无强主题词 + ≥2 只代码
                      → COMPARISON，conf 0.6（代码数量作为兜底信号）
R5 fallback           无任何意图词 → RESEARCH，conf 0.3
"""

import re

from pydantic import BaseModel, Field

from domain.task_type import (
    COMPARISON_INTENT_KEYWORDS,
    ANALYSIS_INTENT_KEYWORDS,
    ClassificationRuleHit,
    TaskType,
)

_FUND_CODE_RE = re.compile(r"\b(\d{6})\b")

# 强主题词：明确以某只基金为研究主体的表述（核心 Case）
_SUBJECT_KEYWORDS = ("分析", "研究", "评估")


class IntentClassification(BaseModel):
    task_type: TaskType
    rule_hit: ClassificationRuleHit
    confidence: float = Field(ge=0, le=1)
    fund_ids: list[str] = Field(default_factory=list)


def extract_fund_codes(query: str) -> list[str]:
    """从 query 中提取 6 位基金代码（去重、保序）。"""
    seen: set[str] = set()
    codes: list[str] = []
    for m in _FUND_CODE_RE.finditer(query):
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def classify(query: str) -> IntentClassification:
    """确定性意图分类：返回任务类型 + 规则命中 + 置信度 + 提取的代码。"""
    fund_ids = extract_fund_codes(query)
    has_analysis = any(kw in query for kw in ANALYSIS_INTENT_KEYWORDS)
    has_comparison = any(kw in query for kw in COMPARISON_INTENT_KEYWORDS)
    has_subject = any(kw in query for kw in _SUBJECT_KEYWORDS)

    if has_comparison and has_analysis and has_subject:
        return IntentClassification(
            task_type=TaskType.FUND_RESEARCH,
            rule_hit=ClassificationRuleHit.R1_DUAL_INTENT_SUBJECT,
            confidence=0.8,
            fund_ids=fund_ids,
        )
    if has_analysis and not has_comparison:
        return IntentClassification(
            task_type=TaskType.FUND_RESEARCH,
            rule_hit=ClassificationRuleHit.R2_ANALYSIS_INTENT,
            confidence=0.9,
            fund_ids=fund_ids,
        )
    if has_comparison and not has_analysis:
        return IntentClassification(
            task_type=TaskType.FUND_COMPARISON,
            rule_hit=ClassificationRuleHit.R3_COMPARISON_INTENT,
            confidence=0.9,
            fund_ids=fund_ids,
        )
    if has_comparison and has_analysis and len(fund_ids) >= 2:
        # 兜底：对比词 + ≥2 只代码，但分析词较弱（无强主题词）→ 对比
        return IntentClassification(
            task_type=TaskType.FUND_COMPARISON,
            rule_hit=ClassificationRuleHit.R4_MULTI_CODE_COMPARISON,
            confidence=0.6,
            fund_ids=fund_ids,
        )
    return IntentClassification(
        task_type=TaskType.FUND_RESEARCH,
        rule_hit=ClassificationRuleHit.R5_FALLBACK,
        confidence=0.3,
        fund_ids=fund_ids,
    )


__all__ = ["IntentClassification", "extract_fund_codes", "classify"]
