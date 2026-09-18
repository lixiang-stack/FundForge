"""跨领域共享原语：枚举类型、State 归一化与序列化助手。

对应 Go 侧 internal/domain/shared 的职责定位。
"""

import json
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class DataQuality(StrEnum):
    """数据质量（TechnicalContract §7/§8 通用字段）。"""

    COMPLETE = "complete"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"


def coerce_model(value: Any, model: type[T]) -> T | None:
    """State 值归一化：dict → 模型；None/模型实例原样返回。

    State 经 LangGraph 节点回传后可能是 dict，各节点统一经此入口归一化。
    """
    if value is None or isinstance(value, model):
        return value
    return model.model_validate(value)


def to_jsonable(value: Any) -> Any:
    """Pydantic 模型 → JSON 安全 dict（model_dump(mode="json")）；dict/None 原样返回。"""
    if value is None or isinstance(value, dict):
        return value
    return value.model_dump(mode="json")


def to_json_text(value: Any) -> str:
    """任意值 → JSON 文本：Pydantic 模型走 model_dump_json，dict/其他走 json.dumps。

    用于运行记录等展示场景（模型与 dict 混排的 State 值统一渲染）。
    """
    dump = getattr(value, "model_dump_json", None)
    if callable(dump):
        return dump()
    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["DataQuality", "coerce_model", "to_jsonable", "to_json_text"]
