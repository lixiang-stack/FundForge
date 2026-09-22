"""Collector 节点（Node 合同 §4）。

职责：通过 Fund Tools 获取结构化基金数据。
- 完整数据写入外部 Store（由 Tools 内部完成），State 只保留摘要与 ID；
- 产出 funds_summary + evidence + tool_calls + data_quality_issues；
- evidence 只允许追加。

结构：`_collect_fund` 返回结构化 `FundCollectionResult`（无副作用），
由 `CollectorNode.__call__` 统一合并进 State。

并发：基金之间、单基金内的各 Tool 之间无依赖（资产配置依赖持仓的报告期，须等
holdings 完成后提交），按 limits.py 的上限并发执行；
结果按 fund_ids 顺序与固定 Tool 顺序合并，Evidence / ToolCallRecord 顺序保持确定。
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from domain.evidence import Evidence, EvidenceType, ToolCallRecord
from domain.fund import (
    AchievementRow,
    AssetAllocRow,
    FeeInfo,
    Fund,
    FundPerformance,
    FundRating,
    FundSummary,
    IndexPoint,
    IndustryAllocRow,
    latest_report_period,
    parse_report_period,
    resolve_benchmark_code,
    summarize_fund,
    top_holdings,
)
from domain.plan import ResearchPlan
from domain.shared import DataQuality
from langchain_core.tools import BaseTool
from limits import COLLECTOR_FUND_CONCURRENCY, COLLECTOR_TOOL_CONCURRENCY
from state import FundForgeState
from store import FundStore
from tools.fund_tools import FundTools
from tools.collector_client import (
    FUND_ACHIEVEMENT_PATH,
    FUND_ALLOCATION_PATH,
    FUND_FEES_PATH,
    FUND_HOLDINGS_PATH,
    FUND_INDUSTRY_PATH,
    FUND_RATING_PATH,
    INDEX_DAILY_PATH,
    collector_source,
)

logger = logging.getLogger(__name__)

_FUND_HOLDINGS_SOURCE = collector_source(FUND_HOLDINGS_PATH)
_FUND_INDUSTRY_SOURCE = collector_source(FUND_INDUSTRY_PATH)
_FUND_ALLOCATION_SOURCE = collector_source(FUND_ALLOCATION_PATH)
_FUND_FEES_SOURCE = collector_source(FUND_FEES_PATH)
_FUND_ACHIEVEMENT_SOURCE = collector_source(FUND_ACHIEVEMENT_PATH)
_FUND_RATING_SOURCE = collector_source(FUND_RATING_PATH)
_INDEX_DAILY_SOURCE = collector_source(INDEX_DAILY_PATH)


@dataclass
class FundCollectionResult:
    """单只基金的采集结果（函数式产出，由 __call__ 统一合并）。"""

    fund_id: str
    summary: FundSummary | None = None
    benchmark_code: str | None = None   # 由基准文本启发式解析；None = 无法解析
    evidence: list[Evidence] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def record_tool_call(tool: BaseTool, arguments: dict[str, Any]) -> tuple[Any, ToolCallRecord]:
    """执行一次 Tool 调用并记录 ToolCallRecord（§12 可观测性合同）。

    Tool 失败必须落记录并降级返回，不允许中断工作流。
    """
    started_at = datetime.now()
    try:
        result = tool.invoke(arguments)
    except Exception as e:  # noqa: BLE001
        logger.error("tool %s failed: %s", tool.name, e)
        return None, ToolCallRecord(
            tool_name=tool.name,
            arguments=arguments,
            started_at=started_at,
            finished_at=datetime.now(),
            success=False,
            error=str(e),
        )
    return result, ToolCallRecord(
        tool_name=tool.name,
        arguments=arguments,
        started_at=started_at,
        finished_at=datetime.now(),
        success=True,
    )


def fund_evidence(fund: Fund) -> Evidence:
    """基金基本信息 → fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=fund.source,
        source_detail=f"基金基本信息：{fund.name or fund.id}",
        as_of=fund.as_of,
        value={
            "fund_id": fund.id,
            "name": fund.name or None,
            "full_name": fund.full_name,
            "fund_type": fund.fund_type,
            "aum_yi": fund.aum,
            "manager_name": fund.manager_name,
            "company": fund.company,
            "custodian": fund.custodian,
            "benchmark": fund.benchmark,
            "rating_agency": fund.rating_agency,
            "rating": fund.rating,
            "inception_date": str(fund.inception_date) if fund.inception_date else None,
            "investment_strategy": fund.investment_strategy,
            "investment_objective": fund.investment_objective,
        },
        data_quality=fund.data_quality,
        raw_ref=FundStore.fund_ref(fund.id),
    )


