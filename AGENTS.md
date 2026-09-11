# AGENTS.md

## What this is

FundForge — fund investment research platform. Go 1.25 backend (`cmd/server` REST API, `cmd/cli` admin tool), a Python 3.11 collector (`collector/`, thin FastAPI wrapper around akshare), and a LangGraph agent (`agent/`, the AI research workflow per `docs/Plan.md`). PostgreSQL via pgx/v5. Docs, comments, and SQL comments are largely Chinese — keep that style in user-facing docs.

## Architecture (hexagonal)

Dependency direction: `cmd/*` → `internal/adapter` → `internal/application` (use cases) → `internal/domain` (entities + repository/provider interfaces). `internal/infra` holds cross-cutting helpers (zap logger, retry, circuit breaker).

- Domain packages: `internal/domain/{fund,nav,alert,strategy,benchmark,calendar,marketdata,shared}`. Repository interfaces live in the domain package; implementations in `internal/adapter/persistence/postgres`.
- HTTP routes: `internal/adapter/http/router.go`. All DI is manual in `cmd/server/main.go` — a new repo/use case must be wired there.
- Collector boundary: `collector/main.py` contains no business logic. `FIELD_MAPS` in it translates Chinese akshare column names to English; those English names are the cross-service contract, mirrored by Go DTOs in `internal/adapter/collector/dto.go`. Keep both sides in sync. The LangGraph agent (`agent/tools/`) also gets data only through the collector API — never call akshare directly in the agent.

## Commands

```bash
go test ./... -count=1             # unit tests only; no DB or containers needed
go vet ./...                       # no linter config exists; this is the only extra check
go build -o server ./cmd/server    # MUST run from repo root (migrations path is relative: file://migrations)
go build -o client ./cmd/cli
uv --directory agent sync          # agent deps are managed by uv (pyproject.toml + uv.lock; collector still uses requirements.txt)
uv --directory agent run python main.py "查询"   # run the agent workflow skeleton
uv --directory agent run pytest    # agent unit tests (mocked collector, no services needed)
docker compose up -d               # full stack: postgres :5432, collector :8000, server :8080
```

Local dev against containers: `docker compose up -d postgres collector`, then export `DATABASE_URL=postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable` and `COLLECTOR_BASE_URL=http://localhost:8000`. The `.env` file uses container hostnames (`postgres`, `collector`) — only valid inside containers, not for host-run binaries (sourcing it on the host breaks collector access; override `COLLECTOR_BASE_URL` after sourcing).

Agent LLM (thesis node): `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (OpenAI-compatible chat/completions, e.g. DeepSeek). Unconfigured → thesis node degrades gracefully (no thesis, issue recorded).

## Migrations

golang-migrate, files `migrations/NNNNNN_name.{up,down}.sql`. Server auto-applies on startup (`internal/adapter/persistence/postgres/db.go`, which rewrites the DSN scheme `postgres://` → `pgx5://`). The CLI can apply them via `./client migrate` with `MIGRATIONS_PATH` set. Always write both up and down files.

## Conventions

- Config is env-only (`internal/config/config.go`); defaults match the docker-compose dev values.
- Enums (alert status/severity, strategy operators) are enforced twice: DB CHECK constraints in migrations and typed constants in domain packages. Change both together.
- Trading-day logic is timezone-sensitive; containers run with `TZ=Asia/Shanghai`.
- Tests use testify with hand-rolled mock repos in `internal/adapter/http/testhelpers_test.go` — a new domain repository interface means updating the mocks there. No DB integration tests exist.
- Commits follow conventional style (`feat: ...`).
- `docs/TechnicalContract.md` defines the planned LangGraph AI-agent layer; its core principle: the domain layer must not depend on frameworks.
