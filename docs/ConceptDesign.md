# FundForge V1

> **An AI Agent for Fund Investment Research and Portfolio Decision Support.**

## 1. 项目定位

FundForge 是一个基于 **LLM + LangGraph + LangChain Tools** 的基金投资研究 Agent。

核心目标不是预测基金涨跌，而是：

> **让 Agent 像一个研究员一样完成基金数据获取、市场研究、量化分析、风险分析和投资判断，并提供可追溯的证据。**

核心闭环：

```text
Investment Question
        ↓
    Research
        ↓
   Data / Tools
        ↓
    Analysis
        ↓
   Risk / Evidence
        ↓
 Investment Thesis
        ↓
 Recommendation
        ↓
    Evaluation
```

---

# 2. 核心能力

V1 聚焦 4 类任务：

### Fund Research

```text
分析某只基金
```

### Fund Comparison

```text
比较多只基金
```

### Fund Screening

```text
按照条件筛选基金
```

### Portfolio Analysis

```text
分析基金组合的收益、风险和集中度
```

其中 **Fund Research 是 V1 的核心能力**，其他能力围绕它逐步扩展。

---

# 3. 核心架构

```text
                        User
                          │
                          ▼
                       Router
                          │
                          ▼
                       Planner
                          │
                          ▼
                    LangGraph
                 Agent Workflow
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     Fund Tools       Market Tools    Research Tools
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                    Analysis Engine
                          │
                          ▼
                       Evaluator
                          │
                          ▼
                     Synthesizer
                          │
                          ▼
                  Investment Report
```

---

# 4. Framework 职责边界

这是 FundForge 的核心设计原则。

## LangGraph：负责「怎么执行」

使用 LangGraph 管理：

* State
* Nodes
* Edges
* Conditional Routing
* Retry / Loop
* Checkpoint

例如：

```text
Understand
    ↓
Plan
    ↓
Research
    ↓
Analyze
    ↓
Evaluate
    ↓
Pass ─────→ Report
    │
    └─ Fail → Repair → Evaluate
```

---

## LangChain Tools：负责「能做什么」

将外部能力封装成 Tools：

```text
Fund Tools
├── search_funds
├── get_fund_info
├── get_fund_performance
├── get_fund_holdings
└── get_fund_manager

Market Tools
├── get_market_data
├── get_index_data
└── get_sector_data

Research Tools
├── web_search
└── fetch_document
```

原则：

> **Tool 提供事实和能力，LLM 负责推理。**

---

## FundForge Core：负责「为什么这么做」

不交给 Framework：

```text
Fund Data Model
Analysis Engine
Investment Logic
Evidence Model
Evaluation
Cost Control
Report Generation
```

因此：

```text
LangGraph
    = Runtime

LangChain Tools
    = Capability

FundForge
    = Domain Intelligence
```

---

# 5. Agent 不采用「万能 ReAct Agent」

不采用：

```text
User
 ↓
万能 Agent
 ↓
LLM 自由决定所有事情
 ↓
Tool
 ↓
Tool
 ↓
Tool
 ↓
Answer
```

而采用：

> **显式 Workflow + 局部 LLM Agent**

例如 Fund Research：

```text
START
  ↓
Understand Question
  ↓
Build Research Plan
  ↓
Collect Data
  ↓
Quantitative Analysis
  ↓
Market Research
  ↓
Investment Thesis
  ↓
Evaluate
  ↓
Generate Report
  ↓
END
```

这样能够清晰观察：

* Agent 做了什么
* 调用了哪些 Tool
* 为什么调用
* 花了多少 Token
* 哪一步出错
* Evaluator 是否有效

---

# 6. 数据与分析原则

FundForge 明确区分：

```text
事实
 ↓
Tool / Database / API

计算
 ↓
Deterministic Analysis

推理
 ↓
LLM

验证
 ↓
Evaluator
```

例如：

