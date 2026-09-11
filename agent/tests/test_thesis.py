"""ThesisNode 单元测试（Phase 3 验收：Claim 绑定完整性 + 降级行为）。

LLM 通过 Fake Provider 模拟，不发真实请求。
"""

import json

import pytest
from pydantic import ValidationError

from domain.thesis import Claim, InvestmentThesis
from domain.report import render_markdown
from llm.base import LLMError, LLMResponse, Message
from nodes.thesis import ThesisNode, build_thesis_prompt
from tests.conftest import FUND_CODE, make_transport

EV1 = "ev-aaaaaaaaaaaa"
EV2 = "ev-bbbbbbbbbbbb"


def _state() -> dict:
    return {
        "user_query": f"分析基金 {FUND_CODE} 是否适合长期持有",
        "evidence": [
            {"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {"a": 1}},
            {"id": EV2, "evidence_type": "fund_data", "source": "s", "value": {"b": 2}},
        ],
    }


def _thesis(claims: list[Claim], **overrides) -> InvestmentThesis:
    defaults = dict(
        summary="概要",
        claims=claims,
        positives=["p"],
        negatives=["n"],
        risks=["r"],
        key_assumptions=["a"],
        suitability="适合长期持有（示例）",
        confidence=0.6,
        data_gaps=[],
    )
    defaults.update(overrides)
    return InvestmentThesis(**defaults)


class FakeLLMProvider:
    """可编程假 Provider：返回预置 Thesis 或抛出异常，记录调用。"""

    def __init__(self, result: InvestmentThesis | Exception) -> None:
        self._result = result
        self.calls: list[list[Message]] = []

    def generate(self, messages, *, structured_output=None) -> LLMResponse:
        self.calls.append(messages)
        if isinstance(self._result, Exception):
            raise self._result
        return LLMResponse(content=self._result.model_dump_json())


class DynamicThesisProvider:
    """从 prompt 上下文读取真实 evidence id，动态构造合法 Thesis（graph 级测试用）。"""

    def generate(self, messages, *, structured_output=None) -> LLMResponse:
        context = json.loads(messages[1].content.split("：\n", 1)[1])
        ev_ids = [e["id"] for e in context["evidence"]]
        thesis = InvestmentThesis(
            summary="概要",
            claims=[
                Claim(
                    id="c1",
                    statement="基于采集证据的结论",
                    claim_type="performance",
                    evidence_ids=ev_ids[:1],
                    strength="moderate",
                )
            ],
            suitability="适合长期持有（示例）",
            confidence=0.5,
        )
        return LLMResponse(content=thesis.model_dump_json())


class TestThesisNode:
    def test_valid_thesis_passes_binding_check(self):
        thesis = _thesis(
            [Claim(id="c1", statement="回撤可控", claim_type="risk", evidence_ids=[EV1], strength="strong")]
        )
        out = ThesisNode(FakeLLMProvider(thesis))(_state())

        assert out["investment_thesis"].suitability == "适合长期持有（示例）"
        assert out["investment_thesis"].confidence == pytest.approx(0.6)
        assert len(out["claims"]) == 1
        assert out["claims"][0].id == "claim-1"  # id 被规范化
        assert out["claims"][0].evidence_ids == [EV1]
        assert out["data_quality_issues"] == []

    def test_missing_evidence_ids_fails_validation(self):
        # Pydantic 强制 evidence_ids 非空：缺失 → 无法构造 Claim
        bad = {"id": "c1", "statement": "s", "claim_type": "risk", "evidence_ids": [], "strength": "weak"}
        with pytest.raises(ValidationError):
            Claim(**bad)

    def test_unknown_evidence_reference_dropped(self):
        thesis = _thesis(
            [
                Claim(id="c1", statement="有效结论", claim_type="risk", evidence_ids=[EV1], strength="strong"),
                Claim(id="c2", statement="坏引用", claim_type="peer", evidence_ids=["ev-nonexistent"], strength="weak"),
            ]
        )
        out = ThesisNode(FakeLLMProvider(thesis))(_state())

        assert len(out["claims"]) == 1
        assert out["claims"][0].statement == "有效结论"
        assert any("不存在的证据" in i for i in out["data_quality_issues"])
        assert out["investment_thesis"] is not None

    def test_all_claims_invalid_yields_no_thesis(self):
        thesis = _thesis(
            [Claim(id="c1", statement="坏引用", claim_type="peer", evidence_ids=["ev-x"], strength="weak")]
        )
        out = ThesisNode(FakeLLMProvider(thesis))(_state())

        assert "investment_thesis" not in out
        assert any("证据引用均无效" in i for i in out["data_quality_issues"])

    def test_llm_error_degrades(self):
        out = ThesisNode(FakeLLMProvider(LLMError("boom")))(_state())
        assert any("投资论点生成失败" in i for i in out["data_quality_issues"])

    def test_unconfigured_llm_degrades(self):
        out = ThesisNode(None)(_state())
        assert any("LLM 未配置" in i for i in out["data_quality_issues"])

    def test_no_evidence_skips(self):
        out = ThesisNode(FakeLLMProvider(_thesis([])))({"user_query": "q", "evidence": []})
        assert any("无可用 Evidence" in i for i in out["data_quality_issues"])

    def test_prompt_contains_evidence_ids(self):
        messages = build_thesis_prompt(_state())
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert EV1 in messages[1].content
        assert FUND_CODE in messages[1].content


class TestThesisInGraph:
    """graph 级：collector 采集 → analyzer 计算 → thesis 引用真实 evidence id。"""

    def test_full_flow_binds_claims_to_real_evidence(self):
        from graph import build_graph
        from tools.collector_client import CollectorClient

        client = CollectorClient(base_url="http://collector.test", transport=make_transport())
        try:
            graph = build_graph(client=client, llm=DynamicThesisProvider())
            result = graph.invoke(
                {"request_id": "t3", "user_query": f"分析基金 {FUND_CODE} 是否适合长期持有"}
            )

            thesis = result.get("investment_thesis")
            assert thesis is not None
            assert thesis.suitability
            assert 0 <= thesis.confidence <= 1
            # 每个关键 Claim 绑定的 evidence 都真实存在于本 State
            valid_ids = {e.id for e in result["evidence"]}
            assert thesis.claims
            for c in thesis.claims:
                assert c.evidence_ids
                assert set(c.evidence_ids) <= valid_ids
            # 报告包含论点段落
            report = result["report"]
            assert report.investment_thesis is not None
            assert "免责声明" in render_markdown(report)
        finally:
            client.close()

    def test_full_flow_without_llm_degrades_gracefully(self):
        from graph import build_graph
        from tools.collector_client import CollectorClient

        client = CollectorClient(base_url="http://collector.test", transport=make_transport())
        try:
            graph = build_graph(client=client, llm=None)
            result = graph.invoke({"request_id": "t4", "user_query": f"分析基金 {FUND_CODE}"})
            assert "investment_thesis" not in result
            assert any("LLM 未配置" in i for i in result.get("data_quality_issues", []))
            report = result["report"]
            assert report.investment_thesis is None
            assert "免责声明" in render_markdown(report)
        finally:
            client.close()
