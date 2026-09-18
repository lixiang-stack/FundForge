"""main 运行记录落盘测试（P3）：output/<request_id>.md 过程在前、最终报告在后。"""

from datetime import datetime

import main as main_module
from observability.models import RunTrace
from observability.sink import NullTraceSink


def _trace() -> RunTrace:
    return RunTrace(
        request_id="req-test",
        user_query="对比 015453 和 519770 的表现",
        started_at=datetime(2026, 9, 17, 19, 30, 23),
        finished_at=datetime(2026, 9, 17, 19, 30, 39),
    )


def _state() -> dict:
    return {
        "request_id": "req-test",
        "user_query": "对比 015453 和 519770 的表现",
        "task_type": "fund_comparison",
        "tool_calls": [
            {
                "tool_name": "get_fund_info",
                "arguments": {"fund_id": "015453"},
                "started_at": "2026-09-17T19:30:23",
                "finished_at": "2026-09-17T19:30:24",
                "success": True,
            }
        ],
        "llm_interactions": [
            {
                "node": "thesis",
                "model": "deepseek-chat",
                "prompt": "[system]\n你是基金投资研究员",
                "response": '{"summary": "ok"}',
                "input_tokens": 10,
                "output_tokens": 5,
                "ok": True,
            }
        ],
        "evidence": [{"id": "ev-1", "evidence_type": "fund_data", "source": "s", "value": {"a": 1}}],
        "data_quality_issues": ["015453: 股票持仓最新报告期为 2024年1季度股票投资明细，非当前年度披露"],
        "report": {
            "title": "FundForge 基金研究报告：测试（015453）",
            "generated_at": "2026-09-17T19:30:37",
            "request_id": "req-test",
            "executive_summary": "摘要",
        },
    }


class TestWriteRunOutput:
    def test_success_writes_process_then_report(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main_module, "_OUTPUT_DIR", tmp_path)
        path = main_module._write_run_output(_state(), _trace(), NullTraceSink())

        assert path is not None and path.exists() and path.name == "req-test.md"
        text = path.read_text(encoding="utf-8")
        # 结构：运行头 → 分析过程 → 最终报告在最后
        assert text.index("# FundForge 运行记录") < text.index("### 1.3 LLM 输入 / 输出")
        assert text.index("### 1.3 LLM 输入 / 输出") < text.index("## 2. 最终报告")
        assert "你是基金投资研究员" in text          # LLM 输入全文
        assert '"summary": "ok"' in text            # LLM 输出全文
        assert "deepseek-chat" in text
        assert "015453: 股票持仓最新报告期" in text   # 数据质量问题透出
        assert "# FundForge 基金研究报告" in text    # 最终报告 markdown

    def test_failure_writes_partial_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main_module, "_OUTPUT_DIR", tmp_path)
        state = {"request_id": "req-fail", "user_query": "q"}  # 无 report / evidence
        path = main_module._write_run_output(state, _trace(), NullTraceSink(), error="RuntimeError: boom")

        assert path is not None and path.exists() and path.name == "req-fail.md"
        text = path.read_text(encoding="utf-8")
        assert "失败" in text and "RuntimeError: boom" in text
        assert "（未生成报告" in text

    def test_write_failure_returns_none(self, tmp_path, monkeypatch):
        # 输出过程抛异常不冒泡：返回 None 并仅记日志
        monkeypatch.setattr(main_module, "_OUTPUT_DIR", tmp_path / "out")

        def _boom(*_args):
            raise RuntimeError("x")

        monkeypatch.setattr(main_module, "coerce_model", _boom)
        path = main_module._write_run_output(_state(), _trace(), NullTraceSink())
        assert path is None
