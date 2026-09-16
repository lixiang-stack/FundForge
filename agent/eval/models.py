"""评测 Case 与结果模型（Phase 10）。

Case = 输入（query / 期望 fund_ids）+ 执行档位（collector / llm）+ 机器可判定检查点（checks）。
检查点口径对齐 Evaluator（Evidence 绑定、覆盖率、data_gaps 披露、免责声明），避免两套标准。
Case 用 Python dict 维护在 eval/cases.py（无 YAML 依赖，类型与 IDE 校验直通）。
"""

from typing import Any

from pydantic import BaseModel, Field


class CheckSpec(BaseModel):
    """单条检查点：name 对应 eval/checks.py 注册表键，params 传参。"""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class EvalCase(BaseModel):
    """一个评测 Case。"""

    id: str
    name: str
    note: str = ""  # 一句话说明本 Case 防什么回归（Plan.md 验收要求）
    query: str
    fund_ids: list[str] = Field(default_factory=list)  # 期望 planner 提取的基金代码（按序）
    peer_fund_ids: list[str] = Field(default_factory=list)
    # 执行档位：
    # collector = "real"（需运行中的 collector 服务）或 eval/mocks.py 档位名
    # llm = "fake" | "fake_bad_binding"（确定性，离线可跑）| "real"（需 LLM_* 配置）
    collector: str = "mock_ok"
    llm: str = "fake"
    checks: list[CheckSpec]
    tags: list[str] = Field(default_factory=list)  # smoke / core / edge / live


class CheckResult(BaseModel):
    """单条检查点的执行结果。"""

    name: str
    passed: bool
    detail: str = ""


class CaseResult(BaseModel):
    """单个 Case 的执行结果。"""

    case_id: str
    passed: bool = False
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""  # graph.invoke 抛出异常时非空
    duration_ms: float = 0.0
    request_id: str = ""
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


class SuiteResult(BaseModel):
    """一次评测运行（多个 Case）的汇总。"""

    mode: str
    results: list[CaseResult] = Field(default_factory=list)

    @property
    def executed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.skipped]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.executed if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.executed if not r.passed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.skipped)


__all__ = ["CaseResult", "CheckResult", "CheckSpec", "EvalCase", "SuiteResult"]
