"""评估与修复领域模型（docs/TechnicalContract.md §10）。

V1 全确定性实现：Evaluator / Repair 不调用 LLM（ConceptDesign §8：
验证 Agent，而不是让 Agent 无限反思）。
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class EvaluationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class RepairActionType(StrEnum):
    """Repair 允许动作（§10，max=1）。"""

    FETCH_MISSING_DATA = "fetch_missing_data"
    ADD_EVIDENCE = "add_evidence"
    REVISE_CLAIM = "revise_claim"
    ADD_RISK_DISCLOSURE = "add_risk_disclosure"
    REDUCE_CONFIDENCE = "reduce_confidence"


class EvaluationResult(BaseModel):
    status: EvaluationStatus
    factual_issues: list[str] = Field(default_factory=list)
    evidence_issues: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    risk_issues: list[str] = Field(default_factory=list)
    question_alignment_issues: list[str] = Field(default_factory=list)
    data_quality_issues: list[str] = Field(default_factory=list)
    overall_score: float = Field(default=0.0, ge=0, le=1)
    critical: bool = False                # 致命问题（数据错误 / 严重幻觉）

    def all_issues(self) -> list[str]:
        return [
            *self.factual_issues,
            *self.evidence_issues,
            *self.missing_items,
            *self.risk_issues,
            *self.question_alignment_issues,
            *self.data_quality_issues,
        ]


class RepairAction(BaseModel):
    action_type: RepairActionType
    target: str
    reason: str


__all__ = ["EvaluationStatus", "RepairActionType", "EvaluationResult", "RepairAction"]
