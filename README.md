# FundForge

> An AI Agent for fund investment research and portfolio decision support

---

## 功能特性

**数据采集**
- 抓取 26,000+ 只公募基金的净值、分红、拆分数据
- 支持单基金全量初始化（成立来）和已订阅基金每日增量更新
- 交易日历同步与管理（提供 `IsTradingDay` 等交易日感知查询接口）
- 基金经理变更自动检测

**策略分析**
- 14 个量化指标（最大回撤、波动率、夏普比率、Beta、超额收益、区间滚动收益等）
- 策略条件模板（AND/OR 逻辑组合）
- 三级告警严重度（Critical / Warning / Info）
- 告警状态机：触发 → 确认 → 恢复

**API**
- REST API 提供基金、策略、告警能力
- 支持 CLI 管理（订阅、同步、分析、告警）

---

## 技术栈

| 层级     | 技术                                      |
| -------- | ----------------------------------------- |
| 后端     | Go 1.25, Gin, pgx/v5, golang-migrate, Zap |
| 数据库   | PostgreSQL 15+                            |
| 数据采集 | Python 3.11, FastAPI, akshare             |
| 部署     | Docker, Docker Compose                    |

---

## 快速开始

### Docker Compose 一键启动

```bash
docker compose up -d
```

服务全部容器化：

| 服务       | 端口 | 说明            |
| ---------- | ---- | --------------- |
| PostgreSQL | 5432 | 数据库          |
| Collector  | 8000 | Python 数据采集 |
| Server     | 8080 | Go API 后端     |

### 组件文档

- **Server（REST API）**：详见 [`cmd/server/README.md`](cmd/server/README.md) —— 启动方式、环境变量、API 能力总览
- **CLI（管理工具）**：详见 [`cmd/cli/README.md`](cmd/cli/README.md) —— 编译与配置、全部子命令示例

---

## 测试

```bash
# Go 单元测试
go test ./... -count=1
```

---

## License

Private project. All rights reserved.