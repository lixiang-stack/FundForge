"""FundForge Agent 节点集合（Node 合同见 docs/TechnicalContract.md §4）。"""

from nodes.analyzer import AnalyzerNode
from nodes.collector import CollectorNode
from nodes.evaluator import EvaluatorNode
from nodes.planner import extract_fund_codes, planner
from nodes.repair import RepairNode
from nodes.router import router
from nodes.synthesizer import synthesizer
from nodes.thesis import ThesisNode

__all__ = [
    "router",
    "planner",
    "extract_fund_codes",
    "CollectorNode",
    "AnalyzerNode",
    "ThesisNode",
    "EvaluatorNode",
    "RepairNode",
    "synthesizer",
]