```text
基金三年年化收益
最大回撤
Sharpe
波动率
持仓比例
基金规模
费率
```

由程序获取和计算。

LLM 不负责“猜数据”或进行关键金融指标计算。

---

# 7. Evidence First

每一个重要投资结论尽可能建立：

```text
Claim
 ↓
Evidence
 ↓
Source
 ↓
Timestamp
```

例如：

```text
Claim:
基金 A 的历史回撤高于同类基金。

Evidence:
Max Drawdown = -32%
Peer Median = -24%

Source:
Fund Performance Data

Timestamp:
2026-09-08
```

最终报告不仅回答：

> **结论是什么？**

还回答：

> **为什么得出这个结论？**

---

# 8. Evaluator

Evaluator V1 不负责无限 Self-Reflection。

只负责检查：

```text
Factuality
Evidence
Completeness
Risk Coverage
Question Alignment
```

输出：

```text
PASS / FAIL
+
Issues
+
Evidence Problems
```

只有明确发现问题时，才允许进入有限 Repair Loop。

目标：

> **验证 Agent，而不是让 Agent 无限思考。**

---

# 9. 成本控制

FundForge 从 V1 开始记录：

```text
LLM Tokens
Tool Calls
Research Calls
Latency
Cost
```

并设置：

```text
max_llm_calls
max_tool_calls
max_research_steps
max_cost
```

评价 Agent 时同时关注：

```text
Quality
Cost
Latency
```

核心目标：

> **Quality / Cost，而不是单纯追求最高质量。**

---

# 10. Evaluation

FundForge 将 Evaluation 作为核心能力，而不是最后再补。

V1 建立：

```text
Fund Research       20 cases
Fund Comparison     10 cases
Fund Screening      10 cases
Portfolio Analysis  10 cases
```

重点评价：

```text
Accuracy
Evidence Coverage
Analysis Quality
Risk Coverage
Hallucination
Cost
Latency
```

最终比较：

```text
Baseline
    vs
LangGraph Workflow
    vs
Workflow + Evaluator
```

从而验证：

> **Agent Architecture 的复杂度是否真正带来了投资研究质量提升。**

---

# 11. V1 不做

暂时不做：

* 自动交易
* 券商账户连接
* 高频交易
* 基金收益预测
* 市场涨跌预测
* 复杂 Multi-Agent
* 无限 Self-Reflection
* 自动 Portfolio Rebalancing

原则：

> **先做好 Research Agent，再考虑 Investment Agent。**

---

# 12. V1 最小闭环

FundForge 第一阶段只需要把下面这个 Case 做好：

```text
用户：

“分析 XXX 基金是否适合长期持有，
并与两只同类基金进行比较。”
```

Agent 完成：

```text
Question
   ↓
Plan
   ↓
Fund Data
   ↓
Peer Funds
   ↓
Quant Analysis
   ↓
Market Research
   ↓
Risk Analysis
   ↓
Investment Thesis
   ↓
Evidence
   ↓
Evaluation
   ↓
Final Report
```

如果这个闭环能够稳定、高质量、低成本地完成，FundForge V1 就已经成立。

---

# 13. 核心设计原则

FundForge V1 最终只保留 6 条原则：

1. **LangGraph 管流程，不管业务。**
2. **LangChain Tools 管能力，不管投资判断。**
3. **LLM 负责推理，不负责事实和关键计算。**
4. **重要结论必须有 Evidence。**
5. **Evaluator 用于验证，而不是无限反思。**
6. **任何 Agent Complexity 都必须通过 Evaluation 证明其 ROI。**

最终架构理念：

```text
                 FundForge
                     │
          ┌──────────┼──────────┐
          │          │          │
       LangGraph  LangChain   FundForge
       Workflow     Tools        Core
          │          │          │
       如何执行     能做什么     为什么
          │          │          │
          └──────────┼──────────┘
                     ▼
          Investment Research
                     │
              Evidence + Risk
                     │
              Decision Support
```
