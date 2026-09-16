**FundForge V1 实现计划**

目标：用最短路径跑通「可验证的基金研究工作流」，再按优先级逐步增强。  
原则：每次迭代短小、可独立运行与测试、人类可 review、严格 MVP。

---

### 总览（优先级从高到低）

| 阶段        | 目标                      | 核心产出                            | 预估工作量 |
| ----------- | ------------------------- | ----------------------------------- | ---------- |
| **Phase 0** | 项目骨架 + 可运行空流程   | 能跑通的空 Graph                    | 0.5–1 天   |
| **Phase 1** | 单基金数据获取闭环        | Collector + Fund Tools + 基础 State | 1–2 天     |
| **Phase 2** | 确定性量化分析            | Analyzer + Analysis Engine          | 1–2 天     |
| **Phase 3** | 投资论点 + Evidence/Claim | Thesis + 强制绑定                   | 1–2 天     |
| **Phase 4** | 结构化报告                | Synthesizer + Report                | 1 天       |
| **Phase 5** | 评估与有限修复            | Evaluator + Repair（max=1）         | 1–2 天     |
| **Phase 6** | 完整核心 Case             | 端到端「单基金+对比」可运行         | 1–2 天     |
| **Phase 7** | 数据质量与失败路径硬化    | data_quality 全链路 + 失败注入测试  | 1–2 天     |
| **Phase 8** | Claim-Evidence 运行时强制 | 绑定硬约束 + Evaluator 强化         | 1–2 天     |
| **Phase 9** | 可观测性基础              | 完整 Trace 可持久化、可查询         | 1–2 天     |

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

### Phase 7：数据质量与失败路径硬化（最高优先）

**目标**：让「数据缺失 / 接口失败 / 部分可用」在全链路可感知、可降级、可测试。

**内容**：
- Collector：明确区分「业务正常空」（债基无股票持仓）vs「数据源失败 / 超时 / 字段缺失」
- 所有进入 State / Evidence 的对象强制带准确的 `data_quality`
- Analyzer：计算前检查必要序列完整性，不完整时写入 `data_quality_issues` 并跳过或降权相关指标
- Thesis：强制把 `data_quality_issues` 映射到 `data_gaps`，并降低相关 Claim strength
- 增加 3–5 个「强制失败注入」测试（mock Tool 返回 partial/stale/missing）

**验收**：
- 人为制造数据缺失时，最终报告明确披露 gaps，且不产生虚假强结论
- 相关单元测试 + graph 测试全部通过
- 人类可从 Trace 直接看到 data_quality 流转

**不包含**：真实外部研究、费率计算。

---

### Phase 8：Claim-Evidence 运行时强制 + Evaluator 强化

**目标**：把「重要结论必须有 Evidence」从约定变成运行时硬约束。

**内容**：
- Thesis 输出后增加轻量后处理：无 `evidence_ids` 的 Claim 自动降级或移入 `data_gaps`
- Evaluator 增加硬指标：
  - 重要 Claim 的 Evidence 覆盖率下限
  - `data_gaps` 是否被正确披露
- 把「绑定失败」作为可触发 Repair 的明确 issue 类型（仍遵守 `max_iteration=1`）
- 固化 Phase 6 标准三基金 Case 为回归基线（预期 Claim 数量、覆盖率下限）

**验收**：
- 故意生成无 Evidence 的 Claim 时，系统能检测并处理
- 回归基线稳定通过
- 报告中关键结论均可追溯

---

### Phase 9：可观测性基础

**目标**：让每次运行的完整 Trace（节点、Tool、Token、Evidence、Evaluation）可持久化、可查询。

**内容**：
- 接入 Langfuse（或同等轻量方案），记录：
  - 每个节点输入/输出摘要
  - `ToolCallRecord`
  - `TokenUsage`
  - Evaluation 结果
  - 最终 Report 元数据
- `main.py` / 入口支持输出 Trace ID
- 保持现有控制台 Trace 不变（兼容人类 review）

**验收**：
- 一次完整运行后，能在可观测平台看到完整链路
- 不影响现有功能与测试
- 可按 `request_id` 回溯

**不包含**：费率表与成本熔断（成本熔断仍依赖现有 `max_iteration`）。

---

### Phase 10：评测集 v0.1 扩展与自动化回归

**目标** 把当前回归基线扩展成可维护的质量基准，防止后续改动回退。

**内容**：
- 在现有回归基线基础上扩充到 15–20 个 Case（覆盖：正常单基金、三基金对比、数据缺失、意图边界、空持仓正常场景等）
- 每个 Case 明确检查点：Evidence 覆盖率、data_gaps 披露、suitability 存在、免责声明、关键 Claim 绑定
- 自动化回归脚本（本地一键跑，输出清晰 pass/fail + 差异报告）
- 与节点输出契约检查、真实数据集成测试整合

**验收**：

- 回归脚本一次跑完所有 Case，核心 Case 稳定通过
- 新增 Case 有简短说明文档
- CI 或本地可方便执行
---

### 执行纪律（必须遵守）

- 每个 Phase 结束必须有：可运行代码 + 至少 1 个验收用例 + 简短 Review 记录
- 不允许提前实现后续 Phase 的功能
- 任何时候优先保证「当前 Phase 可独立验证」
- LLM 调用从 Phase 3 才开始引入，之前全部用 mock 或确定性逻辑
- 每次提交只做当前 Phase，方便回滚与 review

---