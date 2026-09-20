# 基金对比报告一等公民化（fund_comparison 差异化报告结构）

## 背景与根因

query「对比 015453 和 519770 的表现」已被 router 正确判为 `fund_comparison`（R3），thesis 也产出了对比性结论，但最终报告仍是单基金模板：

1. **报告层硬编码 primary**：`agent/nodes/synthesizer.py` L60 `primary = summaries[0]` 决定标题、业绩分析、风险分析、基金经理四处主体；`task_type` 在 synthesizer 完全未被读取。
2. **数据层不对称**：`agent/domain/analysis.py` 的 `AnalysisResult.performance/risk` 只有主基金；多基金指标只在 `PeerComparison.rows`，且缺累计收益、区间起止、净值点数。
3. **evaluator 只查 peer 表存在性**（`agent/nodes/evaluator.py` L120-127），不检查报告是否对称、是否形成跨基金对比结论。
4. **router 缺口**：「A 和 B 哪个更适合长期持有」含分析词（适合/持有）但无对比关键词命中 → R2 误落 `fund_research`（验收场景）。
5. **持仓对比维度缺失**：collector 已采集持仓，但 analyzer 从不读取，重叠度/集中度无计算。

## 方案总览

同一 graph、同一节点复用，按 `task_type == FUND_COMPARISON` 在 analyzer / synthesizer / report 渲染层分支。单基金 research（含 R1「分析 X 并与 Y 比较」）行为保持不变。**报告主体（research）逻辑零改动。**

## 改动清单（按实施顺序）

### 1. 意图关键词加固 — `agent/domain/task_type.py`

- `COMPARISON_INTENT_KEYWORDS` 增加 `"哪个更"`、`"哪一个更"`（覆盖「哪个更适合长期持有」「哪一个更好」）。
- 效果：「A 和 B 哪个更适合长期持有」→ 对比词 + 分析词、无强主题词、≥2 代码 → R4 → `fund_comparison` @0.6；R1 用例（「分析 519770 … 并与 … 比较」，含强主题词「分析」）不受影响。
- evaluator 的 `peer_expected` 共用此表，自动对齐。

### 2. 域模型扩展 — `agent/domain/analysis.py`

- `PeerMetricsRow` 增加字段（均带默认值，不破坏现有构造）：`period_start`、`period_end`、`nav_point_count`、`cumulative_return`、`nav_basis`。
- 新增 `FundConcentration`（fund_id / top10_sum / holding_count）与 `HoldingsOverlap`（fund_a / fund_b / overlap_ratio / common_names 最多 10 条）。
- `PeerComparison` 增加 `concentration: list[FundConcentration] = []`、`overlaps: list[HoldingsOverlap] = []`。

### 3. 分析引擎新增确定性计算 — `agent/analysis/engine.py`

复用 `agent/domain/fund.py` 的 `latest_report_period` / `top_holdings`：

- `top_concentration(holdings) -> float | None`：最新报告期前十大 `hold_ratio` 合计（%）；无有效数据返回 None。
- `holdings_overlap(holdings_a, holdings_b) -> (float | None, list[str])`：两基金最新报告期持仓 `stock_name` 集合的 Jaccard 重叠率 + 共同个股名（截断 10）。

### 4. Analyzer 接线 — `agent/nodes/analyzer.py`

- **仅当 `plan.task_type == FUND_COMPARISON` 且 `len(fund_ids) > 1`** 时：
  - `PeerMetricsRow` 从 `metrics_by_fund` 填充新字段；
  - 读 `store.get_holdings(fid)` 计算各基金集中度 + 两两重叠（`itertools.combinations`），写入 `PeerComparison.concentration / overlaps`；
  - 每基金 1 条集中度 + 每组合 1 条重叠的 `CALCULATION` Evidence（thesis 可引用）。
- **关键**：门控用 task_type 而非「多基金」，否则 R1 三基金 research case 的 `evidence_count==12` 精确断言会被打破（`agent/eval/cases.py` `research_standard_three_fund`）。
- 持仓缺失 → 对应字段 None，不编造。

### 5. Synthesizer 对比分支 — `agent/nodes/synthesizer.py`

检测：`plan.task_type == FUND_COMPARISON`（research 分支全部走原路径）。

- **标题**：`FundForge 基金对比报告：{id} {name} vs {id} {name}（vs …）`，标签按 `summaries` 全量连接。
- **摘要**（`_executive_summary` 对比变体）：对比 N 只基金 + 对齐区间 + 各基金年化收益并列 + 确定性领先句（年化收益最高者）+ thesis.suitability。
- **业绩分析**：逐基金一行（区间 / 净值点 / 累计 / 年化），数据来自增强后的 peer rows；去掉「主体基金」措辞。
- **风险分析**：逐基金一行（波动 / 回撤 / 夏普）。
- **同类对比 → 对比表格**：`_peer_text` 对比模式改输出 Markdown 表（列：基金 / 类型 / 累计收益 / 年化收益 / 年化波动 / 最大回撤 / 夏普）+ 对齐口径注 + 持仓小节（各基金前十大集中度合计、两两重叠率与共同个股；数据 None 则省略该行）。
- **基金经理**：逐基金一行。
- metadata 记录 `task_type`。

