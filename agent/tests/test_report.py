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


class TestReportNewSections:
    """数据缺口补齐：费率与评级、持仓概览的行业/资产配置、同类排名渲染。"""

    def _enriched_evidence(self) -> list:
        return [
            {
                "id": "ev-fee0000001",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/fees",
                "value": {
                    "fund_id": "519770",
                    "management_fee_rate": 1.0,
                    "custodian_fee_rate": 0.15,
                    "service_fee_rate": 0.0,
                },
            },
            {
                "id": "ev-rat0000001",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/rating",
                "value": {
                    "fund_id": "519770",
                    "five_star_count": 2,
                    "rating_sh": 4.0,
                    "rating_zs": 5.0,
                    "rating_ja": 4.0,
                    "rating_mx": 5.0,
                },
            },
            {
                "id": "ev-ind0000001",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/industry",
                "value": {
                    "fund_id": "519770",
                    "latest_report_date": "2026-06-30",
                    "row_count": 2,
                    "top_industries": [
                        {"industry": "制造业", "nav_ratio": 68.96},
                        {"industry": "金融业", "nav_ratio": 6.78},
                    ],
                },
            },
            {
                "id": "ev-alo0000001",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/allocation",
                "value": {
                    "fund_id": "519770",
                    "allocation": [
                        {"asset_type": "股票", "percent": 94.18},
                        {"asset_type": "现金", "percent": 5.46},
                    ],
                },
            },
            {
                "id": "ev-ach0000001",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/achievement",
                "value": {
                    "fund_id": "519770",
                    "achievement": [
                        {
                            "performance_type": "年度业绩",
                            "period": "成立以来",
                            "return_rate": 53.44,
                            "max_drawdown": 27.6,
                            "category_rank": "308/1070",
                        }
                    ],
                },
            },
        ]

    def test_cost_and_rating_section(self):
        state = _base_state(evidence=self._enriched_evidence())
        report = SynthesizerNode()(state)["report"]

        assert report.cost_and_rating is not None
        assert "管理费 1.00%/年、托管费 0.15%/年" in report.cost_and_rating
        assert "第三方评级（2 家五星）：上海证券 4星、招商证券 5星、济安金信 4星、晨星 5星" in report.cost_and_rating
        # 同类排名：分位数 + 原始名次 + 各自类型标注 + 跨类型口径提示
        assert "（混合型-灵活配置）同类排名：成立以来 前 28.8%（308/1070）" in report.cost_and_rating
        assert "跨类型基金之间不可直接比较" in report.cost_and_rating
        assert "## 费率、评级与同类排名" in render_markdown(report)

    def test_cost_and_rating_absent_without_evidence(self):
        report = SynthesizerNode()(_base_state())["report"]
        assert report.cost_and_rating is None
        assert "费率与评级" not in render_markdown(report)

    def test_holdings_industry_and_allocation_lines(self):
        state = _base_state(evidence=self._enriched_evidence())
        report = SynthesizerNode()(state)["report"]

        assert "行业配置（2026-06-30前五）：制造业 68.96%、金融业 6.78%" in report.holdings_analysis
        assert "资产配置：股票 94.18%、现金 5.46%" in report.holdings_analysis

    def test_market_split_rendered_as_percent(self):
        # 回归：market_split 字段本身是百分数（59.89 表示 59.89%），
        # 渲染不得再走 _fmt_pct（小数×100），否则出现 5989.00% 双重百分比
        analysis = _base_state()["analysis"] | {
            "holdings_metrics": [
                {
                    "fund_id": "519770",
                    "top10_sum": 42.36,
                    "holding_count": 83,
                    "market_split": {"a_share_ratio": 59.89, "hk_share_ratio": 40.53},
                }
            ]
        }
        state = _base_state(analysis=analysis, evidence=self._enriched_evidence())
        report = SynthesizerNode()(state)["report"]

        assert "市场分布（占披露持仓净值比）：A股 59.89%、港股 40.53%" in report.holdings_analysis
        assert "5989" not in report.holdings_analysis

    def test_achievement_not_in_peer_text(self):
        analysis = {
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
                "sortino": 1.9,
                "data_quality": "complete",
            },
            "peer_comparison": {
                "base_fund_id": "519770",
                "rows": [
                    {
                        "fund_id": "519770",
                        "cumulative_return": 4.835,
                        "annualized_return": 0.185,
                        "annual_volatility": 0.1708,
                        "max_drawdown": -0.2901,
                        "sharpe": 1.132,
                        "sortino": 1.9,
                        "nav_basis": "acc",
                    },
                    {
                        "fund_id": "015453",
                        "cumulative_return": 0.5,
                        "annualized_return": 0.1,
                        "annual_volatility": 0.2,
                        "max_drawdown": -0.28,
                        "sharpe": 0.6,
                        "sortino": 0.9,
                        "nav_basis": "acc",
                    },
                ],
            },
        }
        state = _base_state(
            evidence=self._enriched_evidence(),
            analysis=analysis,
        )
        report = SynthesizerNode()(state)["report"]

        # 同类排名已移出对比章节（跨类型原始名次不可比），仅保留同口径指标
        assert "同类排名" not in report.peer_comparison

    def test_comparison_table_has_sortino_column(self):
        analysis = {
            "performance": {
                "fund_id": "519770",
                "cumulative_return": 4.835,
                "annualized_return": 0.185,
                "data_quality": "complete",
            },
            "risk": {"fund_id": "519770", "sharpe": 1.132, "sortino": 1.9, "data_quality": "complete"},
            "peer_comparison": {
                "base_fund_id": "519770",
                "rows": [
                    {
                        "fund_id": "519770",
                        "cumulative_return": 4.835,
                        "annualized_return": 0.185,
                        "annual_volatility": 0.1708,
                        "max_drawdown": -0.2901,
                        "sharpe": 1.132,
                        "sortino": 1.9,
                        "nav_basis": "acc",
                    },
                    {
                        "fund_id": "015453",
                        "cumulative_return": 0.5,
                        "annualized_return": 0.1,
                        "annual_volatility": 0.2,
                        "max_drawdown": -0.28,
                        "sharpe": 0.6,
                        "sortino": 0.9,
                        "nav_basis": "acc",
                    },
                ],
            },
        }
        state = _base_state(
            analysis=analysis,
            research_plan={
                "task_type": "fund_comparison",
                "primary_fund_id": "519770",
                "fund_ids": ["519770", "015453"],
                "notes": [],
            },
        )
        report = SynthesizerNode()(state)["report"]

        # 对比模式：Markdown 表格含 Sortino 列
        assert "| 夏普 | Sortino |" in report.peer_comparison
        assert "1.90" in report.peer_comparison


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