def performance_evidence(perf: FundPerformance) -> Evidence:
    """净值序列摘要 → fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=perf.source,
        source_detail=f"净值序列：{perf.nav_point_count} 个数据点",
        as_of=perf.as_of,
        value={
            "fund_id": perf.fund_id,
            "period_start": str(perf.period_start) if perf.period_start else None,
            "period_end": str(perf.period_end) if perf.period_end else None,
            "nav_point_count": perf.nav_point_count,
        },
        data_quality=perf.data_quality,
        raw_ref=FundStore.nav_ref(perf.fund_id),
    )


def holdings_evidence(code: str, holdings: list, failed: bool) -> Evidence:
    """股票持仓 → fund_data 类型 Evidence（空持仓属正常披露，仅质量降级）。

    value 携带最新报告期的前十大持仓摘要，供 Thesis 提示词直接引用；完整数据在 Store。
    """
    period = latest_report_period(holdings)
    top = [
        {"stock_name": h.stock_name, "hold_ratio": h.hold_ratio}
        for h in top_holdings(holdings)
    ]
    quality = (
        DataQuality.MISSING
        if failed or not holdings
        else DataQuality.COMPLETE
    )
    detail = f"股票持仓：{len(holdings)} 条"
    if period:
        detail += f"（最新报告期 {period}）"
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_HOLDINGS_SOURCE.format(code=code),
        source_detail=detail,
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "holding_count": len(holdings),
            "latest_report_period": period,
            "top_holdings": top,
            "failed": failed,
        },
        data_quality=quality,
        raw_ref=FundStore.holdings_ref(code),
    )


def industry_evidence(code: str, rows: list[IndustryAllocRow]) -> Evidence:
    """行业配置 → fund_data 类型 Evidence（携带最新报告期前五大行业摘要）。"""
    latest = max((r.report_date for r in rows if r.report_date), default=None)
    latest_rows = [r for r in rows if r.report_date == latest] if latest else rows
    top = sorted(
        (r for r in latest_rows if r.nav_ratio is not None),
        key=lambda r: r.nav_ratio or 0.0,
        reverse=True,
    )[:5]
    detail = f"行业配置：{len(rows)} 条" + (f"（最新报告期 {latest}）" if latest else "")
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_INDUSTRY_SOURCE.format(code=code),
        source_detail=detail,
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "latest_report_date": latest,
            "row_count": len(rows),
            "top_industries": [
                {"industry": r.industry, "nav_ratio": r.nav_ratio} for r in top
            ],
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.industry_ref(code),
    )


def allocation_evidence(code: str, rows: list[AssetAllocRow]) -> Evidence:
    """资产配置（股/债/现金仓位占比）→ fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_ALLOCATION_SOURCE.format(code=code),
        source_detail="资产配置：股票/债券/现金仓位占比（最新财报）",
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "allocation": [
                {"asset_type": r.asset_type, "percent": r.percent} for r in rows
            ],
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.allocation_ref(code),
    )


def fees_evidence(code: str, fees: FeeInfo) -> Evidence:
    """运作费用 → fund_data 类型 Evidence。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_FEES_SOURCE.format(code=code),
        source_detail="运作费用：管理费/托管费/销售服务费率",
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "management_fee_rate": fees.management_fee_rate,
            "custodian_fee_rate": fees.custodian_fee_rate,
            "service_fee_rate": fees.service_fee_rate,
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.fees_ref(code),
    )


def achievement_evidence(code: str, rows: list[AchievementRow]) -> Evidence:
    """区间业绩与同类排名 → fund_data 类型 Evidence（携带前 8 条）。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_ACHIEVEMENT_SOURCE.format(code=code),
        source_detail="区间业绩与同类排名（雪球源）",
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "achievement": [
                {
                    "performance_type": r.performance_type,
                    "period": r.period,
                    "return_rate": r.return_rate,
                    "max_drawdown": r.max_drawdown,
                    "category_rank": r.category_rank,
                }
                for r in rows[:8]
            ],
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.achievement_ref(code),
    )


def rating_evidence(code: str, ratings: list[FundRating]) -> Evidence:
    """第三方评级 → fund_data 类型 Evidence。"""
    r = ratings[0]
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_FUND_RATING_SOURCE.format(code=code),
        source_detail="第三方基金评级（天天基金评级总汇）",
        as_of=datetime.now(),
        value={
            "fund_id": code,
            "five_star_count": r.five_star_count,
            "rating_sh": r.rating_sh,
            "rating_zs": r.rating_zs,
            "rating_ja": r.rating_ja,
            "rating_mx": r.rating_mx,
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.rating_ref(code),
    )


