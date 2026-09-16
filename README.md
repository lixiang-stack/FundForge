# FundForge

> 基金投资研究与组合决策平台：Go 后端 + Python 数据采集 + LangGraph AI 研究工作流

> 详细的功能特性、架构设计与使用说明见各子目录 README，此处只保留项目概览。

---

## 目录结构

```
├── cmd/           # Go 入口：server（REST API）、cli（管理工具）
├── internal/      # 六边形分层：adapter / application / domain / infra
├── migrations/    # golang-migrate SQL（up/down 成对）
├── collector/     # Python 数据采集服务（akshare → REST，覆盖公募基金净值/分红/拆分/日历）
├── agent/         # LangGraph AI 研究工作流（意图路由 → 采集 → 分析 → 论点 → 评估 → 报告；设计文档在 agent/docs/）
└── docker-compose.yml
```

---

## 文档索引

| 文档 | 内容 |
| ---- | ---- |
| [`cmd/README.md`](cmd/README.md) | Server 启动与 API 总览、CLI 全部子命令、环境变量、数据库迁移、测试 |
| [`agent/README.md`](agent/README.md) | LangGraph 工作流节点、目录结构、配置、可观测性、测试、设计文档 |
| [`AGENTS.md`](AGENTS.md) | AI 助手协作规范 |

---

## License

Private project. All rights reserved.
