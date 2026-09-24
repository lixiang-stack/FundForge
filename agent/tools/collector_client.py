"""Collector Service HTTP 客户端。

collector/main.py 是项目唯一的 akshare 边界（ACL，中文字段已标准化为英文）。
Agent 的 Fund Tools 统一经由本客户端访问数据，不直接调用 akshare。
"""

import logging
import time
from typing import Any, Literal

import httpx

from config import collector_base_url, collector_timeout_seconds

logger = logging.getLogger(__name__)

NavIndicator = Literal["unit", "acc"]

# ---- API 路径常量（client 请求与 evidence source 字符串统一从此引用） ----

FUND_LIST_PATH = "/api/funds"
FUND_DETAIL_PATH = "/api/funds/{code}/detail"
FUND_NAV_PATH = "/api/funds/{code}/nav"
FUND_HOLDINGS_PATH = "/api/funds/{code}/holdings/stock"
FUND_INDUSTRY_PATH = "/api/funds/{code}/industry"
FUND_ALLOCATION_PATH = "/api/funds/{code}/allocation"
FUND_FEES_PATH = "/api/funds/{code}/fees"
FUND_ACHIEVEMENT_PATH = "/api/funds/{code}/achievement"
FUND_RATING_PATH = "/api/funds/{code}/rating"
INDEX_DAILY_PATH = "/api/index/{code}/daily"


def collector_source(path: str) -> str:
    """Evidence source 命名约定：collector:<path>。"""
    return f"collector:{path}"


_NAV_INDICATOR_PARAM: dict[str, str] = {
    "unit": "单位净值走势",
    "acc": "累计净值走势",
}

# 瞬时连接失败（macOS 偶发 getaddrinfo 失败等）在并发建连窗口内常自愈，短退避重试即可；
# 仅重试 ConnectError，超时/HTTP 状态错误仍立即失败。
_CONNECT_RETRY_ATTEMPTS = 2     # 首次失败后的额外尝试次数（共 3 次）
_CONNECT_RETRY_BACKOFF_S = 0.2  # 指数退避基数：0.2s → 0.4s


class CollectorClient:
    """对 collector REST API 的薄包装。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=(base_url or collector_base_url()).rstrip("/"),
            timeout=timeout or collector_timeout_seconds(),
            transport=transport,
        )
        self._fund_list_cache: list[dict[str, Any]] | None = None

    # ---- Fund Detail（雪球源，返回 {item, value} 键值对列表） ----

    def get_fund_detail(self, code: str) -> list[dict[str, Any]]:
        return self._get(FUND_DETAIL_PATH.format(code=code))

    # ---- Historical NAV ----

    def get_fund_nav(
        self,
        code: str,
        indicator: NavIndicator = "unit",
        period: str = "成立来",
    ) -> list[dict[str, Any]]:
        params = {"indicator": _NAV_INDICATOR_PARAM[indicator], "period": period}
        return self._get(FUND_NAV_PATH.format(code=code), params=params)

    # ---- Stock Holdings ----

    def get_fund_holdings(self, code: str, year: str | None = None) -> list[dict[str, Any]]:
        params = {"date": year} if year else None
        return self._get(FUND_HOLDINGS_PATH.format(code=code), params=params)

    # ---- Industry Allocation ----

    def get_fund_industry(self, code: str, year: str | None = None) -> list[dict[str, Any]]:
        params = {"date": year} if year else None
        return self._get(FUND_INDUSTRY_PATH.format(code=code), params=params)

    # ---- Asset Allocation（雪球源，date 为财报日期 YYYYMMDD） ----

    def get_fund_allocation(self, code: str, date: str) -> list[dict[str, Any]]:
        return self._get(FUND_ALLOCATION_PATH.format(code=code), params={"date": date})

    # ---- Operating Fees ----

    def get_fund_fees(self, code: str) -> list[dict[str, Any]]:
        return self._get(FUND_FEES_PATH.format(code=code))

    # ---- Achievement（雪球源：年度/阶段业绩与同类排名） ----

    def get_fund_achievement(self, code: str) -> list[dict[str, Any]]:
        return self._get(FUND_ACHIEVEMENT_PATH.format(code=code))

    # ---- Rating（天天基金评级总汇） ----

    def get_fund_rating(self, code: str) -> list[dict[str, Any]]:
        return self._get(FUND_RATING_PATH.format(code=code))

    # ---- Index Daily（基准指数日线，code 需带市场前缀如 sh000905） ----

    def get_index_daily(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._get(INDEX_DAILY_PATH.format(code=code), params=params or None)

    # ---- Fund List（全量，进程内缓存，用于 search_funds） ----

    def list_funds(self) -> list[dict[str, Any]]:
        if self._fund_list_cache is None:
            self._fund_list_cache = self._get(FUND_LIST_PATH)
        return self._fund_list_cache

    # ---- internals ----

    def _get(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        attempt = 0
        while True:
            try:
                resp = self._client.get(path, params=params)
                resp.raise_for_status()
                break
            except httpx.ConnectError as e:
                if attempt >= _CONNECT_RETRY_ATTEMPTS:
                    logger.error(
                        "collector connect failed after %d attempts: %s %s: %s",
                        attempt + 1, path, params, e,
                    )
                    raise CollectorError(f"collector {path} failed: {e}") from e
                delay = _CONNECT_RETRY_BACKOFF_S * (2**attempt)
                logger.warning(
                    "collector connect failed (attempt %d/%d), retry in %.1fs: %s %s: %s",
                    attempt + 1, _CONNECT_RETRY_ATTEMPTS + 1, delay, path, params, e,
                )
                attempt += 1
                time.sleep(delay)
            except httpx.HTTPError as e:
                logger.error("collector request failed: %s %s: %s", path, params, e)
                raise CollectorError(f"collector {path} failed: {e}") from e
        data = resp.json()
        if not isinstance(data, list):
            raise CollectorError(f"collector {path} returned unexpected payload type")
        return data

    def close(self) -> None:
        self._client.close()


class CollectorError(RuntimeError):
    """collector 不可达或返回异常时抛出。"""


__all__ = [
    "CollectorClient",
    "CollectorError",
    "NavIndicator",
    "FUND_LIST_PATH",
    "FUND_DETAIL_PATH",
    "FUND_NAV_PATH",
    "FUND_HOLDINGS_PATH",
    "collector_source",
]
