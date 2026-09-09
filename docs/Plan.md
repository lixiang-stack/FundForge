**FundForge V1 实现计划**

目标：用最短路径跑通「可验证的基金研究工作流」，再按优先级逐步增强。  
原则：每次迭代短小、可独立运行与测试、人类可 review、严格 MVP。

---

### 总览（优先级从高到低）

| 阶段         | 目标                      | 核心产出                            | 预估工作量 |
| ------------ | ------------------------- | ----------------------------------- | ---------- |
| **Phase 0**  | 项目骨架 + 可运行空流程   | 能跑通的空 Graph                    | 0.5–1 天   |
| **Phase 1**  | 单基金数据获取闭环        | Collector + Fund Tools + 基础 State | 1–2 天     |
| **Phase 2**  | 确定性量化分析            | Analyzer + Analysis Engine          | 1–2 天     |
| **Phase 3**  | 投资论点 + Evidence/Claim | Thesis + 强制绑定                   | 1–2 天     |
| **Phase 4**  | 结构化报告                | Synthesizer + Report                | 1 天       |
| **Phase 5**  | 评估与有限修复            | Evaluator + Repair（max=1）         | 1–2 天     |
| **Phase 6**  | 完整核心 Case             | 端到端「单基金+对比」可运行         | 1–2 天     |
| **Phase 7+** | 增强与工程化              | 成本控制、可观测、评测集、对比/筛选 | 后续       |

---

### Phase 0：项目骨架（可运行空流程）

**目标**：建立最小可运行的 LangGraph 项目结构。

**内容**：
- 项目目录与依赖（LangGraph、LangChain、Pydantic 等）
- 空的 `FundForgeState`
- 空节点：router → planner → synthesizer → END
- 一个最简单的入口脚本，输入任意 query，输出固定字符串报告
- 基础日志

**验收**：
- `python main.py "测试"` 能完整跑完并打印报告
- 无报错，State 可打印

**不包含**：任何真实 Tool、真实 LLM 调用、真实数据。

---

### Phase 1：单基金数据获取闭环（Collector）

**目标**：能根据基金代码/名称获取结构化基金数据。

**内容**：
- 定义 `Fund`、`FundSummary`、`FundPerformance` 等核心 Data Model（含 `data_quality`、`as_of`）
- 实现 2–3 个核心 Fund Tools（基于 akshare）：
  - `get_fund_info`
  - `get_fund_performance`
  - `search_funds`（简单版）
- Collector 节点：调用 Tool → 写入 `funds_summary` + `evidence`
- 简单外部 Store（内存 dict 即可）存放完整数据
- State 只保留摘要 + ID

**验收**：
- 输入基金代码，能返回结构化 `FundSummary` + 至少 1 条 Evidence
- 数据缺失时正确标记 `data_quality`
- 单元测试：Tool 返回格式正确

**独立可测**：不依赖后续节点。

---

### Phase 2：确定性量化分析（Analyzer）

**目标**：对已获取的基金数据计算关键指标，且完全不依赖 LLM。

**内容**：
- Analysis Engine 纯函数：
  - 年化收益、波动率、最大回撤、夏普（简化版）
- Analyzer 节点：读取数据 → 调用纯函数 → 写入 `analysis` + calculation 类型 Evidence
- 简单 Peer 对比占位（先支持手动传入 1–2 只对比基金）

**验收**：
- 给定净值序列，计算结果可复现、可单测
- 结果正确写入 State 和 Evidence
- 不调用任何 LLM

**独立可测**：输入 mock 数据即可验证。

---

### Phase 3：投资论点 + Evidence/Claim 强制绑定（Thesis）

**目标**：基于数据和计算结果生成带证据的投资判断。

**内容**：
- 定义 `Evidence`、`Claim`、`InvestmentThesis`
- Thesis 节点（调用 LLM）：
  - 输入：funds_summary + analysis + evidence
  - 输出：必须包含 `claims`（每个 claim 绑定 `evidence_ids`）+ `suitability` + `confidence` + `data_gaps`
- 简单 Prompt + 结构化输出（Pydantic）
- 校验：重要结论没有 evidence_ids 则失败

**验收**：
- 输出的 Thesis 中每个关键 Claim 都有对应 Evidence
- 能回答「是否适合长期持有」并给出置信度
- 可单测：mock 输入 → 检查 Claim 绑定是否完整

---

### Phase 4：结构化报告（Synthesizer）

**目标**：把前面结果组装成标准报告。

**内容**：
- 定义 `Report` 结构
- Synthesizer 节点：组装 executive_summary、performance、risk、thesis、key_claims、data_gaps、强制免责声明
- 简单模板或轻量 LLM 生成文字部分
- 输出完整 Report 对象（可转 Markdown/JSON）

**验收**：
- 报告结构完整，包含强制风险提示
- 关键结论可追溯到 Claim/Evidence
- 端到端从 Collector → Analyzer → Thesis → Synthesizer 可跑通（暂无 Evaluator）

---

### Phase 5：评估与有限修复（Evaluator + Repair）

**目标**：增加验证环节，最多修复 1 次。

**内容**：
- Evaluator 节点：检查 Factuality、Evidence Coverage、Completeness、Risk、Question Alignment、Data Quality
- 输出 `EvaluationResult`（pass/fail + issues）
- Repair 节点：只执行允许的 5 类动作，max=1
- 失败后强制进入 Synthesizer，并在报告中标注证据不足

**验收**：
- 故意制造缺失 Evidence 的 Thesis，Evaluator 能检出并触发 Repair
- 超过 1 次后不再循环
- 最终报告正确反映评估结果

---

### Phase 6：完整核心 Case 跑通

**目标**：端到端支持文档中的最小闭环。

**内容**：
- 支持「分析基金 A + 与 B、C 对比」
- Planner 能生成包含对比基金的 research_plan
- 补全必要 Tool（get_fund_holdings、get_fund_manager 等，按需）
- 简单 Researcher 节点（可先 mock 或极简 web_search）
- 端到端测试脚本 + 基础日志与 token 统计

**验收**：
- 输入文档中的标准问题，完整跑完并输出结构化报告
- 所有重要结论有 Evidence
- 成本与调用次数可统计
- 人类可 review 完整 Trace

---

### Phase 7+（后续迭代，按优先级）

1. **成本控制与可观测性**：CostLimits、Langfuse 接入、详细 ToolCallRecord
2. **评测集 v0.1**：20 个 Fund Research Case + 简单回归脚本
3. **Fund Comparison 完整支持**
4. **数据质量与降级策略增强**
5. **Fund Screening / Portfolio Analysis**（更后）

---

### 执行纪律（必须遵守）

- 每个 Phase 结束必须有：可运行代码 + 至少 1 个验收用例 + 简短 Review 记录
- 不允许提前实现后续 Phase 的功能
- 任何时候优先保证「当前 Phase 可独立验证」
- LLM 调用从 Phase 3 才开始引入，之前全部用 mock 或确定性逻辑
- 每次提交只做当前 Phase，方便回滚与 review

---