class TestComparisonReport:
    """对比任务一等公民：标题对称、章节逐基金、核心指标表格、持仓对比小节。"""

    def _comparison_state(self, **overrides) -> dict:
        state = {
            "request_id": "req-cmp",
            "user_query": "对比 000001 和 519770 的表现",
            "funds_summary": [
                {
                    "id": "000001",
                    "name": "华夏成长混合",
                    "fund_type": "混合型",
                    "aum": 10.0,
                    "manager_name": "经理甲",
                    "as_of": "2026-09-11T12:00:00",
                    "data_quality": "complete",
                },
                {
                    "id": "519770",
                    "name": "交银优择回报A",
                    "fund_type": "混合型-灵活配置",
                    "aum": 44.16,
                    "manager_name": "周珊珊 高扬",
                    "as_of": "2026-09-11T12:00:00",
                    "data_quality": "complete",
                },
            ],
            "evidence": [
                {"id": EV1, "evidence_type": "fund_data", "source": "s", "value": {"a": 1}},
            ],
            "tool_calls": [],
            "research_plan": {
                "task_type": "fund_comparison",
                "primary_fund_id": "000001",
                "fund_ids": ["000001", "519770"],
                "notes": [],
            },
            "analysis": {
                "performance": {
                    "fund_id": "000001",
                    "period_start": "2022-05-06",
                    "period_end": "2026-09-18",
                    "nav_point_count": 1065,
                    "cumulative_return": 0.53,
                    "annualized_return": 0.10,
                    "data_quality": "complete",
                },
                "risk": {
                    "fund_id": "000001",
                    "annual_volatility": 0.21,
                    "max_drawdown": -0.28,
                    "sharpe": 0.59,
                    "data_quality": "complete",
                },
                "peer_comparison": {
                    "base_fund_id": "000001",
                    "rows": [
                        {
                            "fund_id": "000001",
                            "period_start": "2022-05-06",
                            "period_end": "2026-09-18",
                            "nav_point_count": 1065,
                            "cumulative_return": 0.53,
                            "annualized_return": 0.10,
                            "annual_volatility": 0.21,
                            "max_drawdown": -0.28,
                            "sharpe": 0.59,
                            "nav_basis": "acc",
                        },
                        {
                            "fund_id": "519770",
                            "period_start": "2022-05-06",
                            "period_end": "2026-09-18",
                            "nav_point_count": 1068,
                            "cumulative_return": 3.18,
                            "annualized_return": 0.39,
                            "annual_volatility": 0.26,
                            "max_drawdown": -0.29,
                            "sharpe": 1.43,
                            "nav_basis": "acc",
                        },
                    ],
                    "concentration": [
                        {"fund_id": "000001", "top10_sum": 10.5, "holding_count": 115},
                        {"fund_id": "519770", "top10_sum": 63.03, "holding_count": 55},
                    ],
                    "overlaps": [
                        {
                            "fund_a": "000001",
                            "fund_b": "519770",
                            "overlap_ratio": 0.04,
                            "common_names": ["贵州茅台"],
                        },
                    ],
                },
            },
        }
        state.update(overrides)
        return state

    def test_comparison_report_structure(self):
        report = SynthesizerNode()(self._comparison_state())["report"]

        assert report.title == "FundForge 基金对比报告：000001 华夏成长混合 vs 519770 交银优择回报A"
        assert "本报告对比 2 只基金" in report.executive_summary
        assert "对齐区间 2022-05-06 ~ 2026-09-18" in report.executive_summary
        assert "年化收益领先：519770" in report.executive_summary
        # 业绩/风险章节逐基金对称，无「主体基金」措辞
        assert "主体基金" not in report.performance_analysis
        for fund in ("000001", "519770"):
            assert fund in report.performance_analysis
            assert fund in report.risk_analysis
            assert fund in report.manager_analysis
        # 核心指标表格 + 持仓对比小节
        assert "| 基金 | 类型 | 累计收益 | 年化收益 | 年化波动 | 最大回撤 | 夏普 |" in report.peer_comparison
        assert "持仓集中度（最新报告期前十大合计）" in report.peer_comparison
        assert "重叠 4%" in report.peer_comparison
        assert "共同持仓：贵州茅台" in report.peer_comparison
        assert report.metadata.task_type == "fund_comparison"

    def test_comparison_render_headings(self):
        thesis = _thesis(
            [Claim(id="c1", statement="519770 年化领先", claim_type="performance", evidence_ids=[EV1], strength="strong")]
        )
        report = SynthesizerNode()(
            self._comparison_state(investment_thesis=thesis.model_dump(mode="json"))
        )["report"]
        md = render_markdown(report)

        assert "## 核心指标对比" in md
        assert "## 对比结论" in md
        assert "## 同类对比" not in md
        assert "## 投资论点" not in md

    def test_research_render_headings_unchanged(self):
        thesis = _thesis(
            [Claim(id="c1", statement="长期业绩为正", claim_type="performance", evidence_ids=[EV1], strength="strong")]
        )
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
        state = _base_state(analysis=analysis, investment_thesis=thesis.model_dump(mode="json"))
        state["funds_summary"].append(
            {"id": "000001", "name": "华夏成长混合", "as_of": "2026-09-11T12:00:00", "data_quality": "complete"}
        )
        md = render_markdown(SynthesizerNode()(state)["report"])

        assert "## 同类对比" in md
        assert "## 投资论点" in md
        assert "## 核心指标对比" not in md
        assert "## 对比结论" not in md


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
