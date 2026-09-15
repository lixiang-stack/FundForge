# ==================================
# 项目 AI 助手工作规范（AGENTS.md）
# ==================================

本文件定义各类 AI 助手（AGENTS/Claude Code 等）在本仓库工作时的行为准则。项目描述、架构、命令、配置等**业务相关**内容一律在 `README.md`、`cmd/README.md`、`agent/README.md` 与 `agent/docs/`；本文件只负责规范"AI 助手怎么做事"。

条款未特别说明语言的，Go 与 Python 均须遵守。

**适用尺度：** 本规范偏向"谨慎优先于速度"。琐碎改动（typo、单行修复等）可凭判断从简；但第五条（项目硬约束）与 1.6（破坏性操作前确认）在任何任务下都不豁免。

**结构导读（按工作生命周期排列）：** 第一~四条规范"怎么想、怎么写"（流程与代码行为）；第五条划定"不能碰的墙"（项目硬约束）；第六条规范"怎么验证"；第七~八条规范"怎么收尾"（文档与 Git）；第九~十条是环境与入口速查。

---

## 第一条：工作流程总纲（先思考，再动手）

**核心：** 动手之前把问题想清楚，把目标变成可验证的；不确定就问，绝不靠猜。

- **1.1 (读代码优先)**：被要求加功能 / 修 bug 时，第一步是读相关包（对照第五条约束与 README 的关键设计），然后才提方案或动手。
- **1.2 (显式假设，不靠猜)**：动手前显式陈述关键假设；同一需求存在多种合理解释时，把解释全部列出交用户选择，不要默默挑一个；有更简单的实现方案就直接提出并说明理由。
- **1.3 (不清楚就停下来问)**：需求含糊、与既有设计矛盾、依赖不明——点名"哪里不清楚"并提问，绝不带着困惑继续写。澄清性提问应发生在动手之前，而不是错误之后。
- **1.4 (目标驱动执行)**：把任务转成可验证的目标再动手：
  - "加校验" → 先写非法输入的测试，再让它通过；
  - "修 bug" → 先写复现该 bug 的测试，再让它通过；
  - "重构" → 重构前后测试同样通过。

  成功标准定义得越强，越能独立循环验证，而不是反复回头问"这样可以吗"。
- **1.5 (多步任务先列计划)**：跨 3 个以上文件的改动，先说明方案（数据流、每个文件的动作），经用户确认后再动手；多步任务列出分步计划，每一步带验证方式：

  ```
  1. [步骤] → 验证: [检查方式]
  2. [步骤] → 验证: [检查方式]
  ```
- **1.6 (破坏性操作前确认)**：`rm -rf`、`git reset --hard`、force push、删除文件、降级依赖等操作必须先向用户说明并等确认。

---

## 第二条：简单性原则

**核心：** 遵循"少即是多"哲学——写解决问题的最少代码，不做任何投机性设计，不引入非必需的依赖。

- **2.1 (YAGNI)**：只实现当前任务明确要求的功能；不给"未来可能的场景"预留 hook / flag / abstraction；不添加没人要求的"灵活性"或"可配置性"。
- **2.2 (依赖克制)**：不引入非必需的第三方依赖。Go 代码：标准库与 `go.mod` 已有依赖优先。Python 代码：agent 新增依赖必须进 `agent/pyproject.toml` 并由 `uv lock` 锁定，collector 仍用 `requirements.txt`，两种依赖管理方式不要混用；`uv.lock` 与 `pyproject.toml`、`go.sum` 与 `go.mod` 必须同一 commit 提交。
- **2.3 (反过度工程)**：简单的函数和数据结构优于复杂的接口和继承体系；不为一次性代码造抽象；三行相似代码好过一个"通用"抽象。自检："资深工程师会认为这段代码过度复杂吗？"——会，就简化；200 行能写成 50 行，就重写。

---

## 第三条：外科手术式修改

**核心：** 只改必须改的，只清理自己制造的垃圾；每一行改动都应能直接追溯到任务本身。

