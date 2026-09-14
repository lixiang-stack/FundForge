"""集成测试：真实基金代码 + 真实 collector 数据路径 + 失败注入。

需要运行中的 collector 服务（`docker compose up -d collector`）；
LLM 使用确定性 Fake Provider，不产生真实 API 调用与费用。

运行方式（默认 pytest 会跳过 integration 标记）：
    uv --directory agent run pytest -m integration

覆盖的真实基金代码：519770 / 004814 / 015453 / 001074。
"""

from datetime import date, timedelta

import httpx
import pytest

from config import collector_base_url
from graph import build_graph
from tests.test_thesis import DynamicThesisProvider
from tools.collector_client import CollectorClient

pytestmark = pytest.mark.integration

# 真实基金代码（Phase 6 标准 Case 用 519770 为主基金）
PRIMARY = "519770"
PEERS = ["004814", "015453"]
STANDARD_QUERY = f"分析基金 {PRIMARY} 是否适合长期持有，并与 004814、015453 进行比较"
MAX_ALIGNMENT_DAYS = 365 * 10


def _collector_available() -> bool:
    try:
        resp = httpx.get(f"{collector_base_url().rstrip('/')}/health", timeout=3.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


if not _collector_available():
    pytest.skip(
        f"collector 不可用（{collector_base_url()}），跳过集成测试；"
        "请先 docker compose up -d collector",
        allow_module_level=True,
    )


def _run(query: str, codes: list[str] | None = None):
    client = CollectorClient()
    graph = build_graph(client=client, llm=DynamicThesisProvider())
    try:
        return graph.invoke({"request_id": "integration", "user_query": query})
    finally:
        client.close()


class TestRealDataPath:
    def test_three_fund_standard_case_real_data(self):
        result = _run(STANDARD_QUERY)

        # 真实采集：三只基金全部 complete
        assert result["fund_ids"] == [PRIMARY, *PEERS]
        assert len(result["funds_summary"]) == 3
        assert all(s.data_quality == "complete" for s in result["funds_summary"])

        # 真实数据量：每基金 ≥3 条 fund_data + ≥1 条 calculation
        assert len(result["evidence"]) >= 12
        evidence_types = {e.evidence_type for e in result["evidence"]}
        assert {"fund_data", "calculation"} <= evidence_types

        # 绑定与评估：Claim 全部绑定真实 Evidence，覆盖率满足硬阈值
        thesis = result["investment_thesis"]
        assert thesis is not None and len(thesis.claims) >= 1
        valid_ids = {e.id for e in result["evidence"]}
        for claim in thesis.claims:
            assert set(claim.evidence_ids) <= valid_ids
        assert result["evaluation"].claim_coverage_ratio >= 0.5

        # 对齐窗口：若生成对比则不超过 10 年
        analysis = result["analysis"]
        if analysis.peer_comparison is not None:
            assert len(analysis.peer_comparison.rows) == 3
            start, end = analysis.performance.period_start, analysis.performance.period_end
            assert (end - start) <= timedelta(days=MAX_ALIGNMENT_DAYS)
        else:
            assert any("对齐区间不足" in i for i in result.get("data_quality_issues", []))

        assert any("不构成任何投资建议" in r for r in result["report"].risks_and_disclaimers)

    def test_single_fund_real_data(self):
        result = _run("分析基金 001074 是否适合长期持有")

        assert result["fund_ids"] == ["001074"]
        assert result["analysis"].peer_comparison is None
        assert result["report"].peer_comparison is None
        assert result["investment_thesis"] is not None


class TestFailureInjection:
    def test_bogus_code_degrades_but_workflow_completes(self):
        """失败注入：不存在的基金代码与真实基金混用。"""
        result = _run(f"分析基金 {PRIMARY}，并与 999999 比较")

        # 真实基金正常，假代码被标记问题
        summaries = {s.id: s for s in result["funds_summary"]}
        assert PRIMARY in summaries and summaries[PRIMARY].data_quality == "complete"
        issues = " ".join(result.get("data_quality_issues", []))
        assert "999999" in issues

        # 工作流不中断：报告与免责声明完整
        report = result["report"]
        assert report is not None
        assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)
        # 失败注入下评估仍产出结论（pass 或 fail 均可，但必须有 evaluation）
        assert result["evaluation"] is not None