### 6. 报告模型 — `agent/domain/report.py`

- `ReportMetadata` 增加 `task_type: str | None = None`。
- `render_markdown`：对比模式下 peer 章节标题 `## 核心指标对比`（原 `## 同类对比`）、thesis 章节标题 `## 对比结论`（原 `## 投资论点`）；其余章节与顺序不变。

### 7. Evaluator 对比对齐检查 — `agent/nodes/evaluator.py`

在 question_alignment 中，对比任务追加一条检查：

- **跨基金对比 claim**：至少 1 个 claim 绑定的 Evidence 覆盖 ≥2 只不同基金（evidence → fund 映射取 `value["fund_id"]`，回退解析 `raw_ref` 末段）。不满足 → alignment issue「对比任务：所有 claim 仅绑定单一基金证据，未形成跨基金对比结论」。
- 保持 record-only（alignment 不触发 FAIL），与 V1 repair 语义一致。

### 8. 评测集 — `agent/eval/`

- `fakes.py`：`DeterministicThesisProvider` 的 claim 改绑全部 `ev_ids`（原 `ev_ids[:1]`），使对比 case 能通过跨基金 claim 检查；单基金 case 不受影响（id 均真实存在）。`BadBindingThesisProvider` 不动。
- `checks.py` 注册表新增 3 个检查：
  - `comparison_title_covers_funds`：case 期望的每只基金代码都出现在 `report.title`；
  - `comparative_claim_present`：≥1 claim 绑定证据覆盖 ≥2 只不同基金（口径与 evaluator 一致）；
  - `performance_sections_symmetric`：`report.performance_analysis` 与 `risk_analysis` 包含全部基金代码。
- `cases.py`：
  - `comparison_pure_intent`、`comparison_three_fund` 追加上述 3 检查；
  - 新增 offline case `comparison_suitability_intent`：query「015453 和 519770 哪个更适合长期持有」，断言 `task_type_in=[fund_comparison]` + 3 个新检查 + `has_comparison_section` / `peer_mentioned_in_report` / `has_suitability` 等（防 R2 误判回归）；
  - live case 不加新检查（真实 LLM 不保证跨基金绑定，避免质量门抖动）。

### 9. 单元测试

- `agent/tests/test_intent.py`：新关键词用例（R4 命中）+ R1 回归保持。
- `agent/tests/test_analysis.py`：`top_concentration` / `holdings_overlap` 手算期望。
- `agent/tests/test_analyzer.py`：对比模式 rows 新字段、集中度/重叠填充与新 Evidence；单基金 research 不产生持仓 Evidence。
- `agent/tests/test_report.py`：对比模式标题/章节对称/表格/`核心指标对比` 与 `对比结论` 标题；原 research 断言（含「主体基金」文案）保持。
- `agent/tests/test_graph.py`：对比 e2e 报告标题覆盖两基金、evaluation 无新 alignment issue。
- `agent/tests/test_eval_checks.py`：3 个新检查的通过与失败用例。

### 10. 文档

- `agent/docs/TechnicalContract.md`：§11 Report（metadata.task_type、对比报告结构分支）、PeerComparison 扩展字段与新引擎函数的对应小节补一句（合同级变更，中文）。
- 不动 README / Go 侧 / collector（无跨语言契约变化）。

## 关键设计决策

- **不新增 task_type、不建独立 ComparisonReport 模型**：同一 `Report` 内按 task_type 分支，最小改动。
- **primary/peer 机制保留**：`base_fund_id` 仍是对比表内部基准，报告呈现层对称化，不改 planner 位置约定。
- **持仓对比门控在 task_type**：保住 `research_standard_three_fund` 的 evidence 精确计数基线。
- **不做**（明确出范围）：无代码对比 query（「帮我对比这三只」仍走引导，现状）；planner 不消费 router 输出的现状（避免无关重构）；repair 新增对比修复动作；FUND_SCREENING / PORTFOLIO_ANALYSIS。

## 验证

```bash
# 分步：每步跑对应测试文件（见各条）
uv --directory agent run pytest tests/test_intent.py tests/test_nodes.py -q                      # 步骤 1
uv --directory agent run pytest tests/test_analysis.py -q                                        # 步骤 2-3
uv --directory agent run pytest tests/test_analyzer.py tests/test_alignment.py -q                # 步骤 4
uv --directory agent run pytest tests/test_report.py -q                                          # 步骤 5-6
uv --directory agent run pytest -q                                                               # 全量回归（步骤 7-9 后）

# 评测集（offline 全绿为提交门槛）
uv --directory agent run python -m eval
uv --directory agent run pytest tests/test_eval_suite.py tests/test_eval_checks.py -q
```

手工端到端（需 `docker compose up -d collector` + LLM env）：

1. `uv --directory agent run python main.py "对比 015453 和 519770 的表现"`
   → 报告标题含两只基金、业绩/风险/经理章节逐基金、核心指标对比为表格、含持仓集中度与重叠小节。
2. `uv --directory agent run python main.py "015453 和 519770 哪个更适合长期持有"`
   → task_type=fund_comparison（R4），产出对比结构报告。
3. `uv --directory agent run python main.py "分析基金 519770"`
   → 单基金报告与现状完全一致（回归确认）。
