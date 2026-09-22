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
    AchievementRow,
    AssetAllocRow,
    FeeInfo,
    Fund,
    FundPerformance,
    FundRating,
    FundSummary,
    Holding,
    IndexPoint,
    IndustryAllocRow,
    NAVPoint,
    latest_report_period,
    parse_report_period,
    quality_of,
)
from store import FundStore
from tools.collector_client import (
    CollectorClient,
    CollectorError,
    FUND_ACHIEVEMENT_PATH,
    FUND_ALLOCATION_PATH,
    FUND_DETAIL_PATH,
    FUND_FEES_PATH,
    FUND_HOLDINGS_PATH,
    FUND_INDUSTRY_PATH,
    FUND_NAV_PATH,
    FUND_RATING_PATH,
    INDEX_DAILY_PATH,
    collector_source,
)

logger = logging.getLogger(__name__)

_FUND_DETAIL_SOURCE = collector_source(FUND_DETAIL_PATH)
_FUND_NAV_SOURCE = collector_source(FUND_NAV_PATH)
_FUND_HOLDINGS_SOURCE = collector_source(FUND_HOLDINGS_PATH)
_FUND_INDUSTRY_SOURCE = collector_source(FUND_INDUSTRY_PATH)
_FUND_ALLOCATION_SOURCE = collector_source(FUND_ALLOCATION_PATH)
_FUND_FEES_SOURCE = collector_source(FUND_FEES_PATH)
_FUND_ACHIEVEMENT_SOURCE = collector_source(FUND_ACHIEVEMENT_PATH)
_FUND_RATING_SOURCE = collector_source(FUND_RATING_PATH)
_INDEX_DAILY_SOURCE = collector_source(INDEX_DAILY_PATH)

# 报告期季度 → 财报月末（YYYYMMDD 的月日部分），用于雪球资产配置接口的 date 参数
_QUARTER_END_MD = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}


@dataclass
class FundTools:
    """Fund Tools 集合（§6 Tool Contract）。"""

    get_fund_info: BaseTool
    get_fund_performance: BaseTool
    get_fund_holdings: BaseTool
    get_fund_industry_alloc: BaseTool
    get_fund_asset_allocation: BaseTool
    get_fund_fees: BaseTool
    get_fund_achievement: BaseTool
    get_fund_rating: BaseTool
    get_index_data: BaseTool
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


def _report_period_to_yyyymmdd(period: str | None) -> str | None:
    """报告期原文（如"2026年2季度股票投资明细"）→ 财报月末日期（如"20260630"）。"""
    parsed = parse_report_period(period)
    if not parsed:
        return None
    year, quarter = parsed
    return f"{year}{_QUARTER_END_MD[quarter]}"


