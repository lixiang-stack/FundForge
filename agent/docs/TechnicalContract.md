```markdown
# FundForge V1 — Technical Contract（优化合并版）

> **Purpose:** Define the stable technical contracts between LangGraph, LangChain Tools, LLM, FundForge domain logic, data, and evaluation.  
> **Core Principle:** Framework controls execution; FundForge controls business logic.  
> **Version:** V1 Optimized (2026-09)

State 是任务上下文，Node 是流程步骤，Edge 是控制流，Tool 是外部能力，Data Model 是领域事实。

---

## 1. Architecture

```text
                         User Request
                              │
                              ▼
                         ┌─────────┐
                         │ Router  │  (V1 可与 Planner 合并)
                         └────┬────┘
                              ▼
                         ┌─────────┐
                         │ Planner │
                         └────┬────┘
                              ▼
                         ┌─────────┐
                         │Collector│
                         └────┬────┘
                              │
                              ▼
                         ┌─────────┐
                         │Analyzer │
                         └────┬────┘
                              ▼
                        ┌───────────┐
                        │ Researcher│
                        └─────┬─────┘
                              ▼
                         ┌─────────┐
                         │ Thesis  │
                         └────┬────┘
                              ▼
                         ┌─────────┐
                         │Evaluator│
                         └────┬────┘
                         PASS │ FAIL
                              │   └──→ Repair (max 1) ──┐
                              │                         │
                              ▼                         │
                         ┌──────────┐                    │
                         │Synthesizer│◄──────────────────┘
                         └────┬─────┘
                              ▼
                            Report
```

### Framework Boundary

| Component            | Responsibility                                  |
| -------------------- | ----------------------------------------------- |
| **LangGraph**        | Workflow / State / Routing / Retry / Checkpoint |
| **LangChain Tools**  | External capabilities (facts only)              |
| **LLM**              | Planning / Reasoning / Synthesis                |
| **FundForge Core**   | Investment domain logic                         |
| **Analysis Engine**  | Deterministic calculations (pure functions)     |
| **Data Layer**       | Financial facts + quality metadata              |
| **Evidence + Claim** | Claim traceability (mandatory binding)          |
| **Evaluator**        | Output validation (limited repair)              |

### Core Principle

> **Framework controls execution; FundForge controls business logic.**  
> Domain Layer 不依赖 LangGraph。LangGraph 是可替换的 Runtime。

---

## 2. State Contract（优化版）

LangGraph State 是所有 Node 之间共享的任务上下文。**完整大对象不进 State**。

```python
class FundForgeState(TypedDict, total=False):
    # === Request ===
    request_id: str
    user_query: str
    task_type: TaskType

    # === Planning ===
    research_plan: ResearchPlan
    current_step: str

    # === Domain References（轻量） ===
    fund_ids: list[str]
    peer_fund_ids: list[str]
    portfolio_id: str | None

    # === 核心结构化结果（控制体积） ===
    funds_summary: list[FundSummary]          # 轻量摘要
    analysis: AnalysisResult
    research_items: list[ResearchItem]

    # === Evidence & Reasoning（强制可追溯） ===
    evidence: list[Evidence]
    claims: list[Claim]
    investment_thesis: InvestmentThesis

    # === Evaluation & Control ===
    evaluation: EvaluationResult
    iteration: int                            # 默认 0，硬限制 max=1
    repair_actions: list[str]

    # === Output ===
    report: Report                            # 结构化报告

    # === Observability ===
    token_usage: TokenUsage
    tool_calls: list[ToolCallRecord]
    data_quality_issues: list[str]
    errors: list[str]
    cost_status: Literal["ok", "approaching_limit", "exceeded"]
