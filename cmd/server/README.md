## Server 服务概览

FundForge 的 Go 后端服务（Gin），对外提供 REST API，负责基金、策略、告警等业务能力。

### 运行必备条件

* 启动依赖服务（PostgreSQL + Collector）
```bash
docker compose up -d
```

* 配置环境变量
```
export DATABASE_URL="postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable"
export COLLECTOR_BASE_URL=http://localhost:8000
```

`DATABASE_URL` 默认指向 `localhost`（宿主机直连本地 Postgres）。若在容器内运行，主机名使用 `postgres`、`collector`。

### 启动

```bash
cd 项目根目录
go build -o server ./cmd/server && ./server
```

启动时自动执行数据库迁移（`file://migrations`，需在项目根目录下运行），随后监听 `SERVER_PORT`（默认 `8080`）。

---

## API 能力总览

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

---

## 说明

* 除 `/health` 外，业务 API 无鉴权，为内部接口。
* 告警状态机：触发(triggered) → 确认(confirmed) / 忽略(ignored) / 恢复(recovered)。
* 迁移路径在 server 中硬编码为 `file://migrations`，需在项目根目录执行二进制。