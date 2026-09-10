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


__all__ = ["collector_base_url", "collector_timeout_seconds"]