```

### State Rules

1. State 只保存**跨 Node 真正需要共享的摘要与 ID**。完整 Holdings、原始 Tool 返回、长文本 Research 内容通过外部 Store / Repository 按需加载。
2. 不在 State 中保存 LLM Client、DB Connection、Tool Instance 等运行时对象。
3. 所有重要中间结果必须结构化。
4. `iteration` 硬限制为 1（V1）。
5. `evidence` 只允许追加，不允许修改历史记录。
6. State 应支持完整记录一次 Agent Execution（可复现）。

---

## 3. Task Type

V1 只支持：

```python
TaskType = Literal[
    "fund_research",
    "fund_comparison",
    "fund_screening",
    "portfolio_analysis",
]
```

不要在 V1 建立过细的 Intent Taxonomy。Portfolio Analysis 为最低优先级支持。

---

## 4. Node Contract

### Router
```text
Input:  user_query
Output: task_type
```
职责：判断任务类型，不负责投资分析。  
V1 建议：可与 Planner 合并以降低复杂度。

### Planner
```text
Input:  user_query, task_type
Output: research_plan
```
职责：决定需要哪些数据、研究和分析。  
约束：
- 不直接执行 Tool。
- 输出必须结构化。
- 不负责最终投资判断。

### Collector
```text
Input:  research_plan
Output: fund_ids, funds_summary, evidence, tool_calls, data_quality_issues
```
职责：获取结构化基金数据（通过 Fund Tools）。  
完整数据写入外部 Store，State 只保留摘要与 ID。

### Analyzer
```text
Input:  funds_summary (或按需加载完整数据), market_data
Output: analysis, evidence (calculation 类型)
```
职责：执行**确定性金融计算**。  
强约束：**关键金融指标不得由 LLM 计算**。

### Researcher
```text
Input:  research_plan
Output: research_items, evidence
```
职责：获取结构化数据之外的外部研究信息（web_search / fetch_document）。

### Thesis
```text
Input:  funds_summary, analysis, research_items, evidence
Output: claims, investment_thesis
```
职责：基于事实和证据形成投资判断。  
LLM 只负责 Interpretation / Reasoning / Trade-off / Risk Identification。  
**每一个重要结论必须生成 Claim，并绑定 evidence_ids**。

### Evaluator
```text
Input:  investment_thesis, claims, evidence, analysis, user_query
Output: evaluation
```
检查维度：
- Factuality
- Evidence Coverage（重要结论是否有足够 Evidence）
- Completeness
- Risk Coverage
- Question Alignment
- Data Quality

不默认触发无限迭代。

### Repair
```text
Input:  evaluation
Output: 有限修正后的 claims / evidence / thesis + repair_actions
```
原则：
- 只修复 Evaluator 明确指出的问题。
- `max_repair_iterations = 1`。
- 允许动作：`fetch_missing_data` | `add_evidence` | `revise_claim` | `add_risk_disclosure` | `reduce_confidence`。
- 不允许重新规划整个 Research Plan。
- 仍 Fail → 强制进入 Synthesizer，并在报告中显式标注证据不足。

### Synthesizer
```text
Input:  user_query, analysis, evidence, claims, investment_thesis, evaluation
Output: report
```
职责：生成最终结构化 Investment Research Report。  
必须包含风险提示与「不构成投资建议」声明。

---

## 5. Graph Contract

V1 Graph 固定为：

```text
START
  ↓
router
  ↓
planner
  ↓
collector
  ↓
analyzer
  ↓
researcher
  ↓
thesis
  ↓
evaluator
  ├── PASS → synthesizer
  │
  └── FAIL → repair → evaluator
                         │
                         └── max iteration → synthesizer
  ↓
END
```

### Routing Rules

**Deterministic Edges**  
router → planner → collector → analyzer → researcher → thesis → evaluator → synthesizer → END

**Conditional Edge**  
evaluator  
├── PASS → synthesizer  
└── FAIL → repair（仅 1 次）

**重要约束**  
> 不要让 LLM 自由决定整个 Graph 的执行路径。  
> LLM 可以决定 Research Plan，但 Workflow Control 由 LangGraph 和程序逻辑负责。

---

## 6. Tool Contract

Tools 使用 LangChain `@tool` 暴露。Tool 只返回事实，不返回投资建议。

### Fund Tools
```python
@tool
def search_funds(query: str, filters: FundFilters | None = None) -> list[FundSummary]: ...

@tool
def get_fund_info(fund_id: str) -> Fund: ...

@tool
def get_fund_performance(fund_id: str, start_date: date, end_date: date) -> FundPerformance: ...

@tool
def get_fund_holdings(fund_id: str, as_of: date | None = None) -> list[Holding]: ...

@tool
def get_fund_manager(fund_id: str) -> FundManager: ...
```

### Market Tools
```python
@tool
def get_index_data(index_id: str, start_date: date, end_date: date) -> IndexData: ...

@tool
def get_sector_data(sector: str, start_date: date, end_date: date) -> SectorData: ...

