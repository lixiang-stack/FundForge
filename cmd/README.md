# cmd — Go 后端组件

FundForge 的 Go 后端（Go 1.25 / Gin / pgx/v5 / golang-migrate / Zap），面向基金订阅、净值同步、策略量化分析（14 个量化指标、AND/OR 条件模板）与三级告警（Critical / Warning / Info）。采用六边形架构：`cmd/*` → `internal/adapter` → `internal/application`（用例）→ `internal/domain`（实体 + 仓储接口），`internal/infra` 提供横切能力（zap 日志、重试、熔断）。

由两个二进制组成：

| 二进制 | 目录        | 说明                                     |
| ------ | ----------- | ---------------------------------------- |
| server | `cmd/server` | Gin REST API 后端（基金 / 策略 / 告警）   |
| client | `cmd/cli`    | 管理 CLI（订阅 / 同步 / 策略 / 告警 / 迁移） |

---

## 硬性约定（改代码前必读）

* **装配点**：DI 全部手动装配在 `cmd/server/main.go`——新增 repository / use case 必须在那里接线，否则不生效。
* **枚举双重约束**：alert status/severity、strategy operators 等枚举同时存在于 DB CHECK 约束（migrations）与 domain 包类型常量，改动必须两处同步。
* **时区敏感**：交易日 / 净值日期对齐逻辑依赖时区；容器统一 `TZ=Asia/Shanghai`，涉及"今天是否交易日"的改动先确认运行环境的时区。

---

## 运行必备条件（两者通用）

* 启动依赖服务（PostgreSQL + Collector，`server` 容器化部署时随 compose 一起启动）

```bash
docker compose up -d
```

* 配置环境变量（宿主机运行二进制时）

```bash
export DATABASE_URL="postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable"
export COLLECTOR_BASE_URL=http://localhost:8000
```

`DATABASE_URL` 默认指向 `localhost`（宿主机直连本地 Postgres）。若在容器内运行，主机名使用 `postgres`、`collector`（与 `.env` 一致）。

### 环境变量

| 变量 | 作用 | 默认值 |
| ---- | ---- | ------ |
| `DATABASE_URL` | PostgreSQL 连接串 | compose 内 `postgres:5432` |
| `COLLECTOR_BASE_URL` | Collector API 地址 | `http://localhost:8000` |
| `SERVER_PORT` | Server 监听端口 | `8080` |
| `MIGRATIONS_PATH` | CLI 手动迁移路径 | server 内置 `file://migrations` |

---

## 构建

统一从**仓库根目录**构建（server 的迁移路径硬编码为 `file://migrations`，必须以根目录为工作目录运行）：

```bash
go build -o server ./cmd/server
go build -o client ./cmd/cli
```

---

## Server（cmd/server）

### 启动

```bash
./server
```

启动时自动执行数据库迁移（`file://migrations`），随后监听 `SERVER_PORT`（默认 `8080`）。

### API 能力总览

| 能力 | 方法 | 路径 | 说明 |
| ---- | ---- | ---- | ---- |
| 健康检查 | GET | `/health` | 服务健康检查 |
| **基金** | | | |
| 列表已订阅基金 | GET | `/api/funds` | 已订阅基金列表 |
| 列表全部基金 | GET | `/api/funds/all` | 全部基金（已订阅 + 未订阅）|
| 订阅基金 | POST | `/api/funds` | 订阅基金（请求体 `{"fund_code": "..."}`，写入 fund_info）|
| 添加基金到关注列表 | POST | `/api/funds/add` | 加入关注但不订阅（同上请求体）|
| 基金详情（含指标+最新净值） | GET | `/api/funds/:code` | 返回量化指标快照和最新净值 |
| 退订基金 | DELETE | `/api/funds/:code` | 软退订（标记未订阅）|
| 硬删除基金 | DELETE | `/api/funds/:code/remove` | 物理删除记录 |
| 基金净值历史 | GET | `/api/funds/:code/nav?start=&end=` | NAV 历史，默认近 1 年 |
| 搜索基金 | GET | `/api/funds/search?q=&limit=` | 按代码/名称/拼音搜索 |
| **策略** | | | |
| 策略列表 | GET | `/api/strategies` | 全部策略模板 |
| 策略详情 | GET | `/api/strategies/:id` | 单策略模板 |
| 更新策略 | PUT | `/api/strategies/:id` | 修改策略模板（PUT，需请求体）|
| 删除策略 | DELETE | `/api/strategies/:id` | 删除策略模板 |
| 绑定基金到策略 | POST | `/api/strategies/:id/bindings` | 建立策略-基金绑定（请求体 `{"fund_code": "..."}`）|
| 策略绑定列表 | GET | `/api/strategies/:id/bindings` | 查看策略下绑定的基金 |
| 解除策略绑定 | DELETE | `/api/strategies/:id/bindings/:code` | 移除绑定 |
| **告警** | | | |
| 活跃告警列表 | GET | `/api/alerts` | triggered / confirmed 状态的告警 |
| 按基金查询告警 | GET | `/api/alerts/fund/:code` | 某基金的告警 |
| 确认告警 | POST | `/api/alerts/:id/confirm` | 触发 → 确认 |
| 忽略告警 | POST | `/api/alerts/:id/ignore` | 触发 → 忽略 |

