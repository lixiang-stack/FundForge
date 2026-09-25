"""Synthesizer / Report 单元测试（Phase 4 验收：结构完整 + 可追溯 + 强制免责）。"""

from domain.thesis import Claim
from domain.report import render_markdown
from nodes.synthesizer import SynthesizerNode
from tests.test_thesis import EV1, _thesis


def _assert_tables_wellformed(text: str) -> None:
    """渲染出的每个 Markdown 表格：所有行列数必须一致。

    分隔行列数少于表头时，渲染器按分隔行定列数导致表格错乱（回归防护）。
    """
    for block in (b for b in text.split("\n\n") if b.lstrip().startswith("|")):
        counts = {line.count("|") for line in block.splitlines() if line.lstrip().startswith("|")}
        assert len(counts) == 1, f"表格列数不一致 {counts}：\n{block}"


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

    def test_empty_funds_with_evidence_does_not_crash(self):
        """采集全失败（summaries 为空但仍有 evidence）不崩溃，事实小节整节省略。

        回归：单基金分支曾直接取 summaries[0]。
        """
        evidence = [
            {
                "id": "ev-fee0000001",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "519770", "management_fee_rate": 1.0, "custodian_fee_rate": 0.15},
            },
            {
                "id": "ev-hold000001",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "519770", "top_holdings": [{"stock_name": "贵州茅台", "hold_ratio": 3.12}]},
            },
        ]
        state = _base_state(funds_summary=[], evidence=evidence)
        report = SynthesizerNode()(state)["report"]

        assert report.metadata.fund_count == 0
        assert report.holdings_analysis is None
        assert report.cost_and_rating is None
        assert "未能采集到基金数据" in report.executive_summary

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
        # 单基金：项目/数值两列表 + 周期/排名两列表
        assert "| 项目 | 数值 |" in report.cost_and_rating
        assert "| 管理费/年 | 1.00% |" in report.cost_and_rating
        assert "| 托管费/年 | 0.15% |" in report.cost_and_rating
        assert "| 销售服务费/年 | 0.00% |" in report.cost_and_rating
        assert "| 五星数 | 2 |" in report.cost_and_rating
        assert "| 上海证券 | 4星 |" in report.cost_and_rating
        assert "| 招商证券 | 5星 |" in report.cost_and_rating
        assert "| 济安金信 | 4星 |" in report.cost_and_rating
        assert "| 晨星 | 5星 |" in report.cost_and_rating
        # 同类排名：池内分位 + 原始名次，附跨类型口径提示
        assert "| 成立以来 | 前 28.8%（308/1070） |" in report.cost_and_rating
        assert "跨类型基金之间不可直接比较" in report.cost_and_rating
        _assert_tables_wellformed(report.cost_and_rating)
        assert "## 费率、评级与同类排名" in render_markdown(report)

    def test_cost_and_rating_absent_without_evidence(self):
        report = SynthesizerNode()(_base_state())["report"]
        assert report.cost_and_rating is None
        assert "费率与评级" not in render_markdown(report)

    def test_cost_rating_table_for_multi_fund(self):
        """多基金：费率/评级成表（行 = 基金）+ 同类排名按周期对照矩阵。"""
        evidence = [
            {
                "id": "ev-fee-1",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "519770", "management_fee_rate": 1.0, "custodian_fee_rate": 0.15, "service_fee_rate": 0.0},
            },
            {
                "id": "ev-fee-2",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "000001", "management_fee_rate": 0.8, "custodian_fee_rate": 0.2},
            },
            {
                "id": "ev-rat-1",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "519770", "five_star_count": 2, "rating_sh": 4.0, "rating_zs": 5.0, "rating_ja": 4.0, "rating_mx": 5.0},
            },
            {
                "id": "ev-rat-2",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {"fund_id": "000001", "five_star_count": 1, "rating_sh": 5.0, "rating_zs": 3.0, "rating_ja": 4.0, "rating_mx": 4.0},
            },
            {
                "id": "ev-ach-1",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {
                    "fund_id": "519770",
                    "achievement": [
                        {"performance_type": "年度业绩", "period": "成立以来", "return_rate": 53.44, "max_drawdown": 27.6, "category_rank": "308/1070"},
                        {"performance_type": "年度业绩", "period": "今年以来", "return_rate": 6.94, "max_drawdown": 16.45, "category_rank": "309/1070"},
                    ],
                },
            },
            {
                "id": "ev-ach-2",
                "evidence_type": "fund_data",
                "source": "s",
                "value": {
                    "fund_id": "000001",
                    "achievement": [
                        {"performance_type": "年度业绩", "period": "成立以来", "return_rate": 84.8, "max_drawdown": 41.43, "category_rank": "134/1070"},
                    ],
                },
            },
        ]
        state = _base_state(evidence=evidence)
        state["funds_summary"].append(
            {"id": "000001", "name": "华夏成长混合", "as_of": "2026-09-11T12:00:00", "data_quality": "complete"}
        )
        report = SynthesizerNode()(state)["report"]
        text = report.cost_and_rating

        assert "| 基金 | 管理费/年 | 托管费/年 | 销售服务费/年 | 五星数 | 上海证券 | 招商证券 | 济安金信 | 晨星 |" in text
        assert "| 519770 | 1.00% | 0.15% | 0.00% | 2 | 4星 | 5星 | 4星 | 5星 |" in text
        assert "| 000001 | 0.80% | 0.20% | — | 1 | 5星 | 3星 | 4星 | 4星 |" in text
        assert "同类排名（池内分位；跨类型基金之间不可直接比较）：" in text
        assert "| 成立以来 | 前 28.8%（308/1070） | 前 12.5%（134/1070） |" in text
        assert "| 今年以来 | 前 28.9%（309/1070） | — |" in text
        # 费率/评级表 9 列，分隔行必须同为 9 列
        assert "| --- | --- | --- | --- | --- | --- | --- | --- | --- |" in text
        _assert_tables_wellformed(text)
        assert "## 费率、评级与同类排名" in render_markdown(report)

    def test_holdings_industry_and_allocation_lines(self):
        state = _base_state(evidence=self._enriched_evidence())
        report = SynthesizerNode()(state)["report"]

        assert "| 行业前五（2026-06-30） | 制造业 68.96%、金融业 6.78% |" in report.holdings_analysis
        assert "| 资产配置 | 股票 94.18%、现金 5.46% |" in report.holdings_analysis

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

        assert "| 市场分布（占披露持仓净值比） | A股 59.89%、港股 40.53% |" in report.holdings_analysis
        assert "5989" not in report.holdings_analysis

    def test_performance_text_trailing_returns(self):
        """单基金业绩分析为指标矩阵，区间收益缺失窗口不编造。"""
        analysis = _base_state()["analysis"] | {
            "performance": {
                **_base_state()["analysis"]["performance"],
                "trailing_returns": {"1m": 0.012, "3m": None, "6m": 0.056, "1y": 0.21},
            }
        }
        report = SynthesizerNode()(_base_state(analysis=analysis))["report"]
        perf = report.performance_analysis

        assert "| 指标 | 数值 |" in perf
        assert "| 近1月 | 1.20% |" in perf
        assert "| 近6月 | 5.60% |" in perf
        assert "| 近1年 | 21.00% |" in perf
        assert "| 近3月 |" not in perf                      # 数据缺失的行整行省略
        _assert_tables_wellformed(perf)

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
        text = report.holdings_analysis

        assert text is not None
        # 单基金：前十大明细表 + 持仓结构表
        assert "| 排名 | 股票 | 占净值比 |" in text
        assert "| 1 | 贵州茅台 | 3.12% |" in text
        assert "| 2 | 宁德时代 | 2.85% |" in text
        assert "| 报告期 | 2026年2季度股票投资明细 |" in text
        _assert_tables_wellformed(text)
        assert "## 持仓概览（最新报告期前十大）" in render_markdown(report)

    def test_holdings_overview_table_for_multi_fund(self):
        """多基金：前十大按排名对齐成表 + 持仓结构矩阵（列 = 基金代码）。"""
        evidence = [
            {
                "id": "ev-h1",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/519770/holdings/stock",
                "value": {
                    "fund_id": "519770",
                    "latest_report_period": "2026年2季度股票投资明细",
                    "top_holdings": [
                        {"stock_name": "贵州茅台", "hold_ratio": 3.12},
                        {"stock_name": "宁德时代", "hold_ratio": 2.85},
                    ],
                },
            },
            {
                "id": "ev-h2",
                "evidence_type": "fund_data",
                "source": "collector:/api/funds/000001/holdings/stock",
                "value": {
                    "fund_id": "000001",
                    "latest_report_period": "2026年2季度股票投资明细",
                    "top_holdings": [
                        {"stock_name": "中际旭创", "hold_ratio": 3.56},
                        {"stock_name": "宁德时代", "hold_ratio": 3.37},
                        {"stock_name": "新易盛", "hold_ratio": 2.41},
                    ],
                },
            },
        ]
        analysis = _base_state()["analysis"] | {
            "holdings_metrics": [
                {
                    "fund_id": "519770",
                    "top10_sum": 42.36,
                    "holding_count": 83,
                    "market_split": {"a_share_ratio": 59.89},
                },
                {
                    "fund_id": "000001",
                    "top10_sum": 30.0,
                    "holding_count": 90,
                    "market_split": {"a_share_ratio": 73.33},
                },
            ]
        }
        state = _base_state(evidence=evidence, analysis=analysis)
        state["funds_summary"].append(
            {"id": "000001", "name": "华夏成长混合", "as_of": "2026-09-11T12:00:00", "data_quality": "complete"}
        )
        report = SynthesizerNode()(state)["report"]
        text = report.holdings_analysis

        assert "| 排名 | 519770 | 000001 |" in text
        assert "| 1 | 贵州茅台 3.12% | 中际旭创 3.56% |" in text
        assert "| 3 | — | 新易盛 2.41% |" in text          # 持仓数不足补 —
        assert "| 报告期 | 2026年2季度股票投资明细 | 2026年2季度股票投资明细 |" in text
        assert "| 前十大合计 | 42.36%（83 只） | 30.00%（90 只） |" in text
        assert "| 市场分布（占披露持仓净值比） | A股 59.89% | A股 73.33% |" in text
        _assert_tables_wellformed(text)
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
        # 摘要逐维度分段：对齐区间 / 确定性量化分析各自独立成段
        assert "对齐区间 2022-05-06 ~ 2026-09-18。\n\n确定性量化分析：" in report.executive_summary
        # 对比报告不设重复章节：业绩/风险/经理由核心指标对比表承载
        assert report.performance_analysis == ""
        assert report.risk_analysis == ""
        assert report.manager_analysis is None
        # 核心指标总览表（单一来源，含超额列）+ 持仓重叠要点行
        assert "| 基金 | 累计收益 | 年化收益 | 年化波动 | 最大回撤 | 夏普 | Sortino | 相对基准超额 |" in report.peer_comparison
        assert "对齐区间 2022-05-06 ~ 2026-09-18（全部基金同口径）。" in report.peer_comparison
        assert (
            "- 持仓重叠（最新报告期，按股票名）：000001 华夏成长混合 与 "
            "519770 交银优择回报A 重叠 4%，共同持仓：贵州茅台" in report.peer_comparison
        )
        for fund in ("000001", "519770"):
            assert fund in report.peer_comparison
        # 差异总结表：各基金取值分列 + 更优者与差距；分隔行列数与表头一致
        assert "| 维度 | 000001 | 519770 | 表现更优 | 差距 |" in report.comparison_differences
        assert "| --- | --- | --- | --- | --- |" in report.comparison_differences
        assert "| 年化收益 | 10.00% | 39.00% | 519770 | 29.00 个百分点 |" in report.comparison_differences
        _assert_tables_wellformed(report.comparison_differences)
        assert "519770" in report.recommendation
        assert report.metadata.task_type == "fund_comparison"
        # 多基金概览渲染为表格
        md = render_markdown(report)
        assert "| 代码 | 名称 | 类型 | 规模 | 基金经理 | 数据质量 |" in md
        _assert_tables_wellformed(md)

    def test_comparison_differences_table_dimensions(self):
        report = SynthesizerNode()(self._comparison_state())["report"]
        diffs = report.comparison_differences

        # 收益（大者优）/ 波动（小者优）/ 回撤（浅者优）/ 夏普（大者优）四维度齐全
        for dim in ("年化收益", "年化波动", "最大回撤", "夏普比率"):
            assert f"| {dim} |" in diffs
        # 每个维度同时列出两只基金的取值
        assert "| 年化波动 | 21.00% | 26.00% | 000001 | 5.00 个百分点 |" in diffs
        assert "| 最大回撤 | -28.00% | -29.00% | 000001 | 1.00 个百分点 |" in diffs
        assert "| 夏普比率 | 0.59 | 1.43 | 519770 | 0.84 |" in diffs
        assert "0.84" in diffs                     # 夏普差距 1.43 − 0.59

    def test_comparison_trailing_returns_table(self):
        state = self._comparison_state()
        rows = state["analysis"]["peer_comparison"]["rows"]
        rows[0]["trailing_returns"] = {"1m": 0.012, "3m": -0.034, "6m": 0.056, "1y": 0.21}
        rows[1]["trailing_returns"] = {"1m": -0.005, "3m": 0.048, "6m": None, "1y": 0.15}
        report = SynthesizerNode()(state)["report"]

        assert (
            "区间收益（按净值计算；近1月≈21 个交易日、近3月≈63、近6月≈126、近1年≈252）："
            in report.peer_comparison
        )
        assert "| 基金 | 近1月 | 近3月 | 近6月 | 近1年 |" in report.peer_comparison
        assert "| 000001 华夏成长混合 | 1.20% | -3.40% | 5.60% | 21.00% |" in report.peer_comparison
        assert "| 519770 交银优择回报A | -0.50% | 4.80% | — | 15.00% |" in report.peer_comparison
        _assert_tables_wellformed(report.peer_comparison)

    def test_comparison_trailing_returns_omitted_when_missing(self):
        # fixture 无区间收益 → 表格整节省略（不编造）
        report = SynthesizerNode()(self._comparison_state())["report"]
        assert "区间收益" not in report.peer_comparison

    def test_comparison_recommendation_split_leaders(self):
        state = self._comparison_state()
        rows = state["analysis"]["peer_comparison"]["rows"]
        rows[0]["sharpe"] = 2.0                    # 000001 夏普最高，收益仍由 519770 领先
        rows[1]["sharpe"] = 0.5
        report = SynthesizerNode()(state)["report"]

        assert "由不同基金领先" in report.recommendation
        assert "000001" in report.recommendation and "519770" in report.recommendation
        assert "确定性倾向" in report.recommendation

    def test_comparison_recommendation_does_not_repeat_thesis(self):
        # thesis.suitability 已在「对比结论」呈现，推荐倾向不重复引用
        thesis = _thesis(
            [Claim(id="c1", statement="519770 年化领先", claim_type="peer", evidence_ids=[EV1], strength="strong")]
        )
        report = SynthesizerNode()(
            self._comparison_state(investment_thesis=thesis.model_dump(mode="json"))
        )["report"]

        assert thesis.suitability not in report.recommendation
        assert "不构成投资建议" in report.recommendation

    def test_comparison_render_headings(self):
        thesis = _thesis(
            [Claim(id="c1", statement="519770 年化领先", claim_type="performance", evidence_ids=[EV1], strength="strong")]
        )
        report = SynthesizerNode()(
            self._comparison_state(investment_thesis=thesis.model_dump(mode="json"))
        )["report"]
        md = render_markdown(report)

        assert "## 核心指标对比" in md
        assert "## 差异总结" in md
        assert "## 推荐倾向" in md
        assert "## 对比结论" in md
        assert "## 同类对比" not in md
        assert "## 投资论点" not in md

    def test_research_report_has_no_comparison_only_sections(self):
        report = SynthesizerNode()(_base_state())["report"]
        md = render_markdown(report)

        assert report.comparison_differences is None
        assert report.recommendation is None
        assert "## 差异总结" not in md
        assert "## 推荐倾向" not in md

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
        assert "## 差异总结" not in md
        assert "## 推荐倾向" not in md


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
