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
            # 结构化 Report：关键结论可追溯到 Claim
            report = result["report"]
            assert report.metadata.thesis_generated is True
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
