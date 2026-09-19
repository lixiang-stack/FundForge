# Fund 域模型清理 + 净值口径修复方案

## 根因结论（对应四个问题）

1. **category 恒 None**：雪球详情数据源无独立 category 数据项，`get_fund_info` 不映射 → 恒 None，`summarize_fund` 把 None 复制进 FundSummary（md 71 行）。**决定：删除该字段**。
   附带发现：`Fund.benchmark` 也是实际死的——`agent/tools/fund_tools.py:93` 读 `kv.get("业绩基准")`，而 collector 透传雪球 item 名为 `业绩比较基准`（`collector/main.py:210-215` 无字段映射）→ 恒 None（真 bug，需修键名）。
2. **nav_point_count 1064 vs 1067**：`agent/output/check_nav_diff.py` 的"引擎口径有效点数"按**去重后唯一日期**算（`uniq`，L60/68），而真实链路按 collector「单位净值走势」**原始行**逐行建 `NAVPoint` 不去重（`agent/tools/fund_tools.py:126-138`）→ 519770 窗口内有 3 个重复日期行，engine 数 1067、脚本去重后数 1064，显得"一致"。脚本输出"重复日期（会虚增点数）"一行即列出了这 3 个日期。重复行还会在收益序列里插入近 0 的伪收益。
3. **acc 优先回退 unit 不合理之处**：逐点回退在 acc 覆盖断点处产生虚假收益跳变；多基金对比时两基金可能静默使用不同基准（一个 acc 一个 unit），收益不可比。已知简化保留：累计净值=单位净值+简单加总分红（非复权）。
4. **519770.json → Fund 新增字段**：full_name（基金全称）、custodian（托管银行）、rating_agency（评级机构）、rating（基金评级）、investment_strategy（投资策略）、investment_objective（投资目标）；benchmark 修键名后自然接通。

## 改动清单

### 1. domain 死代码最小清理（问题 1）

**`agent/domain/fund.py`**
- 删 `Fund.category`（L41）、`Fund.manager_id`（L42）
- 删 `FundSummary.category`（L60）及 `summarize_fund` 中的 `category=fund.category`（L96）
- 删 `FundPerformance.sortino`（L83）、`FundPerformance.benchmark_return`（L84）
- 其余 B/C 档死代码（Fund.currency、Evidence.confidence、Report.analysis、枚举占位等）**不动**，清单已另行报告

**`agent/domain/analysis.py`**
- 删未使用 import `from domain.fund import FundSummary`（L10）

**`agent/docs/TechnicalContract.md` §7**：Fund/FundSummary 代码片段同步（去 category/manager_id/sortino/benchmark_return，补上代码中已有的 manager_name/company）

### 2. benchmark 键名修复（问题 1 附带）

**`agent/tools/fund_tools.py:93`**：`kv.get("业绩基准")` → `kv.get("业绩比较基准")`

### 3. 净值点按日期去重（问题 2）

**`agent/tools/fund_tools.py` `get_fund_performance`**：建点后、日期过滤前去重，保留末行（与 `acc_by_date` 的 dict 语义一致），注释说明"为什么"：

```python
# akshare 单位净值走势偶发重复日期行：虚增 nav_point_count 并在收益序列插入伪收益；
# 与 acc_by_date 字典语义一致，同日保留末行
by_date = {p.nav_date: p for p in points}
points = sorted(by_date.values(), key=lambda p: p.nav_date)
```

**`agent/output/check_nav_diff.py`**（未跟踪的诊断脚本）：修复后 engine 口径与脚本去重口径自然一致；将"引擎口径有效点数"标注改为"去重口径"，末行补充原始行数对比，避免再次误判。

### 4. 净值口径统一（问题 3）

**`agent/analysis/engine.py`**
- `compute_fund_metrics(points, basis="auto")` 增加基准参数：
  - `"acc"`：全序列取 acc_nav（acc 缺失点视为无效点）
  - `"unit"`：全序列取 unit_nav
  - `"auto"`：窗口内有效点 acc 全覆盖 → `"acc"`；否则整序列回退 `"unit"`（**不再逐点混用**）
- `FundMetrics` 输出携带所选基准
- docstring 口径说明同步（含"累计净值非复权"的已知简化）

**`agent/domain/analysis.py`**：`FundMetrics` 增加字段 `nav_basis: str | None = None`

**`agent/nodes/analyzer.py`**
- 多基金对比：先按 auto 各算一遍；若各基金 `nav_basis` 不一致，全部以 `basis="unit"` 重算，并向 `data_quality_issues` 追加一条"净值口径不一致（部分基金累计净值覆盖不全），已统一按单位净值口径"
- `_build_evidence` 的 calculation value 中增加 `"nav_basis"` 披露
- 对齐窗口端点检测（`_aligned_window`）沿用"unit 或 acc 任一非空"的有效点口径，不变

### 5. Fund 新增字段（问题 4）

