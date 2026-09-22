"""运行上限常量（统一定义，各处引用，调整只改本文件）。

- Thesis 输出体量：LLM 生成耗时近似线性于输出 token 数，压缩输出即压缩耗时；
- LLM 生成：单次请求的输出 token 硬上限，防止失控生成（截断由节点层降级处理）；
- Collector 并发：只并发调用既有外呼出口（tools/），不改变外呼收敛约定。
"""

# ---- Thesis 输出体量（写入 Thesis 提示词） ----
THESIS_MAX_CLAIMS = 5  # claims 条数上限
THESIS_MAX_SUMMARY_CHARS = 200  # summary / suitability 单字段字数上限
THESIS_MAX_LIST_ITEMS = 5  # positives / negatives / risks / key_assumptions / data_gaps 条数上限
THESIS_MAX_ITEM_CHARS = 80  # 上述列表单条文本字数上限

# ---- LLM 生成 ----
LLM_MAX_TOKENS = 8000  # chat/completions 输出 token 上限（4000 实测会被长 thesis 输出截断）

# ---- Collector 并发 ----
COLLECTOR_FUND_CONCURRENCY = 4  # 同时采集的基金数上限
COLLECTOR_TOOL_CONCURRENCY = 3  # 单只基金内部并发数（info / performance / holdings）

__all__ = [
    "THESIS_MAX_CLAIMS",
    "THESIS_MAX_SUMMARY_CHARS",
    "THESIS_MAX_LIST_ITEMS",
    "THESIS_MAX_ITEM_CHARS",
    "LLM_MAX_TOKENS",
    "COLLECTOR_FUND_CONCURRENCY",
    "COLLECTOR_TOOL_CONCURRENCY",
]