### 说明

* 除 `/health` 外，业务 API 无鉴权，为内部接口。
* 告警状态机：触发(triggered) → 确认(confirmed) / 忽略(ignored) / 恢复(recovered)。

---

## CLI（cmd/cli）

### 编译与配置

```bash
cd cmd/cli
go build -o client .
```

客户端使用 `localhost` 通信（默认为容器内通信，需覆盖）：

```bash
export COLLECTOR_BASE_URL=http://localhost:8000
export DATABASE_URL="postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable"
```

### Fund management

| Commands                         | example                          | collector api        | table     |
| -------------------------------- | -------------------------------- | -------------------- | --------- |
| Subscribe to a fund              | ./client fund subscribe 519770   | /api/funds/%s/detail | fund_info |
| Unsubscribe from a fund          | ./client fund unsubscribe 519770 | -                    | fund_info |
| Search funds by code/name/pinyin | ./client fund search 519770      | -                    | fund_info |
| List subscribed funds            | ./client fund list               | -                    | fund_info |

> The `/api/funds/%s/detail` response is normalized by the collector's FIELD_MAPS ACL (`collector/main.py`): item names are English (`fund_name`, `aum`, ...), Chinese items are no longer passed through.

### Data synchronization

| Commands                                        | example                  | collector api                            | table                              |
| ----------------------------------------------- | ------------------------ | ---------------------------------------- | ---------------------------------- |
| Sync trade calendar                             | ./client sync calendar   | /api/trade-calendar                      | trade_calendar                     |
| Sync dividends and splits                       | ./client sync dividends  | /api/funds/dividends,/api/funds/splits   | fund_info,fund_dividend,fund_split |
| Detect fund manager changes                     | ./client sync managers   | /api/funds/%s/detail                     | fund_info                          |
| Fetch historical NAV for a fund                 | ./client sync nav 519770 | /api/funds/%s/nav?indicator=%s&period=%s | fund_info,fund_nav                 |
| Incremental NAV update for all subscribed funds | ./client sync update     | /api/funds/%s/nav?indicator=%s&period=%s | fund_info,fund_nav                 |
| Sync benchmark index daily data                 | ./client sync benchmark  | /api/index/%s/daily                      | benchmark_index_daily              |

> `sync benchmark` 拉取 `benchmark_index` 表中全部预置指数的日线（回溯 11 年，覆盖 agent 侧 10 年对齐窗口），供 alert 指标（beta/excess_return）使用；单指数失败仅告警跳过，不中断。

### Strategy management

| Commands                  | example                           | collector api | table             |
| ------------------------- | --------------------------------- | ------------- | ----------------- |
| List all strategies       | ./client strategy list            | -             | strategy_template |
| Bind strategy to fund     | ./client strategy bind 1 519770   | -             | strategy_binding  |
| List bindings for a fund  | ./client strategy bindings 519770 | -             | strategy_binding  |
| Unbind strategy from fund | ./client strategy unbind 1 519770 | -             | strategy_binding  |

### Strategy analysis

| Commands                                  | example                            | collector api | table                                                                                             |
| ----------------------------------------- | ---------------------------------- | ------------- | ------------------------------------------------------------------------------------------------- |
| Run analysis on a single fund             | ./client analyze run 519770        | -             | fund_info,fund_nav,benchmark_index,benchmark_index_daily,strategy_binding,strategy_template,alert |
| Compute and display indicators for a fund | ./client analyze indicators 519770 | -             | fund_nav, fund_info,benchmark_index, benchmark_index_daily                                        |
| Run full analysis on all subscribed funds | ./client analyze all               | -             | fund_info,fund_nav,benchmark_index,benchmark_index_daily,strategy_binding,strategy_template,alert |

### Alert management

| Commands           | example                  | collector api | table |
| ------------------ | ------------------------ | ------------- | ----- |
| List active alerts | ./client alert list      | -             | alert |
| Confirm an alert   | ./client alert confirm 1 | -             | alert |
| Ignore an alert    | ./client alert ignore 1  | -             | alert |

---

## 数据库迁移

* server 启动时自动执行（`file://migrations`，因此必须在仓库根目录运行）。
* CLI 也可手动执行：

```bash
export MIGRATIONS_PATH="file:///path/to/FundForge/migrations"
./client migrate
```

迁移文件为 `migrations/NNNNNN_name.{up,down}.sql`，up 与 down 必须成对提供。server 启动自动迁移时会把 DSN scheme `postgres://` 改写为 `pgx5://`（pgx/v5 连接协议，见 `internal/adapter/persistence/postgres/db.go`）。

---

## 测试（Go）

```bash
go build ./...            # 编译检查
go test ./... -count=1    # 单元测试（无 DB / 容器依赖）
go vet ./...              # 仓库无 linter 配置，vet 是唯一额外检查
```

* mock 约定：testify + 手写 mock，集中在 `internal/adapter/http/testhelpers_test.go`——新增 domain 仓储接口必须同步更新那里的 mock，否则编译不过。
