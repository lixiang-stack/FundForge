"""Thesis 节点（Node 合同 §4，Phase 3 首次引入 LLM 调用）。

职责：基于事实和证据形成投资判断。LLM 只负责 Interpretation / Reasoning /
Trade-off / Risk Identification，不负责事实和关键计算（事实来自 Evidence，
指标来自 Analyzer）。

强制校验（§8）：
- Claim.evidence_ids 由 Pydantic 强制非空（缺失 → 解析失败）；
- evidence_ids 必须指向 State 中真实存在的 Evidence（未知引用 → 丢弃该 Claim 并记录 issue）；
- 全部 Claim 无效 → 不产出 Thesis，记录 issue（Phase 5 的 Evaluator/Repair 接管后续）。
"""

import json
import logging
import uuid
from typing import TypedDict

from pydantic import ValidationError

from domain.evidence import Evidence, TokenUsage
from domain.thesis import Claim, ClaimType, InvestmentThesis, Strength
from domain.shared import to_jsonable
from llm.base import LLMError, LLMProvider, Message
from state import FundForgeState

logger = logging.getLogger(__name__)

# 取值列表从枚举派生（单一来源），避免提示词与 Pydantic 校验漂移
_CLAIM_TYPES = "|".join(t.value for t in ClaimType)
_STRENGTHS = "|".join(s.value for s in Strength)

_SYSTEM_PROMPT = f"""你是基金投资研究员，基于给定的事实数据与证据形成投资判断。

规则：
1. 只能引用提供的 Evidence（按 id 引用），严禁编造数据或引用不存在的证据。
2. 每个重要结论（claim）必须绑定至少一个 evidence_id。
3. suitability 必须直接回答「是否适合长期持有」。
4. confidence 表示证据充分程度（0~1），不是未来收益概率。
5. 量化指标来自确定性计算，直接引用即可，不要自行计算。
6. 只输出符合以下结构的 JSON：
{{
  "summary": "论点概要",
  "claims": [{{"id": "c1", "statement": "结论", "claim_type": "{_CLAIM_TYPES}",
              "evidence_ids": ["ev-xxx"], "strength": "{_STRENGTHS}", "assumptions": []}}],
  "positives": [], "negatives": [], "risks": [], "key_assumptions": [],
  "suitability": "是否适合长期持有的明确回答",
  "confidence": 0.0,
  "data_gaps": []
}}"""


def build_thesis_prompt(state: FundForgeState) -> list[Message]:
    """组装 Thesis 节点的上下文：用户问题 + 摘要 + 分析 + Evidence。"""
    # State 经 LangGraph 回传后可能是 dict，统一归一化为 JSON 安全结构
    evidence = [
        e if isinstance(e, Evidence) else Evidence.model_validate(e)
        for e in state.get("evidence", [])
    ]
    context = {
        "user_query": state.get("user_query", ""),
        "funds_summary": [
            s if isinstance(s, dict) else s.model_dump(mode="json")
            for s in state.get("funds_summary", [])
        ],
        "analysis": to_jsonable(state.get("analysis")),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "data_quality_issues": state.get("data_quality_issues", []),
    }
    user_prompt = (
        "请基于以下上下文形成投资论点：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
    return [Message("system", _SYSTEM_PROMPT), Message("user", user_prompt)]


class ThesisOutput(TypedDict, total=False):
    """Thesis 节点输出（§4：claims, investment_thesis；data_quality_issues 记录降级）。"""

    claims: list[Claim]
    investment_thesis: InvestmentThesis
    data_quality_issues: list[str]
    token_usage: TokenUsage


class ThesisNode:
    """Thesis 节点：调用 LLM 生成投资论点，强制 Evidence 绑定。"""

    def __init__(self, llm: LLMProvider | None) -> None:
        self._llm = llm

    def __call__(self, state: FundForgeState) -> ThesisOutput:
        if self._llm is None:
            return self._degrade(
                state,
                "LLM 未配置（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL），无法生成投资论点",
            )
        # State 经 LangGraph 回传后可能是 dict，统一归一化
        evidence = [
            e if isinstance(e, Evidence) else Evidence.model_validate(e)
            for e in state.get("evidence", [])
        ]
        if not evidence:
            return self._degrade(state, "无可用 Evidence，跳过投资论点生成")

        usage = self._current_usage(state)
        try:
            response = self._llm.generate(
                build_thesis_prompt(state),
                structured_output=InvestmentThesis,
            )
            usage = usage.merged(
                TokenUsage(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    llm_calls=1,
                )
            )
            thesis = InvestmentThesis.model_validate_json(response.content)
        except (LLMError, ValidationError, ValueError) as e:
            logger.error("thesis generation failed: %s", e)
            return self._degrade(state, f"投资论点生成失败：{e}", token_usage=usage)

        valid_ids = {e.id for e in evidence}
        valid_claims: list[Claim] = []
        issues: list[str] = []
        for claim in thesis.claims:
            unknown = [eid for eid in claim.evidence_ids if eid not in valid_ids]
            if unknown:
                issues.append(f"claim {claim.id} 引用了不存在的证据 {unknown}，已丢弃")
                continue
            valid_claims.append(claim)

        if not valid_claims:
            return self._degrade(
                state,
                "投资论点校验失败：所有 Claim 的证据引用均无效",
                extra_issues=issues,
            )

        thesis = thesis.model_copy(
            update={
                # 重写 claim id 保证唯一且格式统一
                "claims": [c.model_copy(update={"id": f"claim-{i + 1}"}) for i, c in enumerate(valid_claims)]
            }
        )
        all_issues = [*state.get("data_quality_issues", []), *issues]
        logger.info(
            "thesis: %d claims (of %d), confidence=%.2f",
            len(thesis.claims),
            len(thesis.claims) + len(issues),
            thesis.confidence,
        )
        return ThesisOutput(
            claims=list(thesis.claims),
            investment_thesis=thesis,
            data_quality_issues=all_issues,
            token_usage=usage,
        )

    def _degrade(
        self,
        state: FundForgeState,
        reason: str,
        extra_issues: list[str] | None = None,
        token_usage: TokenUsage | None = None,
    ) -> ThesisOutput:
        """Thesis 失败时降级：不产出论点，记录 issue，不中断工作流。"""
        logger.warning("thesis degraded: %s", reason)
        output = ThesisOutput(
            data_quality_issues=[
                *state.get("data_quality_issues", []),
                *(extra_issues or []),
                reason,
            ]
        )
        if token_usage is not None:
            output["token_usage"] = token_usage
        return output

    @staticmethod
    def _current_usage(state: FundForgeState) -> TokenUsage:
        raw = state.get("token_usage")
        if raw is None or isinstance(raw, TokenUsage):
            return raw or TokenUsage()
        return TokenUsage.model_validate(raw)


__all__ = ["ThesisNode", "build_thesis_prompt"]
