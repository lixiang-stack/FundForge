# 基金分析数据缺口补齐

## 背景

对 15 份 `agent/output` 报告"数据缺口与局限"章节的汇总分析结论（用户已确认）：

- P0 管道故障忽略：LLM 偶发抖动导致，非代码问题。
- Sortino 加回：此前 `fund-domain-cleanup-and-nav-fix.md` 中删除，现重新引入。
- 其余按优先级执行，并新增：行业分析、持仓分析、港股/A股/美股占比分析。

数据源勘察结论（akshare 1.18.94 实测）：

| 数据 | 接口 | 结论 |
|---|---|---|
| 行业配置 | `fund_portfolio_industry_allocation_em(symbol, date)` | 可用，列：行业类别/占净值比例/市值/截止时间 |
| 资产配置（股/债/现金） | `fund_individual_detail_hold_xq(symbol, date=YYYYMMDD)` | 可用（雪球源），列：资产类型/仓位占比 |
| 费率 | `fund_fee_em(symbol, indicator="运作费用")` | 可用 |
| 同类排名/年度业绩 | `fund_individual_achievement_xq` | 可用，但 collector `FIELD_MAPS["achievement"]` 与实际列不符，需一并修正 |
| 指数日线 | `stock_zh_index_daily_em` | 可用，基准/超额收益前置 |
| 评级 | `/detail` 已有 `rating_agency/fund_rating` 字段 | 先核查为何报告显示"暂无评级"；备选 `fund_rating_all` |
| 单基金规模历史 | 无 | 不可得（`fund_aum_em` 全市场快照、`fund_aum_hist_em` 基金公司维度） |
| 经理任职起始/变更 | 无 | 不可得（`fund_manager_em` 全市场分页爬取且无单基金任职日期） |

既有事实：`benchmark_index`/`benchmark_index_daily` 表已预置（含中证500）；`DataSyncUseCase.SyncBenchmarkData` 为占位；Go `ComputeSnapshot` 的 beta/excess_return 依赖 benchBars（有真实消费方）；collector 的 /rules、/analysis 等端点零消费（不动、不删）。

与既有 P2 结论的差异：规模变动历史、经理任职起始/变更从计划移除（无数据源，维持报告局限）；资产配置改用雪球现成接口采真数据（原打算用持仓加总近似）。

## 改动清单

### 阶段 1：agent 确定性指标扩展（无新数据源）

文件：`agent/analysis/engine.py`、`agent/domain/analysis.py`、`agent/nodes/analyzer.py`、`agent/nodes/synthesizer.py`、`agent/docs/TechnicalContract.md`、tests。

1. `sortino_ratio`：下行偏差口径与 sharpe 一致（rf=0、pstdev、√252；下行波动 0 返回 None）；进 `RiskAnalysis`/`PeerMetricsRow`；渲染到风险分析句与对比表格列。
2. `yearly_returns`：按自然年分桶算累计收益。
3. `max_drawdown_recovery_days`：谷底到净值修复天数，未修复返回 None。
4. 滚动收益摘要：滚动 1 年（252 交易日）收益 min/median/max。
5. 持仓分析：`analyzer.py` 集中度门控放开至 research 任务（现仅 comparison），同步更新 `agent/eval/cases.py` 证据计数基线；新增 `market_split` 按 stock_code 模式分类 A股（6/0/3 开头 6 位）/港股（5 位数字）/美股（字母）占披露持仓比例。

约定：新指标并入现有 calculation Evidence 的 value dict，不新增 Evidence 条数（仅第 5 条门控放开需改基线）。

### 阶段 2：collector 新端点 + agent 接线

模式：`collector/main.py` 加 `FIELD_MAPS` + `@app.get` 端点；agent 侧 `collector_client.py` 方法 + `fund_tools.py` 新 @tool + `store.py` 三件套 + `nodes/collector.py::_collect_fund` 编排 + evidence + 渲染 + `tests/conftest.py` 路由分支。

1. `GET /api/funds/{code}/industry?year=`：行业配置章节（单基金 + 对比并排）。
2. `GET /api/funds/{code}/allocation?date=YYYYMMDD`：股/债/现金仓位，date 默认取持仓最新 report_date；解决 519770"披露个股权重异常低"的敞口失真。
3. `GET /api/funds/{code}/fees`：`fund_fee_em(indicator="运作费用")`，FIELD_MAPS 以实际返回列为准；独立 tool `get_fund_fees`；渲染到基金概览。可选：Go `fund_info` 费率列已存在，加 FetchFundFees 填充。
4. `/achievement` FIELD_MAPS 修正为实际列（业绩类型→performance_type、周期→period、本产品区间收益→return_rate、本产品最大回撒→max_drawdown、周期收益同类排名→category_rank）；响应形状变化前 grep 消费方（当前 agent/Go/CLI 均零消费，安全）。
5. 评级核查：curl `/api/funds/015453/detail` 查 rating 实际值；源为空则加 `GET /api/funds/ratings`（`fund_rating_all()` 进程内缓存 + 按代码过滤），否则仅渲染 `Fund.rating`。