def index_evidence(index_code: str, points: list[IndexPoint]) -> Evidence:
    """基准指数日线 → fund_data 类型 Evidence（超额收益/跟踪误差的输入）。"""
    return Evidence(
        id=f"ev-{uuid.uuid4().hex[:12]}",
        evidence_type=EvidenceType.FUND_DATA,
        source=_INDEX_DAILY_SOURCE.format(code=index_code),
        source_detail=f"基准指数日线：{len(points)} 个数据点",
        as_of=datetime.now(),
        value={
            "index_id": index_code,
            "point_count": len(points),
            "period_start": str(points[0].nav_date) if points else None,
            "period_end": str(points[-1].nav_date) if points else None,
        },
        data_quality=DataQuality.COMPLETE,
        raw_ref=FundStore.index_ref(index_code),
    )


class CollectorOutput(TypedDict, total=False):
    """Collector 节点输出（§4：fund_ids, funds_summary, evidence, tool_calls, data_quality_issues）。"""

    fund_ids: list[str]
    funds_summary: list[FundSummary]
    evidence: list[Evidence]
    tool_calls: list[ToolCallRecord]
    data_quality_issues: list[str]


class CollectorNode:
    """Collector 节点：调用 Fund Tools 采集数据，统一合并进 State。"""

    def __init__(self, tools: FundTools) -> None:
        self._tools = tools

    def __call__(self, state: FundForgeState) -> CollectorOutput:
        plan = ResearchPlan.from_state(state.get("research_plan"))
        fund_ids = list(plan.fund_ids) if plan else []
        if not fund_ids:
            logger.warning("collector: research_plan 为空，跳过采集")
            return {
                "fund_ids": [],
                "funds_summary": [],
                "evidence": list(state.get("evidence", [])),
                "tool_calls": list(state.get("tool_calls", [])),
                "data_quality_issues": [
                    *state.get("data_quality_issues", []),
                    "research_plan 中没有基金代码，未执行数据采集",
                ],
            }

        # 基金间并发采集；pool.map 保证结果顺序与 fund_ids 一致
        workers = min(COLLECTOR_FUND_CONCURRENCY, len(fund_ids))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(self._collect_fund, fund_ids))
        # 基准指数：按解析出的基准代码去重拉取（analyzer 计算超额收益/跟踪误差的输入）
        index_evidence, index_records = self._collect_benchmarks(results)
        collected = {
            "fund_ids": fund_ids,
            "funds_summary": [r.summary for r in results if r.summary is not None],
            "evidence": [e for r in results for e in r.evidence],
            "tool_calls": [t for r in results for t in r.tool_calls],
            "data_quality_issues": [i for r in results for i in r.issues],
        }
        collected["evidence"] = [*collected["evidence"], *index_evidence]
        collected["tool_calls"] = [*collected["tool_calls"], *index_records]
        # evidence 只允许追加：在既有记录基础上累加
        collected["evidence"] = [*state.get("evidence", []), *collected["evidence"]]
        collected["tool_calls"] = [*state.get("tool_calls", []), *collected["tool_calls"]]
        collected["data_quality_issues"] = [
            *state.get("data_quality_issues", []),
            *collected["data_quality_issues"],
        ]

        logger.info(
            "collector: %d funds collected, %d evidence, %d tool calls",
            len(collected["funds_summary"]),
            len(collected["evidence"]),
            len(collected["tool_calls"]),
        )
        return collected

    def _collect_benchmarks(
        self, results: list[FundCollectionResult]
    ) -> tuple[list[Evidence], list[ToolCallRecord]]:
        """按基准代码去重拉取指数日线；失败降级（无证据、保留失败记录）。"""
        codes: list[str] = []
        for r in results:
            if r.benchmark_code and r.benchmark_code not in codes:
                codes.append(r.benchmark_code)
        evidence: list[Evidence] = []
        records: list[ToolCallRecord] = []
        for code in codes:
            points, record = record_tool_call(self._tools.get_index_data, {"index_id": code})
            records.append(record)
            if record.success and points:
                evidence.append(index_evidence(code, points))
            elif not record.success:
                logger.warning("index %s fetch failed, excess return skipped", code)
        return evidence, records

    def _collect_fund(self, code: str) -> FundCollectionResult:
        """采集单只基金：info/performance/holdings/行业配置/费率/业绩排名/评级 + 资产配置，失败降级并记录问题。"""
        result = FundCollectionResult(fund_id=code)

        # 同一基金的工具相互独立并发执行；资产配置依赖持仓最新报告期，
        # 须等 holdings 完成后提交（仍复用同一线程池）；结果按固定顺序取回
        with ThreadPoolExecutor(max_workers=COLLECTOR_TOOL_CONCURRENCY) as pool:
            futures = {
                "info": pool.submit(record_tool_call, self._tools.get_fund_info, {"fund_id": code}),
                "performance": pool.submit(record_tool_call, self._tools.get_fund_performance, {"fund_id": code}),
                "holdings": pool.submit(record_tool_call, self._tools.get_fund_holdings, {"fund_id": code}),
                "industry": pool.submit(record_tool_call, self._tools.get_fund_industry_alloc, {"fund_id": code}),
                "fees": pool.submit(record_tool_call, self._tools.get_fund_fees, {"fund_id": code}),
                "achievement": pool.submit(record_tool_call, self._tools.get_fund_achievement, {"fund_id": code}),
                "rating": pool.submit(record_tool_call, self._tools.get_fund_rating, {"fund_id": code}),
            }
            fund, info_record = futures["info"].result()
            perf, perf_record = futures["performance"].result()
            holdings, holdings_record = futures["holdings"].result()
            industry, industry_record = futures["industry"].result()
            fees, fees_record = futures["fees"].result()
            achievement, achievement_record = futures["achievement"].result()
            rating, rating_record = futures["rating"].result()
            allocation, allocation_record = pool.submit(
                record_tool_call, self._tools.get_fund_asset_allocation, {"fund_id": code}
            ).result()

        result.tool_calls.extend([
            info_record,
            perf_record,
            holdings_record,
            industry_record,
            allocation_record,
            fees_record,
            achievement_record,
            rating_record,
        ])

        if not info_record.success and not perf_record.success:
            result.issues.append(f"{code}: 基金数据获取完全失败")
            return result

        fund = fund if info_record.success else None
        perf = perf if perf_record.success else None

        if not info_record.success:
            result.issues.append(f"{code}: 基金基本信息缺失（get_fund_info 失败）")
        if not perf_record.success:
            result.issues.append(f"{code}: 基金净值序列缺失（get_fund_performance 失败）")
        elif perf is not None and perf.data_quality == DataQuality.MISSING:
            result.issues.append(f"{code}: 净值序列为空，data_quality=missing")

        # 业务正常为空 vs 数据源失败的区分：
        # - holdings 为空：债基/货基正常披露 → 仅 missing 质量证据，不记 issue
        # - detail 为空：真实基金必有基本信息，空返回 = 数据源异常 → 记 issue
        # - nav 为空：真实基金必有净值历史，空序列 = 数据源异常 → 记 issue
        # - 行业配置/资产配置/费率/评级为空：非股基或无评级属正常披露 → 静默跳过
        detail_empty = info_record.success and fund is not None and not fund.name and not fund.fund_type
        if detail_empty:
            result.issues.append(f"{code}: 基金基本信息为空（数据源可能异常或代码不存在）")

        holdings_failure = holdings_record.success and not holdings
        if not holdings_record.success:
            result.issues.append(f"{code}: 股票持仓获取失败（get_fund_holdings 失败）")
        elif holdings_failure:
            logger.info("holdings: %s 无股票持仓披露（非股票型基金属正常）", code)

        # 持仓时效披露：报告期早于当前年即记 issue，经 data_quality_issues →
        # thesis.data_gaps 强制进入报告「数据缺口与局限」，杜绝拿旧持仓当最新数据用
        if holdings_record.success and holdings:
            period = latest_report_period(holdings)
            parsed = parse_report_period(period)
            if parsed and parsed[0] < datetime.now().year:
                result.issues.append(f"{code}: 股票持仓最新报告期为 {period}，非当前年度披露")

        if fund is not None:
            result.benchmark_code = resolve_benchmark_code(fund)
            result.summary = summarize_fund(fund)
            result.evidence.append(fund_evidence(fund))
        if perf is not None:
            result.evidence.append(performance_evidence(perf))
        result.evidence.append(
            holdings_evidence(
                code,
                holdings if holdings_record.success else [],
                failed=not holdings_record.success,
            )
        )
        if industry_record.success and industry:
            result.evidence.append(industry_evidence(code, industry))
        if allocation_record.success and allocation:
            result.evidence.append(allocation_evidence(code, allocation))
        if fees_record.success and fees is not None and fees.management_fee_rate is not None:
            result.evidence.append(fees_evidence(code, fees))
        if achievement_record.success and achievement:
            result.evidence.append(achievement_evidence(code, achievement))
        if rating_record.success and rating:
            result.evidence.append(rating_evidence(code, rating))
        return result


__all__ = ["CollectorNode", "FundCollectionResult"]