- **3.1 (不顺手"改进")**：不"改进"相邻的代码、注释或格式（包括补写没人要求的注释与文档）；不重构没有坏的东西；遵循既有代码风格，即使你有不同偏好。
- **3.2 (无关死代码只提及不删除)**：发现与任务无关的死代码，向用户提及即可；预先存在的死代码未经要求不删。
- **3.3 (只清理自己的孤儿)**：你的改动导致 imports / 变量 / 函数失去引用时，必须删除它们——这是收尾责任，不算"顺手改"。
- **3.4 (一次 commit 只做一件事)**：修 bug 不顺手改无关代码；改功能不顺手 refactor。

---

## 第四条：明确性原则

**核心：** 代码的首要目的是让人类易于理解。

- **4.1 (错误处理不可协商，但不过度防御)**：错误必须显式处理。Go 代码：传递用 `fmt.Errorf("...: %w", err)` 保留链路，绝不用 `_ = err` 丢信息。Python 代码：observability 层"故障只 log、降级不影响业务"是刻意设计（trace 丢失不能拖垮研究主流程），业务代码不得模仿它吞业务错误。同时，不给不可能发生的场景写防御性错误处理——信任内部代码与框架保证，只在系统边界（用户输入、外部 API）做校验；这与上一句不矛盾：不吞真实错误，也不防不存在的错误。
- **4.2 (无全局状态，显式装配)**：所有依赖经 struct 字段 / 接口注入；配置 env-only，默认值与 docker-compose 一致。Go 代码：DI 全部手动装配在 `cmd/server/main.go`——新增 repository / use case 必须在那里接线，否则不生效；配置在 `internal/config/config.go`。Python 代码：配置在 `agent/config.py`。
- **4.3 (副作用可见)**：网络请求、文件写入、外发请求等副作用必须在调用栈上可追。Python 代码：agent 对 collector / LLM 的调用只经 `agent/tools/` 与 `agent/llm/` 的 Provider 接口，不在节点里散落裸 HTTP。
- **4.4 (注释写"为什么"不写"是什么")**：只有"这里为什么这么写"（跨服务契约、历史踩坑、时区敏感、降级设计）值得写下来；函数名能讲清楚的不写。
- **4.5 (dict / 模型双形态归一化)**：Python 代码：LangGraph 回传的 State 值可能是 dict 也可能是 pydantic 模型——统一用 `agent/domain/shared.py` 的 `coerce_model` 归一化，禁止在业务代码里散落 isinstance 双形态判断。

---

## 第五条：项目硬约束

**核心：** 违反下列任一条都会破坏跨服务契约或线上行为；这些不是风格建议，是墙。

- **5.1 (六边形依赖方向不可逆)**：Go 代码：`cmd/*` → `internal/adapter` → `internal/application`（用例）→ `internal/domain`（实体 + 仓储接口）；`domain` 不得 import `adapter` / `application`。repository 接口定义在 domain 包，实现放 `internal/adapter/persistence/postgres`。
- **5.2 (跨语言契约清单)**：跨 Go / Python 的契约改动必须列出全部消费方并同步修改，已知三处：
  - collector `FIELD_MAPS` 的英文列名 ↔ Go DTO `internal/adapter/collector/dto.go`（`collector/main.py` 无业务逻辑，英文列名是跨服务契约）；
  - collector API 路径与响应结构 ↔ Go 客户端 `internal/adapter/collector/client.go`、Python 客户端 `agent/tools/collector_client.py`、CLI（`cmd/cli`）；
  - 改 collector 路由 / 字段前先 grep 全部消费方，一起改。Python 代码：agent 只经 collector API 取数，**严禁直连 akshare**。
- **5.3 (枚举双重约束)**：Go 代码：alert status/severity、strategy operators 等枚举同时存在于 DB CHECK 约束（migrations）与 domain 包类型常量，改动必须两处同步。
- **5.4 (迁移成对、路径硬编码)**：Go 代码：迁移文件 `migrations/NNNNNN_name.{up,down}.sql` 必须成对提供；server 启动自动执行迁移（`internal/adapter/persistence/postgres/db.go`，内部会把 DSN scheme `postgres://` 改写为 `pgx5://`），路径硬编码 `file://migrations`——server 必须以仓库根目录为工作目录运行。
- **5.5 (时区敏感)**：交易日逻辑依赖时区；容器统一 `TZ=Asia/Shanghai`。涉及"今天是否交易日 / 净值日期对齐"的改动，先想清楚运行环境的时区。
- **5.6 (domain 不依赖框架)**：Go 的 `internal/domain` 与 Python 的 `agent/domain/` 都不得 import 框架（LangGraph、LLM SDK 等）；LLM 只出现在 `agent/llm/` 与 thesis 节点（见 `agent/docs/TechnicalContract.md` 核心原则）。

