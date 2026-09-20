# /detail 端点 ACL 补全：中文 item 名收口到 collector

## 背景与问题

`collector/main.py` 的 `FIELD_MAPS` 是 ACL（中文→英文字段名），但雪球端点 `/api/funds/{code}/detail`（`fund_individual_basic_info_xq`）调用 `df_to_response(df)` 未传 mapping key，中文 item 名穿透到两侧消费方：

- **Go** `internal/adapter/collector/dto.go:109-118` `convertFundDetail` 用中文 key 读值，且有两个**死键真 bug**：读 `基金规模`（真实 item 是 `最新规模`）→ `Size` 恒 0；读 `业绩基准`（真实 item 是 `业绩比较基准`）→ `Benchmark` 恒空。
- **Agent** `agent/tools/fund_tools.py:87-100` 13 个 `kv.get("中文名")`，正确性靠测试 fixture 照抄雪球返回锚定（历史上已因键名漂移出过 bug，见 `agent/docs/fund-domain-cleanup-and-nav-fix.md:6`）。
- **技术细节**：detail 返回 `{item, value}` 行，中文在 **item 列的值**里，`df.rename(columns=...)` 无效——collector 需要对 item 列值做映射的辅助函数。

真实 item 名全集（`agent/tests/conftest.py:16-31` DETAIL_ROWS，14 项）：`基金代码、基金名称、基金全称、成立时间、最新规模、基金经理、基金类型、基金公司、托管银行、评级机构、基金评级、投资策略、投资目标、业绩比较基准`。

## 契约消费方清单（5.2 全量 grep 结论）

- Go client（`internal/adapter/collector/client.go`）消费 5 个端点：nav / trade-calendar / **detail** / dividends / splits。前四个 ACL 已完好（FIELD_MAPS 已覆盖）。
- Agent（`agent/tools/collector_client.py`）消费 4 个：fund list / **detail** / nav / holdings/stock。其余三个已英文。
- CLI（`cmd/cli/main.go`）经 use case 间接调用，不解析字段名。
- `/rules` 及 realtime、estimation 等 6 个端点**零消费方**——本次不动（YAGNI，用户已确认）。
- 不动的还有：`indicator=单位净值走势` 中文**请求参数**（akshare 自身枚举契约，非响应字段名）；Go `FundDetail` 的 `ManagementFee/CustodianFee/SizeDate`（雪球源无对应 item，恒空是既有事实）。

## 改动方案

### 1. collector/main.py（ACL 收口点）

- `FIELD_MAPS` 增加 `fund_detail` 条目（语义：item 列**值**的映射，注释说明 kv 端点用法）：

  ```python
  "fund_detail": {          # 雪球 fund_individual_basic_info_xq：{item, value} 行，映射作用于 item 值
      "基金代码": "fund_code",     "基金名称": "fund_name",       "基金全称": "fund_full_name",
      "成立时间": "inception_date", "最新规模": "aum",            "基金经理": "fund_manager",
      "基金类型": "fund_type",     "基金公司": "fund_company",    "托管银行": "custodian_bank",
      "评级机构": "rating_agency", "基金评级": "fund_rating",
      "投资策略": "investment_strategy", "投资目标": "investment_objective",
      "业绩比较基准": "benchmark",
  },
  ```

  键名对齐 agent `Fund` 模型与 Go `FundDetail` 既有字段（aum/inception_date/fund_company 等为新定，两侧消费方同步采用）。
- 新增辅助函数 `df_to_kv_response(df, mapping_key)`：复制 df，将 `item` 列的值经 `FIELD_MAPS[mapping_key]` 映射（**未命中的 item 原样透传**——雪球源可能新增条目，消费方忽略未知键即可），其余序列化逻辑与 `df_to_response` 一致。
- `get_fund_detail`（main.py:210-215）改用 `df_to_kv_response(df, "fund_detail")`。

### 2. internal/adapter/collector/dto.go（Go 消费方同步）

`convertFundDetail`（L109-118）中文 key 全部换英文：