新端点 Go 侧不强制消费（既有 6 端点零 Go 消费方是既定模式）；agent 侧契约变化同步 `TechnicalContract.md` §6/§7。

### 阶段 3：基准指数与超额收益

1. collector `GET /api/index/{code}/daily?start_date=&end_date=`：`stock_zh_index_daily_em`；日期→trade_date、收盘→close。
2. agent tool `get_index_data`（TechnicalContract 已规划签名）；基准代码解析：`Fund.benchmark` 文本启发式（含"中证500"→000905、"沪深300"→000300、"创业板"→399006；增强指数缺省 000905，其余类型缺省不计算并注明）。
3. engine `excess_return`（对齐窗口内基金 vs 基准累计收益差）+ `tracking_error` 近似（std(超额日收益)×√252）；进 `PeerMetricsRow`，渲染"相对基准超额收益"。
4. Go 基准同步（消费方为 alert 指标 beta/excess_return）：
   - `internal/domain/marketdata/provider.go` 加 `IndexProvider` port；`internal/adapter/collector/client.go` 实现 + `dto.go` 加 `indexDailyJSON`。
   - `BenchmarkRepo` 补 `SaveIndexDaily`（仿 `nav_repo.go` unnest upsert）+ domain 接口。
   - `DataSyncUseCase.SyncBenchmarkData` 实现预置 4 指数增量同步。
   - CLI 加 `sync benchmark`（仿 `sync nav`）；`cmd/server/main.go` 与 `cmd/cli/main.go` initApp 双处接线。

### 阶段 4：文档与收尾

`TechnicalContract.md` 同步（sortino 回归、新 tool、新 Analysis 字段）；`agent/README.md`、`cmd/README.md` 补新端点与命令；commit 拆分：docs → feat(agent-metrics) → feat(collector-endpoints) → feat(agent-tools) → feat(go-benchmark-sync)；冒烟跑一次研究报告与对比报告。

## 明确不做

- 规模变动历史、经理任职起始/变更历史：无数据源。
- 换手率：半年度披露时效差，边际价值低。
- 跟踪误差实测：无披露源，用净值 vs 基准近似替代。
- 风格因子归因、申赎限制明细：投入产出比低。
- /rules、/analysis、realtime、estimation 等既有死端点：不接线不删除。

## 验证

```bash
uv --directory agent run pytest
go build ./... && go test ./... -count=1 && go vet ./...
# 冒烟：起 collector 逐个 curl 新端点；跑一次研究报告与对比报告
```

注：本计划实施分支 `feat/fund-data-gap-closure` 从 `fix/collector-connect-retry`（领先 main 13 个 commit，含本计划依赖的对比报告与连接重试改动）拉出，而非 main。

## 实施状态（已完成）

- 阶段 1-4 全部落地；evidence 计数基线最终为：三基金 research 31（3×(8 采集 + 2 计算) + 1 基准指数）、空持仓 9。
- 与计划的两处偏差：评级核查发现雪球源"暂无评级"后，新增了 `/api/funds/{code}/rating` 端点（fund_rating_all 单页抓取 + 进程内缓存），两只目标基金均有第三方评级；`/api/index/{code}/daily` 落地时确认东财源需带市场前缀（sh000905），agent 的 get_index_data 直接收全符号。
- 评级、费率、资产配置、行业配置、同类排名渲染为确定性模板（费率与评级独立成章"## 费率与评级"，行业/资产配置并入持仓概览）。
- 同类排名复核后调整（用户确认）：数据源排名的"同类"按基金类型划分池子，跨类型基金的原始名次不可直接比较，故从"同类对比/核心指标对比"章节移出，并入"## 费率、评级与同类排名"每基金事实小节，渲染为池内分位（前 X%）+ 原始名次 + 各自类型标注，并附跨类型口径提示；单基金研究报告因此也能看到排名（此前挂在对比链路上反而不渲染）。
- Go 侧 SyncBenchmarkData 实现预置指数增量同步（CLI `sync benchmark`）；中证全债（000012）在东财源无对应 secid 时仅告警跳过。

