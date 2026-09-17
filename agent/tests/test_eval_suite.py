"""Phase 10 评测集离线回归（pytest 常驻锚点）。

offline 模式 = mock collector + fake LLM，确定性、零外部依赖；
与 `uv run python -m eval` 跑的是同一套 Case 定义与检查点（单一事实来源）。
"""

from eval.cases import CASES
from eval.runner import run_suite


def test_offline_suite_all_pass():
    suite = run_suite("offline")
    fake_cases = [c for c in CASES if c.llm.startswith("fake")]
    # live 档位 Case 在 offline 模式下跳过，其余全部执行且稳定通过
    assert suite.skipped_count == len(CASES) - len(fake_cases)
    assert suite.passed_count == len(fake_cases), "\n".join(
        f"{r.case_id} / {c.name}: {c.detail}"
        for r in suite.executed
        for c in r.failed_checks
    )
    assert suite.failed_count == 0