@tool
def get_market_context(market: str) -> MarketContext: ...
```

### Research Tools
```python
@tool
def web_search(query: str, recency_days: int | None = None) -> list[SearchResult]: ...

@tool
def fetch_document(url: str) -> Document: ...
```

### Tool Rules
1. **Single Responsibility**：禁止一个 Tool 完成所有数据获取与分析。
2. **Tools Return Facts**：返回 Data + Metadata + Source + Timestamp + data_quality，绝不返回“值得买”等判断。
3. **Deterministic First**：能通过 API / 计算得到的，绝不让 LLM 推断。
4. **Observable**：每次调用必须记录 tool_name、arguments、时间、success、error。

---

## 7. Domain Data Model（核心）

### FundSummary（State 轻量版）
```python
class FundSummary(BaseModel):
    id: str
    name: str
    fund_type: str
    category: str
    aum: float | None
    manager_name: str | None
    as_of: datetime
    data_quality: Literal["complete", "partial", "stale", "missing"]
```

### Fund / FundPerformance / Holding / FundManager
（完整定义与原版保持一致，增加 `data_quality` 与 `as_of` 字段）

```python
class Fund(BaseModel):
    id: str
    name: str
    fund_type: str
    category: str
    manager_id: str | None
    benchmark: str | None
    inception_date: date | None
    aum: float | None
    currency: str
    source: str
    as_of: datetime
    data_quality: Literal["complete", "partial", "stale", "missing"] = "complete"
```

```python
class FundPerformance(BaseModel):
    fund_id: str
    period_start: date
    period_end: date
    cumulative_return: float
    annualized_return: float
    volatility: float
    max_drawdown: float
    sharpe: float | None
    sortino: float | None
    benchmark_return: float | None
    source: str
    as_of: datetime
    data_quality: Literal["complete", "partial", "stale", "missing"] = "complete"
```

（Holding、FundManager 同理增加 data_quality）

---

## 8. Evidence + Claim Contract（强制绑定）

```python
class Evidence(BaseModel):
    id: str
    evidence_type: Literal["fund_data", "market_data", "calculation", "research", "manager"]
    source: str
    source_detail: str | None
    as_of: datetime | None
    value: str | float | dict | None
    data_quality: Literal["complete", "partial", "stale", "missing"] = "complete"
    confidence: float = 1.0
    raw_ref: str | None                    # 指向外部完整原始数据


class Claim(BaseModel):
    id: str
    statement: str
    claim_type: Literal[
        "performance", "risk", "style", "manager",
        "portfolio", "peer", "suitability"
    ]
    evidence_ids: list[str]                # 强制：至少 1 个
    strength: Literal["strong", "moderate", "weak"]
    assumptions: list[str] = []


class InvestmentThesis(BaseModel):
    summary: str
    claims: list[Claim]                    # 所有重要结论必须在这里
    positives: list[str]
    negatives: list[str]
    risks: list[str]
    key_assumptions: list[str]
    suitability: str                       # 针对「是否适合长期持有」的明确回答
    confidence: float                      # 证据充分程度（非未来收益概率）
    data_gaps: list[str] = []
```

**强制规则**：
- 每一个重要投资结论必须对应至少一个 Claim。
- 每个 Claim 必须绑定 evidence_ids。
- Evaluator 重点检查 Evidence Coverage 与 data_gaps。

---

## 9. Analysis Contract

```python
class AnalysisResult(BaseModel):
    performance: PerformanceAnalysis
    risk: RiskAnalysis
    portfolio: PortfolioAnalysis | None
    peer_comparison: PeerComparison | None
```

Analysis Engine 必须是 **deterministic、testable、reproducible** 的纯函数集合：
- `calculate_max_drawdown(nav_series)`
- `calculate_sharpe(returns)`
- `calculate_volatility(returns)`
- `calculate_correlation(...)`
- 等

这些函数不依赖 LLM，结果写入 Evidence（type=calculation）。

---

## 10. Evaluation + Repair Contract

```python
class EvaluationResult(BaseModel):
    status: Literal["pass", "fail"]
    factual_issues: list[str]
    evidence_issues: list[str]
    missing_items: list[str]
    risk_issues: list[str]
    question_alignment_issues: list[str]
    data_quality_issues: list[str]
    overall_score: float
    critical: bool                         # 致命问题（数据错误 / 严重幻觉）


