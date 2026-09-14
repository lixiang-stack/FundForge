"""Fund Tools（docs/TechnicalContract.md §6）。

原则：
- Tools 只返回事实（Data + Source + Timestamp + data_quality），不做投资判断；
- 关键金融指标不由 Tool 计算（Phase 2 Analyzer 负责）；
- 每次调用可观测（由 Collector 节点记录 ToolCallRecord）。

数据来源：collector service（唯一 akshare 边界），不直接调用 akshare。
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from langchain_core.tools import BaseTool, tool

from domain.fund import (
    Fund,
    FundPerformance,
    FundSummary,
    Holding,
    NAVPoint,
    quality_of,
)
from store import FundStore
from tools.collector_client import (
    CollectorClient,
    CollectorError,
    FUND_DETAIL_PATH,
    FUND_HOLDINGS_PATH,
    FUND_NAV_PATH,
    collector_source,
)

logger = logging.getLogger(__name__)

_FUND_DETAIL_SOURCE = collector_source(FUND_DETAIL_PATH)
_FUND_NAV_SOURCE = collector_source(FUND_NAV_PATH)
_FUND_HOLDINGS_SOURCE = collector_source(FUND_HOLDINGS_PATH)


@dataclass
class FundTools:
    """Fund Tools 集合（§6 Tool Contract）。"""

    get_fund_info: BaseTool
    get_fund_performance: BaseTool
    get_fund_holdings: BaseTool
    search_funds: BaseTool


def _parse_aum(raw: str | None) -> float | None:
    """解析雪球规模字符串（如 "44.16亿"）为 float（单位：亿元）。"""
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _optional_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def make_fund_tools(client: CollectorClient, store: FundStore) -> FundTools:
    """构建绑定 collector 客户端与外部 Store 的 Fund Tools。"""

    @tool
    def get_fund_info(fund_id: str) -> Fund:
        """获取基金基本信息（名称、类型、规模、基金经理等），只返回事实。"""
        rows = client.get_fund_detail(fund_id)
        kv = {str(r.get("item")): r.get("value") for r in rows}
        name = _optional_str(kv.get("基金名称"))
        fund_type = _optional_str(kv.get("基金类型"))
        manager_name = _optional_str(kv.get("基金经理"))
        inception = _parse_date(_optional_str(kv.get("成立时间")))
        aum = _parse_aum(_optional_str(kv.get("最新规模") or kv.get("基金规模")))
        benchmark = _optional_str(kv.get("业绩基准"))
        company = _optional_str(kv.get("基金公司"))

        fund = Fund(
            id=fund_id,
            name=name or "",
            fund_type=fund_type,
            manager_name=manager_name,
            company=company,
            benchmark=benchmark,
            inception_date=inception,
            aum=aum,
            source=_FUND_DETAIL_SOURCE.format(code=fund_id),
            as_of=datetime.now(),
            # detail 为空时关键字段全为 None → missing，无需单独分支
            data_quality=quality_of(name, fund_type, manager_name, inception, aum),
        )
        store.put_fund(fund)
        logger.info("get_fund_info: %s -> %s (%s)", fund_id, name, fund.data_quality)
        return fund

    @tool
    def get_fund_performance(
        fund_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> FundPerformance:
        """获取基金历史净值序列（原始事实，写入外部 Store）；指标计算由 Analyzer 负责。"""
        unit_rows = client.get_fund_nav(fund_id, indicator="unit")
        acc_rows = client.get_fund_nav(fund_id, indicator="acc")

        acc_by_date = {r.get("nav_date"): r.get("acc_nav") for r in acc_rows}
        points: list[NAVPoint] = []
        for r in unit_rows:
            nav_date = _parse_date(_optional_str(r.get("nav_date")))
            if nav_date is None:
                continue
            points.append(
                NAVPoint(
                    nav_date=nav_date,
                    unit_nav=r.get("unit_nav"),
                    acc_nav=acc_by_date.get(r.get("nav_date")),
                    daily_return=r.get("daily_return"),
                )
            )
        points.sort(key=lambda p: p.nav_date)

        if start_date:
            start = _parse_date(start_date)
            if start:
                points = [p for p in points if p.nav_date >= start]
        if end_date:
            end = _parse_date(end_date)
            if end:
                points = [p for p in points if p.nav_date <= end]

        store.put_nav_series(fund_id, points)

        performance = FundPerformance(
            fund_id=fund_id,
            period_start=points[0].nav_date if points else None,
            period_end=points[-1].nav_date if points else None,
            nav_point_count=len(points),
            source=_FUND_NAV_SOURCE.format(code=fund_id),
            as_of=datetime.now(),
            # 序列存在即 complete，为空即 missing
            data_quality=quality_of(points or None),
        )
        logger.info(
            "get_fund_performance: %s -> %d points [%s ~ %s]",
            fund_id,
            len(points),
            performance.period_start,
            performance.period_end,
        )
        return performance

    @tool
    def get_fund_holdings(fund_id: str, year: str | None = None) -> list[Holding]:
        """获取基金股票持仓（前十大重仓等披露数据），只返回事实。

        空持仓对债券型/货币型基金属正常披露，不算数据质量问题。
        """
        rows = client.get_fund_holdings(fund_id, year=year)
        holdings = [
            Holding(
                stock_code=str(r.get("stock_code", "")),
                stock_name=str(r.get("stock_name", "")),
                hold_ratio=r.get("hold_ratio"),
                report_date=_optional_str(r.get("report_date")),
            )
            for r in rows
            if r.get("stock_code")
        ]
        store.put_holdings(fund_id, holdings)
        logger.info("get_fund_holdings: %s -> %d rows", fund_id, len(holdings))
        return holdings

    @tool
    def search_funds(query: str, limit: int = 10) -> list[FundSummary]:
        """按基金代码 / 名称 / 拼音缩写模糊搜索基金（简单版）。"""
        rows = client.list_funds()
        needle = query.strip().lower()
        matched = [
            r
            for r in rows
            if needle
            and (
                needle in str(r.get("fund_code", "")).lower()
                or needle in str(r.get("fund_name", "")).lower()
                or needle in str(r.get("pinyin_abbr", "")).lower()
            )
        ][:limit]
        summaries = [
            FundSummary(
                id=str(r.get("fund_code", "")),
                name=str(r.get("fund_name", "")),
                fund_type=_optional_str(r.get("fund_type")),
                as_of=datetime.now(),
                data_quality=quality_of(r.get("fund_code"), r.get("fund_name"), r.get("fund_type")),
            )
            for r in matched
        ]
        logger.info("search_funds: %r -> %d hits", query, len(summaries))
        return summaries

    return FundTools(
        get_fund_info=get_fund_info,
        get_fund_performance=get_fund_performance,
        get_fund_holdings=get_fund_holdings,
        search_funds=search_funds,
    )


__all__ = ["FundTools", "make_fund_tools", "CollectorError"]
