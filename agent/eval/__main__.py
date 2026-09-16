"""评测集入口（Phase 10）。

用法（在 agent/ 目录）：
    uv run python -m eval                    # offline：mock collector + fake LLM，CI 可跑
    uv run python -m eval --mode live        # live：真实 collector + 真实 LLM（质量门）
    uv run python -m eval --tag smoke        # 只跑 smoke 层
    uv run python -m eval --case research_single_normal

输出：每个 Case 一行 PASS / FAIL / SKIP（含失败检查明细），末尾汇总；有 FAIL 时退出码 1。
配置 LANGFUSE_* 时检查结果作为 scores 写入对应 trace；配置 TRACE_FILE 时同写本地 JSONL。
"""

import argparse
import sys

from eval.cases import CASES
from eval.runner import run_suite
from observability import make_default_trace_sink
from observability.sink import TraceSink

CASE_ID_WIDTH = 34

def _print_suite(suite) -> None:
    print(f"=== eval suite (mode={suite.mode}) ===")
    for r in suite.results:
        if r.skipped:
            print(f"SKIP {r.case_id:<{CASE_ID_WIDTH}} {r.skip_reason}")
            continue
        status = "PASS" if r.passed else "FAIL"
        print(f"{status} {r.case_id:<{CASE_ID_WIDTH}} ({len(r.checks) - len(r.failed_checks)}/{len(r.checks)} checks, {r.duration_ms:.0f}ms)")
        if r.error:
            print(f"     run error: {r.error}")
        for check in r.failed_checks:
            print(f"     - {check.name}: {check.detail}")
    print(
        f"=== {suite.passed_count}/{len(suite.executed)} passed, "
        f"{suite.skipped_count} skipped ==="
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="FundForge 评测集 runner（Phase 10）")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--tag", help="只跑包含该 tag 的 Case（smoke/core/edge/live...）")
    parser.add_argument("--case", dest="case_id", help="只跑指定 id 的 Case")
    parser.add_argument("--list", action="store_true", help="列出全部 Case 后退出")
    args = parser.parse_args()

    if args.list:
        for c in CASES:
            print(f"{c.id:<{CASE_ID_WIDTH}} [{','.join(c.tags)}] {c.name}")
        return

    sink: TraceSink | None = None
    try:
        sink = make_default_trace_sink()
        suite = run_suite(args.mode, tag=args.tag, case_id=args.case_id, sink=sink)
        _print_suite(suite)
    finally:
        shutdown = getattr(sink, "shutdown", None) if sink is not None else None
        if callable(shutdown):
            shutdown()

    if suite.failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
