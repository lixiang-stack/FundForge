"""Agent 配置（env-only，与 Go 侧 internal/config 模式一致）。"""

import os


def collector_base_url() -> str:
    return os.getenv("COLLECTOR_BASE_URL", "http://localhost:8000")


def collector_timeout_seconds() -> float:
    raw = os.getenv("COLLECTOR_TIMEOUT_S", "120")
    try:
        return float(raw)
    except ValueError:
        return 120.0


def llm_base_url() -> str:
    return os.getenv("LLM_BASE_URL", "")


def llm_api_key() -> str:
    return os.getenv("LLM_API_KEY", "")


def llm_model() -> str:
    return os.getenv("LLM_MODEL", "")


def llm_timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_S", "120")
    try:
        return float(raw)
    except ValueError:
        return 120.0


__all__ = [
    "collector_base_url",
    "collector_timeout_seconds",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "llm_timeout_seconds",
]