```go
detail.Name = kv["fund_name"]
detail.FundType = kv["fund_type"]
detail.Company = kv["fund_company"]
detail.Manager = kv["fund_manager"]
detail.CustodianBank = kv["custodian_bank"]
detail.Benchmark = kv["benchmark"]
if v, ok := kv["aum"]; ok { detail.Size = parseFloatFromStr(v) }          // 修死键：原读 "基金规模"
if v, ok := kv["inception_date"]; ok { ... }                              // 原 "成立时间"
```

`parseFloatFromStr("44.16亿")` → 44.16，与 agent `_parse_aum` 行为一致，无需改。

### 3. 新增 internal/adapter/collector/dto_test.go（6.1：该包当前 0 测试）

- `TestConvertFundDetail`：fixture 仿 `conftest.py` DETAIL_ROWS（英文 item），断言 Name/FundType/Company/Manager/CustodianBank/Benchmark/Size(44.16)/EstablishDate(2016-04-22) —— **先跑会红**（aum/benchmark 键不存在时 Size=0、Benchmark=""，即复现两个死键 bug），再随 dto.go 修改转绿。
- `TestConvertFundDetail_Empty`：空输入 → nil。

### 4. agent/tools/fund_tools.py:87-100（Python 消费方同步）

13 个 `kv.get("中文名")` 改英文：`fund_name / fund_type / fund_manager / inception_date / aum（去掉 "最新规模" or "基金规模" 双键兜底，只读 aum）/ benchmark / fund_company / fund_full_name / custodian_bank / rating_agency / fund_rating / investment_strategy / investment_objective`。

### 5. agent 三份 fixture 同步改英文 item

- `agent/tests/conftest.py:16-31` `DETAIL_ROWS`（14 项）
- `agent/tests/test_fund_tools.py:47` partial fixture（`基金代码→fund_code`、`基金名称→fund_name`）
- `agent/eval/mocks.py:21-29` `DETAIL_ROWS`（7 项）

下游 `test_thesis / test_graph / test_observability / test_nodes` 只断言 `Fund` 字段，不受影响。

### 6. collector/tests/ 新增映射测试

新增 `collector/tests/test_detail_acl.py`（沿 `test_holdings_year.py` 的组织方式）：中文 item DataFrame 经 `df_to_kv_response` 后 item 全部为英文、未知 item 透传、空 df 返回 `[]`。命令：`uv --directory collector run pytest`。

### 7. 文档一句话（7.2：跨组件契约变更）

`cmd/README.md` Fund management / Data synchronization 表中 `/api/funds/%s/detail` 所在行加注：响应 item 名已由 FIELD_MAPS 标准化为英文（中文 item 不再透传）。

## 明确不做

- `/rules` 及其余 6 个无消费端点不加映射；`/rules` 为既有死端点，只在此提及不删除（3.2）。
- Go 侧 `FetchFundNAV` 的中文 indicator 请求参数不改（akshare 枚举契约）。
- 不动 `agent/docs/fund-domain-cleanup-and-nav-fix.md`（历史记录）。
- 已落库的旧基金 size=0/benchmark 为空不会自动修复——需重跑 `fund subscribe` / `sync managers` 才会带新值（向用户知悉，不在本次范围）。

## 验证

1. `uv --directory collector run pytest` — 新 ACL 测试 + 既有 test_holdings_year 绿。
2. `go build ./... && go test ./... -count=1 && go vet ./...`（6.2 三件套）—— dto_test.go 先红后绿。
3. `uv --directory agent run pytest` — 全量单测绿（fixture 已同步）。
4. 真机抽查（可选但推荐）：`docker compose up -d collector` 后 `curl localhost:8000/api/funds/519770/detail`，确认 item 为英文；再跑 `uv --directory agent run pytest -m integration`（`test_integration.py:63` 断言 data_quality=complete，端到端验证真实雪球 item 命中映射）。

## Commit

一次 commit（5.2 一次同步修改）：`fix(collector): complete ACL mapping for fund detail endpoint`——body 说明死键修复（Size/Benchmark）与 Go/agent 消费方、fixture 的一次性同步；不附 Co-authored-by（8.2）。
