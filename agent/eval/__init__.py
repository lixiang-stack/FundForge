"""评测集（Phase 10）：给 Agent 的单元测试 + 集成测试，而不是给报告打分的主观比赛。

- eval.models    Case / 结果模型（schema）
- eval.checks    硬检查注册表（机器可判定，口径对齐 Evaluator）
- eval.mocks     collector mock 档位（数据缺失 / 失败注入）
- eval.fakes     确定性 Fake LLM（离线可复现）
- eval.cases     Case 定义（Python dict，无 YAML 依赖）
- eval.runner    Runner：Case → graph.invoke → 硬检查 → 汇总 + Langfuse scores
"""

from eval.models import CaseResult, CheckResult, CheckSpec, EvalCase, SuiteResult
from eval.runner import run_case, run_suite

__all__ = [
    "CaseResult",
    "CheckResult",
    "CheckSpec",
    "EvalCase",
    "SuiteResult",
    "run_case",
    "run_suite",
]
