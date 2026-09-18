# 修复持仓年份 hardcode 与运行输出落盘（P0~P3）

分支：`git fetch origin && git checkout -b fix/holdings-year-report-output origin/main`

## 一、问题确认（已核实，均属实）

| # | 问题 | 证据 |
|---|------|------|
| P0-1 | collector 持仓接口 hardcode `"2024"`，agent 链路从不传 year，永远拉 2024 年持仓 | `collector/main.py:261,271`（`date: str = Query("2024")`）；agent 调用链 `agent/nodes/collector.py:209-211 → agent/tools/fund_tools.py:171 → agent/tools/collector_client.py:71-73` 均不传 year |
| P0-2 | 在过期持仓上做对比，报告无任何时效披露（data_quality 全 complete，issue=0） | 输出报告 claim-3"持股230只、前五权重…"、"519770 个股权重极低"均基于 2024 年数据；evaluator 只查 peer_comparison 是否存在，不查持仓时效 |
| P0-3 | 返回数据含年份（akshare `季度` 列→`report_date`，值如"2024年1季度股票投资明细"），全链路无人解析使用 | `collector/main.py:90`（FIELD_MAPS 改名）；`agent/domain/fund.py:29` Holding 透传；evidence/synthesizer 均不读 |
| P1-1 | 业绩分析/风险分析未标注描述哪只基金（只描述主体基金） | `agent/nodes/synthesizer.py:150-169` `_performance_text/_risk_text` 无基金标识 |
| P2-1 | 输出无前十大持仓 | evidence 只带前 5（`collector.py:121-124`），且是 rows 前 5（按季度分组顺序，既非最新季度也非按权重排序）；报告无持仓章节 |
| P3-1 | 内容与日志全进终端，无法回溯 | `agent/main.py:54-114` 全 print；`:27-30` logging 只到 stderr；`agent/output/8fad….md` 是手动 shell 重定向产物，代码不写 output；`.gitignore` 缺 `/agent/output/`（有 `/agent/log`） |
| P3-2 | 无程序化运行记录文件；LLM 输入/输出用完即弃 | thesis prompt（`thesis.py:62-83`）与 response（`:128`）未持久化，本地仅 `traces/runs.jsonl` 摘要（`observability/tracer.py:182-202` 只存 summary） |

顺手修正的既有漂移（本次触碰区域内）：`agent/docs/TechnicalContract.md` 的 `get_fund_holdings` 签名写成 `as_of: date | None`，实现是 `year: str | None`；`agent/tests/conftest.py:29-31` mock 的 `report_date: "2025-06-30"` 与真实 akshare 季度字符串格式不符。

## 二、方案

### 1. P0：持仓拉最新 + 时效透明化

**collector/main.py**（唯一 akshare 边界，"取最新可用"职责放这里）：
- 新增 helper `_fetch_holdings_df(fetch, code, date)`：`date` 未传 → 用当前年份；**仅当未显式传 date** 时，当前年失败或空 df → 回退上一年重试一次（info 日志注明回退）；显式传 date 保持原语义（空就空，不回退、不掩盖错误）。最终仍失败照常 502。
- 两个持仓端点 `date: str = Query(None)`，内部走 helper。**响应结构不变**（裸数组），Go 侧不消费 holdings、CLI 无引用，无跨语言契约影响。

**agent/domain/fund.py**（纯函数，可单测，domain 不引框架）：
- `parse_report_period(s) -> tuple[int, int] | None`：正则 `(\d{4})年(\d{1,2})季度` 子串搜索；
- `latest_report_period(holdings) -> str | None`：取最新 (year, quarter) 的原文；
- `top_holdings(holdings, n=10)`：取最新报告期的行，按 hold_ratio 降序（None 最后）取前 n。

