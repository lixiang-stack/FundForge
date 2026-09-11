"""InvestmentThesis 领域模型（docs/TechnicalContract.md §8）。

强制规则：
- 每一个重要投资结论必须对应至少一个 Claim；
- 每个 Claim 必须绑定 evidence_ids（Pydantic 层强制非空）；
- 节点层还须校验 evidence_ids 指向真实存在的 Evidence。

取值固定的枚举（ClaimType / Strength）以 StrEnum 定义为唯一来源，
LLM 提示词中的取值列表从枚举派生，避免多处维护漂移。
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    PERFORMANCE = "performance"
    RISK = "risk"
    STYLE = "style"
    MANAGER = "manager"
    PORTFOLIO = "portfolio"
    PEER = "peer"
    SUITABILITY = "suitability"


class Strength(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class Claim(BaseModel):
    id: str
    statement: str
    claim_type: ClaimType
    evidence_ids: list[str] = Field(min_length=1)   # 强制：至少 1 个
    strength: Strength
    assumptions: list[str] = Field(default_factory=list)


class InvestmentThesis(BaseModel):
    summary: str
    claims: list[Claim]                    # 所有重要结论必须在这里
    positives: list[str] = Field(default_factory=list)
    negatives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    suitability: str                       # 针对「是否适合长期持有」的明确回答
    confidence: float = Field(ge=0, le=1)  # 证据充分程度（非未来收益概率）
    data_gaps: list[str] = Field(default_factory=list)


__all__ = ["Claim", "InvestmentThesis", "ClaimType", "Strength"]