**`agent/domain/fund.py` `Fund`** 增加（全部 `str | None = None`）：
`full_name`、`custodian`、`rating_agency`、`rating`、`investment_strategy`、`investment_objective`

**`agent/tools/fund_tools.py` `get_fund_info`** 增加映射：
`基金全称→full_name`、`托管银行→custodian`、`评级机构→rating_agency`、`基金评级→rating`、`投资策略→investment_strategy`、`投资目标→investment_objective`（benchmark 键名修复见上）
- `data_quality=quality_of(...)` 参数保持原 5 个关键字段不变（长文本/评级字段不参与质量评级）

**`agent/nodes/collector.py` `fund_evidence`**：value 字典补充 `benchmark`、`company` 及全部新字段，让 LLM 证据里能看到业绩基准与投资策略等（FundSummary 保持轻量，不加字段）

**`agent/docs/TechnicalContract.md` §7**：Fund 片段补新字段

### 6. 测试

- **`agent/tests/conftest.py`**：`DETAIL_ROWS` 增加 基金全称/托管银行/评级机构/基金评级/投资策略/投资目标/业绩比较基准 条目
- **`agent/tests/test_fund_tools.py`**：
  - 断言新字段与 benchmark 映射成功
  - 新增重复日期用例：`UNIT_ROWS` 含两行同 `nav_date` → `nav_point_count` 按去重计
- **`agent/tests/test_analysis.py`**：engine 基准选择用例（acc 全覆盖→acc；acc 部分缺失→整序列 unit 且 nav_basis="unit"；强制 basis="unit" 时用单位净值计算）
- **`agent/tests/test_alignment.py`**：两基金 acc 覆盖不一致 → 统一 unit 口径重算、`nav_basis=="unit"`、data_quality_issues 记录一条

注：grep 已确认 tests 中无 category/manager_id/sortino/benchmark_return 引用，删除无测试 fallout；`test_contracts.py` 只校验 State 键集合，不受影响。

## 影响面说明

- 纯 agent 侧（Python）改动；collector API 响应结构未动，Go 侧 `internal/adapter/collector/dto.go` 无需同步（AGENTS.md 5.2 已核对）。
- 全 acc 覆盖场景（如本次 md 运行）指标数值不变，仅 nav_point_count 因去重 -3（519770 侧）。

## 验证

1. 单元测试：`uv --directory agent run pytest` 全绿
2. 静态检查：`uv --directory agent run python -c "import main"`（或编译全部模块）无 import 错误
3. 端到端（docker compose 起 collector/server 或本地 uvicorn）：跑一次 "对比 015453 和 519770" 查询，检查输出 md：
   - funds_summary 不再出现 `category` 键
   - fund_data evidence 中 `benchmark` 有值（"50%×沪深300指数收益率+…"）
   - 两基金 calculation evidence 的 `nav_point_count` 在同一 alignment_window 下相等
   - calculation evidence 出现 `nav_basis`，且两基金一致
4. 重跑 `python3 check_nav_diff.py`：脚本口径与 engine 口径一致（差=0，重复日期行已不进点序列）

## 追加分析（2026-09-19）：同窗口净值点数差异的根因与披露

**现象**：015453 与 519770 在同一对齐窗口 [2022-05-06, 2026-09-18] 内点数 1065 vs 1068，多次运行稳定复现（差恰 3）。

**排除项**（对照实验，双路径 payload 完全一致）：

- 引擎/HTTP 客户端处理零丢行：`parse_fail=0`、去重后 `engine_only=0`；
- 当前数据源返回中无重复日期行、无全空行、unit/acc 覆盖一致。

**根因**：

1. **主因（合法差异）**：015453 成立初期（2022-05-06 成立）建仓期未逐日披露净值，2022-05-09/10/11 三个交易日无净值行。雪球源（蛋卷 `djapi/fund/nav/history`，akshare 未包装、需 collector 直连）与东财主版本一致，均只有 1065 行（05-06 成立日 → 05-12/05-13 起每日披露）。对齐窗口只统一端点、不统一逐日覆盖（引擎既定口径），披露频率不同导致的点数差是合法现象。
2. **次因（数据源脏数据）**：东财 `pingzhongdata/{code}.js`（akshare `fund_open_fund_info_em` 唯一数据源，`fund_em.py:469`）偶发多吐含 05-09/10/11 的 1068 行版本，在两个版本间摇摆；短时间高频请求还会触发限流返回空表。雪球源可作交叉校验（两侧行数不一致时以雪球为准或记 issue）。

**治理**：

- analyzer 对比场景在同窗口内各基金点数差 > `_POINT_COUNT_DIFF_TOLERANCE`（1%）时，向 `data_quality_issues` 追加披露"各基金逐日覆盖不一致，指标横向对比需谨慎"，使报告可见而非静默（容忍度内视为正常披露频率噪声）。
- 点有效性判定（单位/累计净值任一非空）内联于 `analyzer._aligned_window`，现下沉为 `NAVPoint.has_value`，`engine._select_basis` 同步复用。
