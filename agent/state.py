"""FundForgeState — Agent 工作流的任务上下文。

完整 State 合同见 docs/TechnicalContract.md §2：
- 只保存跨 Node 真正需要共享的摘要与 ID；
- 不保存 LLM Client、DB Connection、Tool Instance 等运行时对象；
- evidence 只允许追加。

Phase 0：仅保留空流程骨架所需的最小字段。
"""

from typing import TypedDict


class FundForgeState(TypedDict, total=False):
    request_id: str
    user_query: str
    report: str
