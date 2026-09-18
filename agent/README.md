# agent — LangGraph 基金研究工作流

FundForge 的 AI 研究工作流：接收自然语言问题（单基金分析 / 基金对比），经 LangGraph 节点图产出**证据可溯**的结构化研究报告。

技术栈：Python 3.11 / LangGraph / OpenAI 兼容 LLM（论点生成）/ Langfuse（追踪）。

- 分阶段计划见 [`docs/Plan.md`](docs/Plan.md)（Phase 0-9）
- 节点 / State / Evidence / Observability 契约见 [`docs/TechnicalContract.md`](docs/TechnicalContract.md)
- 概念设计见 [`docs/ConceptDesign.md`](docs/ConceptDesign.md)

## 设计文档（docs/）

| 文档 | 内容 |
| ---- | ---- |
| [`docs/ConceptDesign.md`](docs/ConceptDesign.md) | 概念设计 |
| [`docs/Plan.md`](docs/Plan.md) | Agent 分阶段实施计划（Phase 0-9） |
| [`docs/TechnicalContract.md`](docs/TechnicalContract.md) | Agent 技术合同（State / Node / Evidence / Evaluation / Observability 等 §1-18） |

---

## 工作流

```
router → planner → collector → analyzer → researcher → thesis → evaluator → repair? → synthesizer
                                                                              │
                                                         FAIL 且未超修复上限 ──┘
```

| 节点 | 职责 |
| ---- | ---- |
| `router` | 意图识别与任务分类（单基金 / 对比等），规则优先、LLM 兜底 |
| `planner` | 生成研究计划（主基金 + 同类基金、研究重点） |
| `collector` | 通过 collector API 采集基金数据，产出 Evidence 与 Tool 调用记录 |
| `analyzer` | 确定性量化分析引擎（收益 / 风险指标 / 同类对比），不依赖 LLM |
| `researcher` | 补充研究项 |
| `thesis` | LLM 生成投资论点，**Evidence-Claim 强制绑定**（无证据的结论降级为数据缺口） |
| `evaluator` | 结构化评估（事实 / 证据 / 缺项 / 风险），产出评分与修复决策 |
| `repair` | 有限修复（max=1） |
| `synthesizer` | 结构化报告与元数据 |

---

## 目录结构

```
├── main.py          # CLI 入口：组装 graph、写入 Trace、打印报告
├── graph.py         # StateGraph 装配（节点包装 RunTracer）
├── state.py         # FundForgeState（跨节点共享摘要与 ID）
├── store.py         # FundStore：进程内原始数据存储（State 只存 raw_ref 摘要）
├── config.py        # env-only 配置（与 Go 侧 internal/config 模式一致）
├── nodes/           # 九个业务节点（router/planner/collector/…/synthesizer）
├── tools/           # collector_client（HTTPX）+ fund_tools（Tool 定义）
├── analysis/        # 确定性量化分析引擎（engine.py）
├── domain/          # 领域模型（fund/plan/analysis/evidence/thesis/evaluation/report）
├── llm/             # LLM Provider（base.py + openai_compat.py，OpenAI 兼容）
├── eval/            # 评测集（Phase 10）：Case 定义 + 硬检查 + Runner
├── observability/   # RunTracer + TraceSink（Langfuse / JSONL / Null / Multi）
├── docs/            # 设计文档（ConceptDesign / Plan / TechnicalContract）
└── tests/           # 单元测试（mock collector）+ 集成测试（-m integration）
```

---

## 快速开始

```bash
uv sync                                        # 安装依赖（uv 管理，pyproject.toml + uv.lock）
uv run python main.py "分析基金 519770"
uv run python main.py "对比 015453 和 519770 的表现"
```

需要本地 collector 在跑：`docker compose up -d collector`（在仓库根目录）。

LLM 未配置时工作流仍可运行：thesis 节点优雅降级（无论点、记录问题），其余节点不受影响。配置后启用完整论点生成。

### 本地运行输出（均不入库，已在 .gitignore）

每次运行落盘两个文件，文件名均为 `request_id`：

- `output/<request_id>.md`：运行记录——分析过程在前（节点轨迹、Tool 调用、**LLM 输入/输出全文**、证据、数据质量与评估），最终报告 Markdown 在最后；失败运行也会尽力写入已产出内容。
- `log/<request_id>.log`：全量 INFO 日志；终端只打印最终报告与上述文件路径（WARNING 以上同步到终端）。

---

## 配置（env-only）