**agent/nodes/collector.py**：
- `holdings_evidence`：value 增加 `latest_report_period`；`top_holdings` 改为最新报告期 top10；source_detail 改 `股票持仓：N 条（最新报告期 X）`；解析不出报告期则不带，不编造。
- `_collect_fund`：最新报告期年份 < 当前年份 → `result.issues.append(f"{code}: 股票持仓最新报告期为 {period}，非当前年度披露")`。
- 时效问题经既有机制自动闭环：`data_quality_issues` → thesis 强制合并进 `data_gaps`（thesis.py:156-169）→ 报告"数据缺口与局限"章节 + evaluator Completeness 校验（evaluator.py:113-114）。**这就是 P0-2 的修复：报告必然披露持仓时效。**

**agent/tools/fund_tools.py / collector_client.py**：不改（agent 保持"取最新"，年份决定权在 collector）。

### 2. P1：报告章节标注基金

`agent/nodes/synthesizer.py`：
- `_performance_text` / `_risk_text` 增加主语：`015453 中欧中证500指数增强A（主体基金）：区间…`；
- `_peer_text` 行加基金名（summaries 建 id→name 映射）：`- 015453 中欧中证500指数增强A: 年化收益…`。

### 3. P2：报告"持仓概览"章节

- `agent/domain/report.py`：`Report` 增加 `holdings_analysis: str | None = None`；`render_markdown` 在"基金概览"后渲染 `## 持仓概览（最新报告期前十大）`。
- `synthesizer.py` 新增 `_holdings_text`：从 State evidence 中筛 holdings evidence（value 含 `top_holdings`），按 summaries 顺序输出 `- **015453 名称**（报告期 2026年2季度）：滨江集团 2.63%、…`；无股票持仓（债基/货基正常披露）则不出章节。

### 4. P3：运行输出落盘 + LLM 输入输出记录

**State / 域模型**：
- `agent/domain/evidence.py` 新增 `LlmInteraction`（pydantic）：`node, model, prompt, response, input_tokens, output_tokens, ok, error`；
- `agent/state.py` 增加 `llm_interactions: list[LlmInteraction]`（append-only，同 evidence 约定；prompt 几 KB，可接受）；
- `agent/nodes/thesis.py`：成功与失败（LLMError/ValidationError）路径都追加一条（失败时 response 存错误摘要）。

**agent/main.py**：
- request_id 先生成；logging 加 FileHandler → `agent/log/<request_id>.log`（`mkdir(parents=True)`），控制台 Handler 降为 WARNING（精简终端已确认）；
- 新增 `_write_run_output(state, trace, error=None)` → `agent/output/<request_id>.md`，**"有什么写什么"，成功与失败运行都写**（失败用 `tracer.last_state` 尽力取部分结果 + error 段）；
- 终端只打印：最终报告 Markdown + 两个文件路径；失败时打印错误 + log 路径。

输出文件结构（P3-2 要求：过程在前，MD 结论在后）：

```
# FundForge 运行记录
request_id / query / 起止时间与耗时 / task_type / model / 评估状态

## 1. 分析过程
### 1.1 节点轨迹        （RunTrace.nodes：节点、耗时、输出摘要）
### 1.2 Tool 调用        （tool_calls 原文）
### 1.3 LLM 输入 / 输出  （llm_interactions：system+user prompt 全文、response 全文、token）
### 1.4 证据             （evidence 原文）
### 1.5 数据质量问题与评估（data_quality_issues、evaluation、repair_actions）

## 2. 最终报告
<render_markdown(report) 全文>
```

**.gitignore**：增加 `/agent/output/`（`/agent/log` 与 `*.log` 已覆盖）。

**文档同步**（最小化）：`agent/docs/TechnicalContract.md` 校正 `get_fund_holdings` 签名为 `year: str | None`、State 字段清单补 `llm_interactions`；`agent/README.md` 补一小节"本地运行输出（output/ 与 log/，均不入库）"。

### 5. collector 最小测试基建（已确认要建）

- `collector/pyproject.toml`：dev 依赖组加 `pytest`，`uv lock` 同步（与 pyproject 同 commit，规范 8.5）；
- `collector/tests/test_holdings_year.py`：monkeypatch `ak.fund_portfolio_hold_em`，直接调用端点函数（不起 HTTP 层）：① 未传 date → 请求当前年份；② 当前年空 → 回退上一年；③ 显式传 date 为空 → 不回退返回空；④ 异常 → 回退、上一年也异常 → 502。