---

## 第六条：测试与验证

**核心：** 提交前测试必须绿；优先测行为，不测实现细节；改动以测试锚定。

- **6.1 (改代码前先读测试)**：修既有函数前先看对应 `_test.go` / `tests/` 的断言——若测试覆盖了想改的行为，先决定"是改行为、还是补测试防止退化"。
- **6.2 (改动以测试锚定)**：修 bug 先写复现测试再修复（见 1.4）；失败测试要么修好、要么直接向用户说明，绝不"顺手"跳过或注释掉。
- **6.3 (提交前三件套)**：Go 代码：`go build ./...`、`go test ./... -count=1`、`go vet ./...` 零告警（仓库无 linter 配置，vet 是唯一额外检查）。
- **6.4 (mock 的位置)**：Go 代码：testify + 手写 mock，集中在 `internal/agent/http/testhelpers_test.go`——新增 domain 仓储接口必须同步更新那里的 mock，否则编译不过；无 DB 集成测试，单元测试不依赖容器。
- **6.5 (agent 测试分两层)**：Python 代码：单元测试 `uv --directory agent run pytest`（mock collector，无需任何服务）；`uv --directory agent run pytest -m integration` 需要真实 collector（`docker compose up -d collector`），默认跳过，失败注入也在这层。
- **6.6 (无 linter 约定)**：Python 代码：agent 侧当前无 ruff / mypy / formatter 约定——不要顺手引入；确需引入时单独一次 commit 说明，并同步本条。

---

## 第七条：文档管理

- **7.1 (文档分层)**：`README.md` 只承载"项目描述、目录结构、子文档索引"（项目完成后再充实）；组件细节在 `cmd/README.md`（Server/CLI/迁移/测试）与 `agent/README.md`（工作流/配置/可观测性/测试）；agent 设计文档在 `agent/docs/`。
- **7.2 (何时写文档)**：改动跨多个包 / 引入新的跨组件契约时才写；单文件修 bug 用 commit message 与代码注释即可，**不主动生成文档**。
- **7.3 (语言)**：用户可见文档（README、代码注释、SQL 注释、报告输出）用中文。

---

## 第八条：Git 与提交

- **8.1 (Conventional Commits)**：commit 用 `feat:` / `fix:` / `test:` 等前缀，一句话说清意图。
- **8.2 (不加 Co-authored-by)**：commit 末尾**不要**附加 Co-authored-by 署名。
- **8.3 (不主动 push)**：远程推送由用户决定；仅当用户明确要求时才 push（涉及已推送分支的改写用 `--force-with-lease`）。
- **8.4 (提交前跑测试)**：第六条的测试通过才提交。

---

## 第九条：技术栈与工具链

- **9.1 (Go 1.25)**：Gin（HTTP）、pgx/v5（PostgreSQL）、golang-migrate（迁移）、Zap（日志）。版本以 `go.mod` 为权威，不要动。
- **9.2 (Python 3.11)**：agent 依赖由 uv 管理（`pyproject.toml` + `uv.lock`），命令统一 `uv --directory agent ...`；collector 用 `requirements.txt`。
- **9.3 (容器拓扑)**：compose 服务——postgres `:5432`、collector `:8000`、server `:8080`，全部 `TZ=Asia/Shanghai`；`.env` 的容器主机名仅容器内有效。

---

## 第十条：项目上下文入口

每次开始工作前先扫一眼，无需重复其中内容：

- **`README.md`**：项目描述、目录结构、文档索引。
- **`cmd/README.md`**：Server 启动与 API 总览、CLI 全部子命令、数据库迁移。
- **`agent/README.md`**：LangGraph 工作流节点、目录结构、配置、可观测性、测试。
- **`agent/docs/*.md`**：Agent 相关文档。

---

**本规范有效的标志：** diff 中没有不必要的改动；没有因过度复杂导致的返工；澄清性提问发生在动手之前，而不是错误之后。