def make_fund_tools(client: CollectorClient, store: FundStore) -> FundTools:
    """构建绑定 collector 客户端与外部 Store 的 Fund Tools。"""

    @tool
    def get_fund_info(fund_id: str) -> Fund:
        """获取基金基本信息（名称、类型、规模、基金经理等），只返回事实。"""
        rows = client.get_fund_detail(fund_id)
        kv = {str(r.get("item")): r.get("value") for r in rows}
        # 键名为 collector FIELD_MAPS["fund_detail"] 标准化后的英文 item
        name = _optional_str(kv.get("fund_name"))
        fund_type = _optional_str(kv.get("fund_type"))
        manager_name = _optional_str(kv.get("fund_manager"))
        inception = _parse_date(_optional_str(kv.get("inception_date")))
        aum = _parse_aum(_optional_str(kv.get("aum")))
        benchmark = _optional_str(kv.get("benchmark"))
        company = _optional_str(kv.get("fund_company"))
        full_name = _optional_str(kv.get("fund_full_name"))
        custodian = _optional_str(kv.get("custodian_bank"))
        rating_agency = _optional_str(kv.get("rating_agency"))
        rating = _optional_str(kv.get("fund_rating"))
        investment_strategy = _optional_str(kv.get("investment_strategy"))
        investment_objective = _optional_str(kv.get("investment_objective"))

        fund = Fund(
            id=fund_id,
            name=name or "",
            full_name=full_name,
            fund_type=fund_type,
            manager_name=manager_name,
            company=company,
            custodian=custodian,
            benchmark=benchmark,
            inception_date=inception,
            aum=aum,
            rating_agency=rating_agency,
            rating=rating,
            investment_strategy=investment_strategy,
            investment_objective=investment_objective,
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
        # akshare 单位净值走势偶发重复日期行：虚增 nav_point_count 并在收益序列插入伪收益；
        # 与 acc_by_date 字典语义一致，同日保留末行
        points = sorted({p.nav_date: p for p in points}.values(), key=lambda p: p.nav_date)

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
    def get_fund_industry_alloc(fund_id: str, year: str | None = None) -> list[IndustryAllocRow]:
        """获取基金行业配置（占净值比例，按报告期），只返回事实；无行业披露（如债基）返回空列表。"""
        rows = client.get_fund_industry(fund_id, year=year)
        industry = [
            IndustryAllocRow(
                industry=_optional_str(r.get("industry")),
                nav_ratio=r.get("nav_ratio"),
                market_value=r.get("market_value"),
                report_date=_optional_str(r.get("report_date")),
            )
            for r in rows
            if r.get("industry")
        ]
        store.put_industry(fund_id, industry)
        logger.info("get_fund_industry_alloc: %s -> %d rows", fund_id, len(industry))
        return industry

    @tool
    def get_fund_asset_allocation(fund_id: str, date: str | None = None) -> list[AssetAllocRow]:
        """获取基金资产配置（股票/债券/现金仓位占比），只返回事实。

        date 为财报日期（YYYYMMDD）；缺省取股票持仓最新报告期对应的财报日期，
        无持仓报告期可依据时返回空列表（不编造日期）。
        """
        if date is None:
            date = _report_period_to_yyyymmdd(latest_report_period(store.get_holdings(fund_id)))
        if not date:
            store.put_allocation(fund_id, [])
            logger.info("get_fund_asset_allocation: %s -> 无报告期依据，跳过", fund_id)
            return []
        rows = client.get_fund_allocation(fund_id, date=date)
        allocation = [
            AssetAllocRow(
                asset_type=_optional_str(r.get("asset_type")),
                percent=r.get("percent"),
            )
            for r in rows
            if r.get("asset_type")
        ]
        store.put_allocation(fund_id, allocation)
        logger.info("get_fund_asset_allocation: %s (%s) -> %d rows", fund_id, date, len(allocation))
        return allocation

    @tool
    def get_fund_fees(fund_id: str) -> FeeInfo:
        """获取基金运作费用（管理费/托管费/销售服务费率，%/年），只返回事实；无披露时字段为 None。"""
        rows = client.get_fund_fees(fund_id)
        first = rows[0] if rows else {}
        fees = FeeInfo(
            management_fee_rate=first.get("management_fee_rate"),
            custodian_fee_rate=first.get("custodian_fee_rate"),
            service_fee_rate=first.get("service_fee_rate"),
        )
        store.put_fees(fund_id, fees)
        logger.info("get_fund_fees: %s -> mgmt=%s", fund_id, fees.management_fee_rate)
        return fees

    @tool
    def get_fund_achievement(fund_id: str) -> list[AchievementRow]:
        """获取基金区间业绩与同类排名（雪球源：年度/阶段业绩），只返回事实。"""
        rows = client.get_fund_achievement(fund_id)
        achievement = [
            AchievementRow(
                performance_type=_optional_str(r.get("performance_type")),
                period=_optional_str(r.get("period")),
                return_rate=r.get("return_rate"),
                max_drawdown=r.get("max_drawdown"),
                category_rank=_optional_str(r.get("category_rank")),
            )
            for r in rows
            if r.get("period")
        ]
        store.put_achievement(fund_id, achievement)
        logger.info("get_fund_achievement: %s -> %d rows", fund_id, len(achievement))
        return achievement

    @tool
    def get_fund_rating(fund_id: str) -> list[FundRating]:
        """获取基金第三方评级（上海证券/招商证券/济安金信/晨星），无评级返回空列表。"""
        rows = client.get_fund_rating(fund_id)
        ratings = [
            FundRating(
                fund_code=str(r.get("fund_code") or fund_id),
                five_star_count=r.get("five_star_count"),
                rating_sh=r.get("rating_sh"),
                rating_zs=r.get("rating_zs"),
                rating_ja=r.get("rating_ja"),
                rating_mx=r.get("rating_mx"),
            )
            for r in rows
        ]
        store.put_rating(fund_id, ratings)
        logger.info("get_fund_rating: %s -> %d rows", fund_id, len(ratings))
        return ratings

    @tool
    def get_index_data(
        index_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[IndexPoint]:
        """获取基准指数日线收盘序列（原始事实，写入外部 Store），只返回事实。"""
        rows = client.get_index_daily(index_id, start_date=start_date, end_date=end_date)
        points = []
        for r in rows:
            nav_date = _parse_date(_optional_str(r.get("trade_date")))
            if nav_date is None:
                continue
            points.append(IndexPoint(nav_date=nav_date, close=r.get("close")))
        points.sort(key=lambda p: p.nav_date)
        store.put_index_series(index_id, points)
        logger.info("get_index_data: %s -> %d points", index_id, len(points))
        return points

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
        get_fund_industry_alloc=get_fund_industry_alloc,
        get_fund_asset_allocation=get_fund_asset_allocation,
        get_fund_fees=get_fund_fees,
        get_fund_achievement=get_fund_achievement,
        get_fund_rating=get_fund_rating,
        get_index_data=get_index_data,
        search_funds=search_funds,
    )


__all__ = ["FundTools", "make_fund_tools", "CollectorError"]