| 变量 | 作用 | 默认值 |
| ---- | ---- | ------ |
| `COLLECTOR_BASE_URL` | Collector API 地址 | `http://localhost:8000` |
| `COLLECTOR_TIMEOUT_S` | Collector 请求超时（秒） | `120` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 论点生成 LLM（OpenAI 兼容 chat/completions，如 DeepSeek） | 未配置 → thesis 降级 |
| `LLM_TIMEOUT_S` | LLM 请求超时（秒） | `120` |
| `LANGFUSE_HOST`（或 `LANGFUSE_BASE_URL`）/ `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse 追踪 | 未配置 → 仅本地 JSONL |

---

## 可观测性（Phase 9）

每次运行的完整 Trace（节点 span、Tool 调用、Token 用量、评估得分、报告元数据）可同时写入两个目标（扇出）：

- **Langfuse**：live tracing——节点 span 在真实执行时创建/关闭，时间线与嵌套即真实执行顺序；trace id 由 `request_id` 派生，可回溯。
- **本地 JSONL**（恒启用，`output/runs.jsonl`，与运行记录同目录、均不入库）：每行一个 `RunTrace`，供离线分析。

```bash
uv run python main.py "分析基金 519770"

# 用 jq 提取节点耗时
jq -r '.nodes[] | [.node, .duration_ms] | @tsv' output/runs.jsonl
```

本地 JSONL 恒启用，Langfuse 未配置时仅写本地文件，不影响功能。trace 丢失不能拖垮研究主流程——"故障只 log、降级不影响业务"是刻意设计，**业务代码不得模仿它吞业务错误**。

---

## 测试

```bash
uv run pytest                    # 单元测试：mock collector，无需任何服务
uv run pytest -m integration     # 集成测试：真实 collector 数据 + 失败注入
```

集成测试默认跳过（`pyproject.toml` 的 `addopts`），需要 `docker compose up -d collector` 后显式指定 `-m integration`。

---

## 评测集（Phase 10）

评测集 = 给 Agent 的单元测试 + 集成测试（`eval/`），不是给报告打分的主观比赛。Case 为「输入 + 执行档位 + 机器可判定检查点」，检查口径与 Evaluator 对齐（Evidence 绑定、覆盖率、data_gaps 披露、免责声明）。

```bash
uv run python -m eval                    # offline：mock collector + fake LLM（确定性，CI 可跑）
uv run python -m eval --mode live        # live：真实 collector + 真实 LLM（质量门，需服务与 LLM_* 配置）
uv run python -m eval --tag smoke        # 只跑 smoke 层
uv run python -m eval --case research_single_normal  # 只跑指定 Case
uv run python -m eval --list             # 列出全部 Case
```

- **Case 定义**在 `eval/cases.py`（Python dict，无 YAML 依赖），分 offline（10 个）与 live（2 个）两档；每个 Case 的 `note` 说明它防什么回归
- **检查点**在 `eval/checks.py` 注册表（19 个硬检查）；Case 引用未注册检查名会判失败（fail fast）
- **Langfuse 结合**：配置 `LANGFUSE_*` 时，每次评测的 trace 自动上传，检查结果以 scores（`eval_pass` / `checks_passed_ratio` / `claim_coverage_ratio` / `data_gaps_ok`）回写对应 trace，失败时点开 trace 即调试现场
- offline 全量 Case 同时作为 pytest 回归常驻：`uv run pytest tests/test_eval_suite.py`（原 `test_regression_baseline.py` 基线口径已迁移为 Case `research_standard_three_fund`）

---

## 设计原则

- **数据边界**：只通过 collector API 取数，不直连 akshare。
- **外呼收敛**：对 collector / LLM 的调用只经 `tools/` 与 `llm/` 的 Provider 接口，节点内不散落裸 HTTP。
- **State 轻量**：State 只保存跨节点摘要与 ID，完整原始数据放 `FundStore`（`raw_ref` 形如 `store:funds/{code}`）。
- **State 双形态归一化**：LangGraph 回传的 State 值可能是 dict 或 pydantic 模型，统一用 `domain/shared.py` 的 `coerce_model` 归一化，不散落 isinstance 判断。
- **领域纯净**：`domain/` 不依赖 LangGraph / LLM SDK 等框架（TechnicalContract §15）；LLM 仅出现在 `llm/` 与 thesis 节点。
- **证据可溯**：Claim 必须绑定 Evidence；不可验证的结论进入 `data_gaps` 而非报告正文。
- **可观测性不侵入业务**：节点保持业务纯净，业务摘要集中在 `observability/` 层。