## 三、文件改动清单

| 文件 | 动作 |
|---|---|
| `collector/main.py` | 持仓端点年份默认当前年 + 回退 helper |
| `collector/pyproject.toml`、`collector/uv.lock`、`collector/tests/test_holdings_year.py`（新） | 最小测试基建 |
| `agent/domain/fund.py` | 报告期解析/top10 纯函数 |
| `agent/domain/evidence.py`、`agent/state.py` | `LlmInteraction` + State 字段 |
| `agent/nodes/collector.py` | evidence 组装（period/top10）+ staleness issue |
| `agent/nodes/thesis.py` | llm_interactions 捕获 |
| `agent/nodes/synthesizer.py` | 章节标注基金名 + 持仓概览组装 |
| `agent/domain/report.py` | `holdings_analysis` 字段 + 渲染 |
| `agent/main.py` | 日志落盘 + 输出文件 + 精简终端 |
| `.gitignore` | `/agent/output/` |
| `agent/docs/TechnicalContract.md`、`agent/README.md` | 合同/文档同步 |
| `agent/tests/conftest.py` | mock report_date 改真实季度格式 |
| `agent/tests/test_nodes.py`、`test_report.py`、`test_thesis.py`、`test_main.py`（部分新增） | 用例 |

## 四、测试与验证（1.4：先写测试锚定行为）

1. **新增/调整单测**：
   - domain：`parse_report_period`/`latest_report_period`/`top_holdings`（多季度混排、None ratio、无年份字符串）；
   - collector node：多季度 rows → top10 属最新报告期且按权重排序；旧年份 → issue 追加、evidence 带 period；
   - synthesizer/report：业绩/风险文本带基金标识；peer 行带名称；持仓概览章节渲染；无持仓不出章节；
   - thesis：成功/失败路径均产出 llm_interactions；
   - main writer：临时目录下写文件、失败容错（缺字段跳过）。
2. **命令**：
   - `uv --directory agent run pytest`（单测，mock collector）
   - `uv --directory collector run pytest`（新增）
   - `go build ./... && go test ./... -count=1 && go vet ./...`（无 Go 改动，跑一遍确认无影响）
   - offline eval：`uv --directory agent run python -m eval`（已核对 `agent/eval/checks.py` 只做结构断言，不受文本变化影响）
3. **端到端手动验证**：collector 起服务 → `uv run python main.py "对比 015453 和 519770 的表现"` → 检查：
   - 日志出现在 `agent/log/<request_id>.log`，终端只有报告 + 两个路径；
   - `agent/output/<request_id>.md`：含 LLM 输入/输出全文，最终报告在文件末尾；
   - 报告中持仓报告期为最新（2026年Q2），业绩/风险标注基金名，新增持仓概览章节；
   - 若报告期非当前年，"数据缺口与局限"中出现时效披露。

## 五、提交拆分（8.4：测试绿才提交）

1. `fix(collector): 持仓接口默认取当前年份并回退上一年`（collector + 其测试）
2. `feat(agent): 持仓时效披露与最新报告期 top10，报告标注基金与持仓概览`（P0 agent 侧 + P1 + P2 + 测试）
3. `feat(agent): 运行记录与日志落盘，记录 LLM 输入输出`（P3 + 文档同步）

## 六、权衡与风险

- **回退上一年**有静默降级嫌疑 → 用 info 日志 + evidence `latest_report_period` + （跨年时）data_quality_issue 三重透明化；显式传 date 不回退，不掩盖调用方意图。
- **staleness 阈值 = 年份 < 当前年**：每年 1-4 月会对上一年 Q4 数据提示"非当前年度披露"——是事实陈述，宁多披露不静默。
- `llm_interactions` 进 State 使 State 变大（prompt 数 KB）：换取 main.py 无需侵入 observability 即可拿到全文；trace 摘要机制不动。
- LLM 输出文件含完整 prompt（evidence dump），无密钥等敏感信息，且目录已 gitignore。
