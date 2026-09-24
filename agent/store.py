"""外部 Store（内存 dict）—— 存放完整原始数据。

State 合同（§2 State Rules 1）：State 只保存跨 Node 共享的摘要与 ID，
完整数据按需存放于外部 Store。raw_ref 形如 "store:funds/{code}"。
"""

from domain.fund import (
    AchievementRow,
    AssetAllocRow,
    FeeInfo,
    Fund,
    FundRating,
    Holding,
    IndexPoint,
    IndustryAllocRow,
    NAVPoint,
)


class FundStore:
    """进程内简单存储。V1 单次运行即可，无需持久化。"""

    def __init__(self) -> None:
        self._funds: dict[str, Fund] = {}
        self._nav_series: dict[str, list[NAVPoint]] = {}
        self._holdings: dict[str, list[Holding]] = {}
        self._industry: dict[str, list[IndustryAllocRow]] = {}
        self._allocation: dict[str, list[AssetAllocRow]] = {}
        self._fees: dict[str, FeeInfo] = {}
        self._achievement: dict[str, list[AchievementRow]] = {}
        self._rating: dict[str, list[FundRating]] = {}
        self._index_series: dict[str, list[IndexPoint]] = {}

    # ---- Fund ----

    def put_fund(self, fund: Fund) -> None:
        self._funds[fund.id] = fund

    def get_fund(self, code: str) -> Fund | None:
        return self._funds.get(code)

    # ---- NAV series ----

    def put_nav_series(self, code: str, points: list[NAVPoint]) -> None:
        self._nav_series[code] = points

    def get_nav_series(self, code: str) -> list[NAVPoint]:
        return self._nav_series.get(code, [])

    # ---- Holdings ----

    def put_holdings(self, code: str, holdings: list[Holding]) -> None:
        self._holdings[code] = holdings

    def get_holdings(self, code: str) -> list[Holding]:
        return self._holdings.get(code, [])

    # ---- Industry / Allocation / Fees / Achievement / Rating ----

    def put_industry(self, code: str, rows: list[IndustryAllocRow]) -> None:
        self._industry[code] = rows

    def get_industry(self, code: str) -> list[IndustryAllocRow]:
        return self._industry.get(code, [])

    def put_allocation(self, code: str, rows: list[AssetAllocRow]) -> None:
        self._allocation[code] = rows

    def get_allocation(self, code: str) -> list[AssetAllocRow]:
        return self._allocation.get(code, [])

    def put_fees(self, code: str, fees: FeeInfo) -> None:
        self._fees[code] = fees

    def get_fees(self, code: str) -> FeeInfo | None:
        return self._fees.get(code)

    def put_achievement(self, code: str, rows: list[AchievementRow]) -> None:
        self._achievement[code] = rows

    def get_achievement(self, code: str) -> list[AchievementRow]:
        return self._achievement.get(code, [])

    def put_rating(self, code: str, ratings: list[FundRating]) -> None:
        self._rating[code] = ratings

    def get_rating(self, code: str) -> list[FundRating]:
        return self._rating.get(code, [])

    # ---- Index series（基准指数，按指数代码存放） ----

    def put_index_series(self, index_code: str, points: list[IndexPoint]) -> None:
        self._index_series[index_code] = points

    def get_index_series(self, index_code: str) -> list[IndexPoint]:
        return self._index_series.get(index_code, [])

    # ---- raw_ref 约定 ----

    @staticmethod
    def fund_ref(code: str) -> str:
        return f"store:funds/{code}"

    @staticmethod
    def nav_ref(code: str) -> str:
        return f"store:nav/{code}"

    @staticmethod
    def holdings_ref(code: str) -> str:
        return f"store:holdings/{code}"

    @staticmethod
    def industry_ref(code: str) -> str:
        return f"store:industry/{code}"

    @staticmethod
    def allocation_ref(code: str) -> str:
        return f"store:allocation/{code}"

    @staticmethod
    def fees_ref(code: str) -> str:
        return f"store:fees/{code}"

    @staticmethod
    def achievement_ref(code: str) -> str:
        return f"store:achievement/{code}"

    @staticmethod
    def rating_ref(code: str) -> str:
        return f"store:rating/{code}"

    @staticmethod
    def index_ref(index_code: str) -> str:
        return f"store:index/{index_code}"


__all__ = ["FundStore"]
