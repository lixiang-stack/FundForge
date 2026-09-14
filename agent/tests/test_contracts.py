"""节点输出契约测试。

强制约束（防止 Output TypedDict 与 State 漂移）：
1. 每个 XxxOutput 的 key 必须是 FundForgeState key 的子集（节点只返回自己负责的字段）；
2. Output 字段类型必须与 State 同名字段类型一致；
3. State 的每个字段都必须有节点负责（request_id / user_query 为外部输入除外），
   避免出现无人写入的孤儿字段。
"""

import pytest

from nodes import (
    AnalyzerOutput,
    CollectorOutput,
    EvaluatorOutput,
    PlannerOutput,
    RepairOutput,
    ResearcherOutput,
    RouterOutput,
    SynthesizerOutput,
    ThesisOutput,
)
from state import FundForgeState

_OUTPUTS = {
    "RouterOutput": RouterOutput,
    "PlannerOutput": PlannerOutput,
    "CollectorOutput": CollectorOutput,
    "AnalyzerOutput": AnalyzerOutput,
    "ResearcherOutput": ResearcherOutput,
    "ThesisOutput": ThesisOutput,
    "EvaluatorOutput": EvaluatorOutput,
    "RepairOutput": RepairOutput,
    "SynthesizerOutput": SynthesizerOutput,
}

_INPUT_ONLY = {"request_id", "user_query"}


class TestNodeOutputContract:
    @pytest.mark.parametrize("name,output", _OUTPUTS.items())
    def test_output_keys_are_state_subset(self, name, output):
        state_keys = set(FundForgeState.__annotations__)
        output_keys = set(output.__annotations__)
        unknown = output_keys - state_keys
        assert not unknown, f"{name} 含 State 不存在的字段 {unknown}（节点输出必须是 State 子集）"

    @pytest.mark.parametrize("name,output", _OUTPUTS.items())
    def test_output_field_types_match_state(self, name, output):
        state_ann = FundForgeState.__annotations__
        mismatched = {
            key: (output.__annotations__[key], state_ann[key])
            for key in output.__annotations__
            if key in state_ann and output.__annotations__[key] != state_ann[key]
        }
        assert not mismatched, f"{name} 字段类型与 State 不一致：{mismatched}"

    def test_state_fields_are_covered_by_some_node(self):
        covered = set(_INPUT_ONLY)
        for output in _OUTPUTS.values():
            covered |= set(output.__annotations__)
        orphans = set(FundForgeState.__annotations__) - covered
        assert not orphans, f"State 存在无节点负责的孤儿字段：{orphans}"

    def test_outputs_are_total_false_partial_updates(self):
        # 节点返回部分更新（降级路径可能只写子集 key），统一 total=False
        for name, output in _OUTPUTS.items():
            assert output.__total__ is False, f"{name} 应为 total=False（允许部分更新）"
