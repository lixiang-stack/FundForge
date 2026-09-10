"""Graph 级测试：条件边路由（无 fund_ids 时短路跳过 collector）。"""

from tests.conftest import FUND_CODE, make_transport
from graph import build_graph
from tools.collector_client import CollectorClient


def _build():
    client = CollectorClient(
        base_url="http://collector.test", transport=make_transport()
    )
    return build_graph(client=client), client


class TestConditionalRouting:
    def test_full_flow_with_fund_code(self):
        graph, client = _build()
        try:
            result = graph.invoke({"request_id": "t1", "user_query": f"分析基金 {FUND_CODE}"})
            assert result["funds_summary"][0].id == FUND_CODE
            assert result.get("tool_calls", []) != []
            assert result.get("data_quality_issues", []) == []
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
            # synthesizer 输出引导信息
            assert "未能采集到基金数据" in result["report"]
            assert "6 位基金代码" in result["report"]
        finally:
            client.close()
