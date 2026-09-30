# 基金筛选（fund_screening）设计定稿

> 状态：设计定稿（2026-09-26，grilling 会话结论）。取代根目录 `issuse.md` 草案；术语表见根目录 `CONTEXT.md`；候选池来源决策见 `docs/adr/0001-fund-screening-universe-from-rank-table.md`。

## 1. 目标与定位

自然语言 → 带披露的推荐短名单。不是「全市场智能选基引擎」：

- LLM 只做理解（NL→ScreenSpec）与最终话术；过滤、排序、缺口判定全部确定性；
- 风险指标在全候选池不可得，用预选集 + 锚点披露诚实处理，不假装满足。

## 2. 数据流（Step 1）

```text
自然语言
  → router：新增 screening 意图规则（FUND_SCREENING 枚举已预留，task_type.py:13）
  → planner：不动（透传 task_type，fund_ids 为空）
  → screener（新节点）
      ① NL→ScreenSpec：LLM 结构化输出（JSON Mode + Pydantic，先例 thesis.py:131），
         失败/超时 → 规则兜底（裁决：采纳 issuse.md §4 的「LLM 先行」，废止 §8「先规则」表述）
      ② 候选池构建：GET /api/funds/rank?symbol=主类（1 类型 1 次调用，自带收益列）
      ③ 预筛：候选池级字段 + 锚点 → 预选集 Top M=30
      写 state：screen_spec、fund_ids=预选集、预选集 rank 行、screening_meta{候选池大小,锚点,M}
  → collector（复用）：仅对预选集并发拉 NAV（现有采集/evidence 机制原样）
  → analyzer（复用）：1/3/5 年年化/回撤/夏普/波动
  → screen_finalize（新节点，纯确定性）：风险硬过滤 → 排序 → Top N → ScreenResult
  → evaluator（screening 分支）：披露完整性检查
  → synthesizer：report.py 的 fund_screening 渲染分支（先例 fund_comparison）
```

thesis / researcher / repair 不在路径上；evaluator FAIL 直达 synthesizer（不进 repair 回路）。

## 3. 候选池与预选集规则

- **候选池**：rank 表按主类切出的全市场切片；预筛零 NAV 成本；
- **预筛锚点**：用户给出收益条件或收益排序时用之；否则默认 = `lookback_years` 对应收益列降序（1→近1年，3→近3年，5→近3年回退）；**锚点必须随报告披露**；
- **M = 30**（代码常量，不做配置）；候选池 ≤ M 时全取；
- 成本：30 只 NAV 采集，与常规 Top N 详采同量级。

## 4. ScreenSpec（字段表 v2，每个字段标注执行层）

```python
class ScreenSpec(BaseModel):
    # 候选池级（rank 表列直接可筛）
    fund_types: list[str] = []                # 主类，映射 rank symbol：股票型/混合型/债券型/指数型/QDII/LOF/FOF
    exclude_types: list[str] = []
    min_period_return: float | None = None    # 区间收益率（非年化），作用于 lookback 对应列
    lookback_years: int = 3                   # 1/3/5

    # 预选集级（analyzer 计算后硬过滤）
    min_sharpe: float | None = None
    max_max_drawdown: float | None = None     # 绝对值更小更好
    max_volatility: float | None = None
    min_aum: float | None = None              # M 只逐只 detail；仅过滤不做排序
    max_aum: float | None = None
    min_inception_years: float | None = None

    # 排序（统一在 finalize 执行）
    sort_by: Literal["period_return", "sharpe", "max_drawdown", "volatility"] = "sharpe"
    sort_order: Literal["asc", "desc"] = "desc"
    top_n: int = 5

    # 解释用
    raw_query: str
    assumptions: list[str] = []
    unsupported_requirements: list[str] = []  # 无法落地的条件，汇入 data_gaps
```

执行规则：候选池级字段在预筛执行，预选集级字段在 finalize 执行；任一字段无数据来源 → `unsupported_requirements` → `data_gaps`。回撤符号口径以 analyzer 现有实现为准，实现时对齐。

## 5. screen_finalize 与 ScreenResult

- 输入：analysis 指标 + 预选集 rank 行（state 传递）+ ScreenSpec；
- 行为：风险硬过滤（**指标缺失/NAV 不足窗口 = 剔除并披露**，不降窗口硬算）→ `sort_by` 排序 → Top N → 每只模板化一句话理由 → `ScreenResult`（新 Pydantic，存 `state.screening_result`）→ data_gaps 装配（unsupported + 剔除原因 + 偏差声明）；
- **0 只满足**：输出「无可满足条件」并列出最难满足的条件，绝不放宽阈值；1~4 只如实输出数量与原因。

## 6. 报告形态

```text
# 筛选结果：<条件摘要>（Top N）

筛选条件（系统理解）：
- 类型：指数型；候选池大小 N=2143；预筛锚点：近3年收益降序（M=30）
- 最大回撤 ≤ 20%；排序：回撤升序

推荐：
1. 000000 沪深300ETF联接A
   3年年化 x%，最大回撤 -x%，夏普 x
   理由：<模板化一句话>

未满足/无法验证的条件：
- 「要明显跑赢中证500」：当前无基准超额分解能力

风险提示：
- 风险指标仅在按锚点预筛的 Top 30 内计算，存在样本偏差
- 历史回撤/收益不代表未来
```

## 7. evaluator 的 screening 分支（确定性检查）

输出行数 = Top N（或 0 只缺口态）；每行指标齐全；`unsupported_requirements` 全部出现在缺口披露；候选池大小与锚点已披露；用到风险指标时偏差披露必在；最终排序与 ScreenSpec 一致。

## 8. 实施清单（Step 1）

| # | 改动 | 验证 |
|---|---|---|
| 1 | `collector/main.py`：`FIELD_MAPS["fund_rank"]` + `get_fund_rank` 用 mapping_key | agent fixture 锁形状 |
| 2 | `collector_client.py`：`FUND_RANK_PATH` 常量 + 取数方法 | MockTransport 单测 |
| 3 | `agent/domain/screening.py`（新）：ScreenSpec / ScreenResult，纯净 domain 禁框架 import | 校验单测 |
| 4 | `task_type.py` screening 关键词 + `intent.py` R 规则 | `test_intent.py` |
| 5 | `nodes/screener.py`（新）：解析 + 候选池 + 预筛 | fake LLM 单测 |
| 6 | `nodes/screen_finalize.py`（新） | 过滤/排序/缺口单测 |
| 7 | `graph.py`：条件边 + 跳过 thesis/researcher/repair | 图路由单测 |
| 8 | `state.py` 新 key + `test_contracts.py` 同步 | 合同测试 |
| 9 | `evaluator.py` screening 分支 | 单测 |
| 10 | `report.py` 渲染分支 | 单测 |
| 11 | `main.py` 装配点接线（screener/finalize 的 LLM provider 注入） | 启动冒烟 |
| 12 | eval：cases +1~2、checks 增披露检查；integration：rank symbol 枚举核对 + 端到端 | `-m integration` |

无新依赖（httpx/pydantic 已有）；Go 零改动，提交前三件套照跑。

## 9. 后续路径

- **Step 2**：短名单理由绑定 Evidence（claims + evaluator 证据覆盖检查）；
- **Step 3**：collector 侧纯 Python 因子表（定时批任务），候选池级风险硬过滤取代预选集偏差；与 Go 策略模板对齐（策略条件 → ScreenSpec 翻译）。
