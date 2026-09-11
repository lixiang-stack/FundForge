"""Graph 级测试：条件边路由 + Thesis 绑定（无 fund_ids 时短路跳过 collector）。"""

from tests.conftest import FUND_CODE, make_transport
from tests.test_thesis import DynamicThesisProvider
from graph import build_graph
from tools.collector_client import CollectorClient


def _build(llm=None):
    client = CollectorClient(
        base_url="http://collector.test", transport=make_transport()
    )
    return build_graph(client=client, llm=llm), client


class TestConditionalRouting:
    def test_full_flow_with_fund_code(self):
        graph, client = _build(llm=DynamicThesisProvider())
        try:
            result = graph.invoke({"request_id": "t1", "user_query": f"分析基金 {FUND_CODE}"})
            assert result["funds_summary"][0].id == FUND_CODE
            assert result.get("tool_calls", []) != []
            assert result.get("data_quality_issues", []) == []
            # Thesis 生成且 Claim 绑定真实 Evidence
            thesis = result.get("investment_thesis")
            assert thesis is not None
            valid_ids = {e.id for e in result["evidence"]}
            for c in thesis.claims:
                assert set(c.evidence_ids) <= valid_ids
            # 评估通过，未触发修复
            report = result["report"]
            assert report.metadata.thesis_generated is True
            assert report.metadata.evaluation_status == "pass"
            assert report.metadata.repair_applied is False
            assert report.key_claims == thesis.claims
            assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)
        finally:
            client.close()

    def test_short_circuit_without_fund_code(self):
        graph, client = _build()
        try:
            result = graph.invoke({"request_id": "t2", "user_query": "帮我推荐基金"})
            # collector 未执行：其输出键不写入 State（TypedDict total=False）
            assert result.get("funds_summary", []) == []
            assert result.get("tool_calls", []) == []
            assert result.get("evidence", []) == []
            # 降级 Report：结构完整，包含引导信息与免责声明
            report = result["report"]
            assert "未能采集到基金数据" in report.executive_summary
            assert any("6 位基金代码" in g for g in report.data_gaps_and_limitations)
            assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)
        finally:
            client.close()


class TestRepairLoop:
    def test_missing_evidence_triggers_repair_then_forced_synthesizer(self):
        """验收：故意制造缺失 Evidence → Evaluator 检出 → Repair → 仍 FAIL → 强制 synthesizer。"""
        # nav 全空 → performance Evidence data_quality=missing（采集"成功"但数据缺失）
        client = CollectorClient(
            base_url="http://collector.test",
            transport=make_transport(unit_rows=[], acc_rows=[]),
        )
        try:
            graph = build_graph(client=client, llm=DynamicThesisProvider(cite="all"))
            result = graph.invoke(
                {"request_id": "t5", "user_query": f"分析基金 {FUND_CODE} 是否适合长期持有"}
            )

            # Evaluator 检出 factual issue（claim 引用 missing 质量证据）
            evaluation = result["evaluation"]
            assert evaluation.status == "fail"
            assert evaluation.factual_issues

            # Repair 执行过恰好 1 次（iteration 硬限制），且执行了降置信度动作
            assert result["iteration"] == 1
            assert any(a.startswith("reduce_confidence") for a in result.get("repair_actions", []))
            assert result["investment_thesis"].confidence == 0.25  # 0.5 * 0.5

            # 强制进入 synthesizer，报告标注证据不足
            report = result["report"]
            assert report.metadata.evaluation_status == "fail"
            assert report.metadata.repair_applied is True
            assert any("证据不足" in g for g in report.data_gaps_and_limitations)
        finally:
            client.close()
