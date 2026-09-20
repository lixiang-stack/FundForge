"""评测用确定性 Fake LLM Provider（Phase 10）。

与 tests/test_thesis.DynamicThesisProvider 同思路但独立维护（评测不反向依赖测试夹具）：
从 prompt 上下文读取真实 evidence id，保证 Claim 绑定校验可过；不发真实请求。

- DeterministicThesisProvider  固定 1 条有效绑定 Claim（离线确定性基准）
- BadBindingThesisProvider     固产出坏绑定 Claim（c1 空绑定 / c2 未知引用 / c3 有效），
                               回归保护：ThesisNode 的绑定降级路径
"""

import json
from collections.abc import Callable

from domain.thesis import Claim, InvestmentThesis
from llm.base import LLMResponse


def _evidence_ids_from_prompt(messages) -> list[str]:
    """从 thesis prompt 的 user 消息中解析真实 evidence id。"""
    context = json.loads(messages[1].content.split("：\n", 1)[1])
    return [e["id"] for e in context["evidence"]]


def _per_fund_evidence_ids(messages) -> list[str]:
    """每只基金取首条证据 id（按 prompt 顺序去重）。

    单基金退化为首条证据；对比任务天然绑定双方证据，
    满足「跨基金对比 claim」口径（与 Evaluator 对齐）。
    """
    context = json.loads(messages[1].content.split("：\n", 1)[1])
    picked: list[str] = []
    seen: set[str] = set()
    for e in context["evidence"]:
        fund_id = (e.get("value") or {}).get("fund_id")
        if fund_id and fund_id not in seen:
            seen.add(fund_id)
            picked.append(e["id"])
    return picked or _evidence_ids_from_prompt(messages)[:1]


class DeterministicThesisProvider:
    """固定产出 1 条绑定「每基金首条证据」的 Claim（suitability 回应长期持有维度）。"""

    def generate(self, messages, *, structured_output=None) -> LLMResponse:
        ev_ids = _per_fund_evidence_ids(messages)
        thesis = InvestmentThesis(
            summary="概要（确定性 Fake LLM 输出）",
            claims=[
                Claim(
                    id="c1",
                    statement="基于采集证据的确定性结论",
                    claim_type="performance",
                    evidence_ids=ev_ids,
                    strength="moderate",
                )
            ],
            suitability="证据支持下可考虑长期持有（确定性示例结论）",
            confidence=0.5,
            risks=["历史业绩不代表未来表现"],
        )
        return LLMResponse(content=thesis.model_dump_json(), input_tokens=10, output_tokens=10)


class BadBindingThesisProvider:
    """c1 空绑定（降级 data_gaps）/ c2 未知引用（丢弃并记 issue）/ c3 有效绑定。"""

    def generate(self, messages, *, structured_output=None) -> LLMResponse:
        ev_ids = _evidence_ids_from_prompt(messages)
        thesis = InvestmentThesis(
            summary="概要（坏绑定回归用例）",
            claims=[
                Claim(id="c1", statement="无证据的结论", claim_type="risk", evidence_ids=[], strength="weak"),
                Claim(
                    id="c2",
                    statement="引用不存在证据的结论",
                    claim_type="peer",
                    evidence_ids=["ev-nonexistent"],
                    strength="weak",
                ),
                Claim(
                    id="c3",
                    statement="有效绑定的结论",
                    claim_type="performance",
                    evidence_ids=ev_ids[:1],
                    strength="strong",
                ),
            ],
            suitability="有效证据支持下可考虑长期持有",
            confidence=0.4,
            risks=["历史业绩不代表未来表现"],
        )
        return LLMResponse(content=thesis.model_dump_json(), input_tokens=10, output_tokens=10)


FAKE_LLM_BUILDERS: dict[str, Callable[[], object]] = {
    "fake": DeterministicThesisProvider,
    "fake_bad_binding": BadBindingThesisProvider,
}


def build_fake_llm(name: str):
    """按档位名构建 Fake Provider；未知档位抛错（fail fast）。"""
    factory = FAKE_LLM_BUILDERS.get(name)
    if factory is None:
        raise ValueError(f"未知 llm 档位：{name!r}（可选：real / {sorted(FAKE_LLM_BUILDERS)}）")
    return factory()


__all__ = ["FAKE_LLM_BUILDERS", "build_fake_llm"]
