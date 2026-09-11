"""Researcher 节点与 Fund Tools 持仓采集测试（Phase 6）。"""

from tests.conftest import FUND_CODE, make_tools
from nodes.researcher import ResearcherNode


class _FakeResearchProvider:
    def __init__(self, items: list) -> None:
        self._items = items
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list:
        self.queries.append(query)
        return self._items[:limit]


class TestResearcherNode:
    def test_without_provider_returns_empty_items(self):
        out = ResearcherNode()({"fund_ids": [FUND_CODE], "research_plan": None})
        assert out["research_items"] == []
        assert "evidence" not in out
        assert "data_quality_issues" not in out  # 研究缺失不是数据质量问题

    def test_with_provider_writes_items_and_research_evidence(self):
        from datetime import datetime

        from domain.research import ResearchItem

        items = [
            ResearchItem(
                title="某基金调研纪要",
                content="基金经理变更情况……",
                source="web_search",
                as_of=datetime(2026, 9, 1),
            )
        ]
        provider = _FakeResearchProvider(items)
        state = {"fund_ids": [FUND_CODE], "research_plan": None}
        out = ResearcherNode(provider)(state)

        assert out["research_items"] == items
        assert len(out["evidence"]) == 1
        evidence = out["evidence"][0]
        assert evidence.evidence_type == "research"
        assert evidence.source == "web_search"
        assert provider.queries and FUND_CODE in provider.queries[0]


class TestGetFundHoldings:
    def test_returns_structured_holdings_and_stores(self):
        tools, store, client = make_tools()
        try:
            holdings = tools.get_fund_holdings.invoke({"fund_id": FUND_CODE})
            assert len(holdings) == 2
            assert holdings[0].stock_code == "600519"
            assert holdings[0].stock_name == "贵州茅台"
            assert holdings[0].hold_ratio == 3.12
            assert store.get_holdings(FUND_CODE) == holdings
        finally:
            client.close()

    def test_empty_holdings_is_not_an_error(self):
        tools, store, client = make_tools(holdings_rows=[])
        try:
            holdings = tools.get_fund_holdings.invoke({"fund_id": FUND_CODE})
            assert holdings == []
            assert store.get_holdings(FUND_CODE) == []
        finally:
            client.close()

    def test_collector_records_holdings_evidence(self):
        tools, store, client = make_tools()
        from nodes.collector import CollectorNode

        try:
            state = {
                "user_query": f"分析基金 {FUND_CODE}",
                "research_plan": {
                    "task_type": "fund_research",
                    "primary_fund_id": FUND_CODE,
                    "fund_ids": [FUND_CODE],
                    "notes": [],
                },
            }
            out = CollectorNode(tools)(state)
            # info + performance + holdings = 3 条 fund_data 证据
            assert len(out["evidence"]) == 3
            holdings_ev = [e for e in out["evidence"] if "持仓" in (e.source_detail or "")]
            assert holdings_ev and holdings_ev[0].data_quality == "complete"
            assert holdings_ev[0].value["top_holdings"][0]["stock_name"] == "贵州茅台"
            assert out["data_quality_issues"] == []
        finally:
            client.close()
