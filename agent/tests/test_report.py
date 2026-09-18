"""Synthesizer / Report 单元测试（Phase 4 验收：结构完整 + 可追溯 + 强制免责）。"""

from domain.thesis import Claim
from domain.report import render_markdown
from nodes.synthesizer import SynthesizerNode
from tests.test_thesis import EV1, _thesis


def _base_state(**overrides) -> dict:
    state = {
        "request_id": "req-1",
        "user_query": "分析基金 519770 是否适合长期持有",
        "funds_summary": [
            {
                "id": "519770",
                "name": "交银优择回报A",
                "fund_type": "混合型-灵活配置",
                "aum": 44.16,
                "manager_name": "周珊珊 高扬",
                "as_of": "2026-09-11T12:00:00",
                "data_quality": "complete",
            }
        ],
        "evidence": [
            {"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {"a": 1}},
            {"id": "ev-bbbbbbbbbbbb", "evidence_type": "fund_data", "source": "s", "value": {"b": 2}},
        ],
        "tool_calls": [{"tool_name": "get_fund_info", "arguments": {}}],
        "analysis": {
            "performance": {
                "fund_id": "519770",
                "period_start": "2016-04-22",
                "period_end": "2026-09-10",
                "nav_point_count": 2487,
                "cumulative_return": 4.835,
                "annualized_return": 0.185,
                "data_quality": "complete",
            },
            "risk": {
                "fund_id": "519770",
                "annual_volatility": 0.1708,
                "max_drawdown": -0.2901,
                "sharpe": 1.132,
                "data_quality": "complete",
            },
            "peer_comparison": None,
        },
    }
    state.update(overrides)
    return state


class TestReportStructure:
    def test_full_report_structure_complete(self):
        thesis = _thesis(
            [
                Claim(id="c1", statement="长期业绩为正", claim_type="performance", evidence_ids=[EV1], strength="strong"),
            ],
            risks=["回撤风险"],
            data_gaps=["缺少同类对比"],
        )
        state = _base_state(investment_thesis=thesis.model_dump(mode="json"))
        report = SynthesizerNode()(state)["report"]

        # §11 关键字段
        assert report.title.startswith("FundForge 基金研究报告")
        assert report.request_id == "req-1"
        assert report.generated_at is not None
        assert "交银优择回报A" in report.executive_summary
        assert report.fund_overview[0].id == "519770"
        assert "483.50%" in report.performance_analysis or "累计收益" in report.performance_analysis
        assert "年化波动率" in report.risk_analysis
        assert report.peer_comparison is None            # 单基金无对比
        assert "周珊珊 高扬" in report.manager_analysis
        assert report.investment_thesis is not None
        # 关键结论可追溯：key_claims 与 Thesis claims 一致
        assert report.key_claims == thesis.claims
        # 数据缺口 = thesis.data_gaps；风险 = thesis.risks + 强制免责
        assert "缺少同类对比" in report.data_gaps_and_limitations
        assert "回撤风险" in report.risks_and_disclaimers
        assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)
        # 元信息
        assert report.metadata.fund_count == 1
        assert report.metadata.evidence_count == 2
        assert report.metadata.tool_call_count == 1
        assert report.metadata.thesis_generated is True

    def test_degraded_report_without_thesis(self):
        report = SynthesizerNode()(_base_state())["report"]

        assert report.investment_thesis is None
        assert report.key_claims == []
        assert any("投资论点未生成" in g for g in report.data_gaps_and_limitations)
        assert any("不构成任何投资建议" in r for r in report.risks_and_disclaimers)

    def test_empty_state_report_has_guidance(self):
        report = SynthesizerNode()({"request_id": "r", "user_query": "帮我推荐基金"})["report"]

        assert "未能采集到基金数据" in report.executive_summary
        assert any("6 位基金代码" in g for g in report.data_gaps_and_limitations)
        assert report.metadata.fund_count == 0

    def test_thesis_dicts_from_state_are_normalized(self):
        thesis = _thesis(
            [Claim(id="c1", statement="s", claim_type="peer", evidence_ids=[EV1], strength="weak")]
        )
        report = SynthesizerNode()(_base_state(investment_thesis=thesis.model_dump(mode="json")))["report"]
        assert report.key_claims[0].claim_type == "peer"


class TestReportLabelsAndHoldings:
    """P1：业绩/风险/对比章节标注基金；P2：持仓概览章节。"""

    def test_performance_and_risk_labeled_with_primary_fund(self):
        report = SynthesizerNode()(_base_state())["report"]
        assert "519770 交银优择回报A（主体基金）" in report.performance_analysis
        assert "519770 交银优择回报A（主体基金）" in report.risk_analysis

    def test_peer_rows_labeled_with_fund_names(self):
        analysis = {
            **_base_state()["analysis"],
            "peer_comparison": {
                "base_fund_id": "519770",
                "rows": [
                    {"fund_id": "519770", "annualized_return": 0.18, "annual_volatility": 0.17,
                     "max_drawdown": -0.29, "sharpe": 1.13},
                    {"fund_id": "000001", "annualized_return": 0.05, "annual_volatility": 0.10,
                     "max_drawdown": -0.15, "sharpe": 0.50},
                ],
            },
        }
        state = _base_state(analysis=analysis)
        state["funds_summary"].append(
            {"id": "000001", "name": "华夏成长混合", "as_of": "2026-09-11T12:00:00", "data_quality": "complete"}
        )
        report = SynthesizerNode()(state)["report"]
        assert "519770 交银优择回报A" in report.peer_comparison
        assert "000001 华夏成长混合" in report.peer_comparison

    def test_holdings_overview_rendered(self):
        evidence = [
            {
                "id": "ev-h1",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/holdings/stock",
                "value": {
                    "fund_id": "519770",
                    "holding_count": 12,
                    "latest_report_period": "2026年2季度股票投资明细",
                    "top_holdings": [
                        {"stock_name": "贵州茅台", "hold_ratio": 3.12},
                        {"stock_name": "宁德时代", "hold_ratio": 2.85},
                    ],
                    "failed": False,
                },
            }
        ]
        report = SynthesizerNode()(_base_state(evidence=evidence))["report"]
        assert report.holdings_analysis is not None
        assert "519770 交银优择回报A" in report.holdings_analysis
        assert "报告期 2026年2季度股票投资明细" in report.holdings_analysis
        assert "贵州茅台 3.12%" in report.holdings_analysis
        assert "## 持仓概览（最新报告期前十大）" in render_markdown(report)

    def test_no_holdings_no_section(self):
        report = SynthesizerNode()(_base_state())["report"]
        assert report.holdings_analysis is None
        assert "持仓概览" not in render_markdown(report)


class TestMarkdownRendering:
    def test_render_markdown_contains_core_sections(self):
        thesis = _thesis(
            [Claim(id="c1", statement="长期业绩为正", claim_type="performance", evidence_ids=[EV1], strength="strong")]
        )
        report = SynthesizerNode()(_base_state(investment_thesis=thesis.model_dump(mode="json")))["report"]
        md = render_markdown(report)

        for section in ["# FundForge 基金研究报告", "## 摘要", "## 基金概览", "## 业绩分析",
                        "## 风险分析", "## 投资论点", "## 关键结论追溯", "## 风险提示与免责声明"]:
            assert section in md
        assert "长期业绩为正" in md
        assert EV1 in md                     # 结论可追溯到 Evidence id
        assert "不构成任何投资建议" in md
