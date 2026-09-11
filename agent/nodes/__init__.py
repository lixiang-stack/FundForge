"""FundForge Agent 节点集合（Node 合同见 docs/TechnicalContract.md §4）。

所有节点统一为 XxxNode 可调用类形式（__call__ 进节点），
输出契约由各节点模块内的 TypedDict 显式定义。
"""

from nodes.analyzer import AnalyzerNode, AnalyzerOutput
from nodes.collector import CollectorNode, CollectorOutput
from nodes.evaluator import EvaluatorNode, EvaluatorOutput
from nodes.planner import PlannerNode, PlannerOutput, extract_fund_codes
from nodes.repair import RepairNode, RepairOutput
from nodes.researcher import ResearcherNode, ResearcherOutput
from nodes.router import RouterNode, RouterOutput
from nodes.synthesizer import SynthesizerNode, SynthesizerOutput
from nodes.thesis import ThesisNode, ThesisOutput

__all__ = [
    "RouterNode",
    "RouterOutput",
    "PlannerNode",
    "PlannerOutput",
    "extract_fund_codes",
    "CollectorNode",
    "CollectorOutput",
    "AnalyzerNode",
    "AnalyzerOutput",
    "ThesisNode",
    "ThesisOutput",
    "EvaluatorNode",
    "EvaluatorOutput",
    "RepairNode",
    "RepairOutput",
    "ResearcherNode",
    "ResearcherOutput",
    "SynthesizerNode",
    "SynthesizerOutput",
]