class RepairAction(BaseModel):
    action_type: Literal[
        "fetch_missing_data",
        "add_evidence",
        "revise_claim",
        "add_risk_disclosure",
        "reduce_confidence"
    ]
    target: str
    reason: str
```

Repair 边界（V1）：
- 最多 1 次。
- 只修复 Evaluator 指出的具体问题。
- 失败后强制 Synthesizer，并在报告中标注证据不足。

---

## 11. Report Contract（结构化）

```python
class Report(BaseModel):
    title: str
    generated_at: datetime
    request_id: str

    executive_summary: str
    fund_overview: list[FundSummary]
    performance_analysis: str
    risk_analysis: str
    peer_comparison: str | None
    manager_analysis: str | None

    investment_thesis: InvestmentThesis
    key_claims: list[Claim]

    data_gaps_and_limitations: list[str]
    risks_and_disclaimers: list[str]       # 强制包含合规声明

    metadata: ReportMetadata               # token / cost / tool_calls / data_as_of 等
```

Synthesizer 必须输出完整 Report 结构。

---

## 12. Observability Contract

```python
class ToolCallRecord(BaseModel):
    tool_name: str
    arguments: dict
    started_at: datetime
    finished_at: datetime
    success: bool
    error: str | None


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    estimated_cost: float = 0
```

每次完整 Execution 必须能统计：Quality / Tokens / Tool Calls / Latency / Cost。

---

## 13. Cost Governor

```python
class CostLimits(BaseModel):
    max_llm_calls: int = 12
    max_tool_calls: int = 20
    max_cost_usd: float = 0.5
    max_repair_iterations: int = 1
```

- `approaching_limit`：减少非关键研究步骤，降低详细度。
- `exceeded`：跳过 Repair，直接生成带警告的报告。

---

## 14. LLM Contract

```python
class LLMProvider(Protocol):
    async def generate(
        self,
        messages: list[Message],
        *,
        structured_output: type[BaseModel] | None = None,
    ) -> LLMResponse: ...
```

Agent 不直接依赖具体模型（OpenAI / DeepSeek / Gemini / Claude 等），通过 Provider 替换。

---

## 15. Architecture Dependency Rules

正确依赖方向：
```text
Agent
  ↓
Tools Interface
  ↓
Domain / Repository
  ↓
Data Provider
```

禁止 Domain 依赖 LangGraph。

---

## 16. V1 Non-Goals

```text
Multi-Agent
Autonomous Trading
Broker Integration
Return Prediction
Market Prediction
Automatic Rebalancing
Long-term Memory
Complex RAG
Infinite Self-Reflection
```

未来新增能力必须通过 Evaluation 证明 ROI。

---

## 17. V1 Acceptance Criteria

必须稳定完成：
> “分析基金 A 是否适合长期持有，并与基金 B、C 进行比较。”

执行过程必须具备：
- Structured Fund Data
- Deterministic Quant Analysis
- External Research
- Evidence + Claim 强制绑定
- Investment Thesis（含 suitability + confidence + data_gaps）
- Risk Analysis
- Evaluation（有限 Repair）
- 结构化 Final Report
- Token / Cost / Latency Tracking
- 数据质量传递与披露

任何重要结论必须能回答：**这个结论的数据依据是什么？**

---

## 18. Final Design Principle

FundForge V1 的核心不是 Build a sophisticated Agent，而是：

> **Build a verifiable investment research workflow powered by an Agent.**

最终职责划分：

```text
                FundForge
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   LangGraph    LangChain      Core
   Workflow       Tools
       │            │            │
    怎么执行      能做什么       为什么
                                  │
                         ┌────────┼────────┐
                         ▼        ▼        ▼
                       Data    Analysis  Evidence+Claim
                         │        │        │
                         └────────┼────────┘
                                  ▼
                            Investment Thesis
                                  │
                                  ▼
                              Evaluation
                                  │
                                  ▼
                            Structured Report
```

**六条核心原则（V1 最终保留）**：
1. LangGraph 管流程，不管业务。
2. LangChain Tools 管能力，不管投资判断。
3. LLM 负责推理，不负责事实和关键计算。
4. 重要结论必须有 Evidence，并以 Claim 强制绑定。
5. Evaluator 用于验证，而不是无限反思（最多 1 次 Repair）。
6. 任何 Agent Complexity 都必须通过 Evaluation 证明其 ROI。
```

---