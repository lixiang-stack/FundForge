"""Phase 6 标准三基金 Case 回归基线（确定性，常驻运行）。

固化「分析基金 A 是否适合长期持有，并与 B、C 比较」的端到端预期，
防止后续改动悄然改变关键产物（证据数、Claim 绑定、评估结论）。

基线口径（conftest 模拟数据，3 只基金同构）：
- Evidence：每基金 3 条 fund_data（基本信息/净值序列/持仓）+ 1 条 calculation = 12
- Claim：DynamicThesisProvider 生成 1 条，且必须绑定真实 Evidence（覆盖率 1.0 ≥ 0.5 阈值）
- Evaluation：pass，无 critical
- Report：peer 对比 3 行，含强制免责声明
"""

from domain.task_type import TaskType
from graph import build_graph
from tests.conftest import FUND_CODE, make_transport
from tests.test_thesis import DynamicThesisProvider
from tools.collector_client import CollectorClient

# Phase 6 标准三基金（真实代码，用于集成测试与基线口径一致）
STANDARD_CODES = ["519770", "004814", "015453"]

_QUERY = "分析基金 519770 是否适合长期持有，并与 004814、015453 进行比较"

# ---- 基线期望值 ----
EXPECTED_FUNDS = 3
EXPECTED_EVIDENCE = 12          # 3 基金 × (3 fund_data + 1 calculation)
EXPECTED_CLAIMS = 1             # DynamicThesisProvider 固定 1 条
MIN_COVERAGE = 0.5              # Evaluator 硬阈值下限


class TestStandardThreeFundBaseline:
    def _run(self):
        client = CollectorClient(
            base_url="http://collector.test", transport=make_transport()
        )
        graph = build_graph(client=client, llm=DynamicThesisProvider())
        try:
            return graph.invoke({"request_id": "baseline", "user_query": _QUERY})
        finally:
            client.close()

    def test_baseline_artifacts(self):
        result = self._run()

        assert result["task_type"] == TaskType.FUND_RESEARCH
        assert result["fund_ids"] == STANDARD_CODES
        assert result["peer_fund_ids"] == STANDARD_CODES[1:]
        assert len(result["funds_summary"]) == EXPECTED_FUNDS
        assert len(result["evidence"]) == EXPECTED_EVIDENCE

        # Claim 绑定：数量与覆盖率下限
        thesis = result["investment_thesis"]
        assert len(thesis.claims) == EXPECTED_CLAIMS
        valid_ids = {e.id for e in result["evidence"]}
        for claim in thesis.claims:
            assert set(claim.evidence_ids) <= valid_ids
        evaluation = result["evaluation"]
        assert evaluation.claim_coverage_ratio >= MIN_COVERAGE
        assert evaluation.status == "pass"
        assert evaluation.critical is False

        # 报告：三基金对比 + 强制免责
        report = result["report"]
        assert report.metadata.fund_count == EXPECTED_FUNDS
        assert report.metadata.evidence_count == EXPECTED_EVIDENCE
        assert report.peer_comparison is not None
        assert len(result["analysis"].peer_comparison.rows) == EXPECTED_FUNDS
        assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)

    def test_baseline_is_deterministic(self):
        first = self._run()
        second = self._run()
        # 去除时间戳后产物结构一致（id 随机，数量与状态可比）
        assert len(first["evidence"]) == len(second["evidence"])
        assert len(first["investment_thesis"].claims) == len(second["investment_thesis"].claims)
        assert first["evaluation"].status == second["evaluation"].status
        assert first["evaluation"].claim_coverage_ratio == second["evaluation"].claim_coverage_ratio
