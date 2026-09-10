"""FundForge Agent 节点集合（Node 合同见 docs/TechnicalContract.md §4）。"""

from nodes.collector import CollectorNode
from nodes.planner import extract_fund_codes, planner
from nodes.router import router
from nodes.synthesizer import synthesizer

__all__ = [
    "router",
    "planner",
    "extract_fund_codes",
    "CollectorNode",
    "synthesizer",
]
