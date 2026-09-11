"""外部 Store（内存 dict）—— 存放完整原始数据。

State 合同（§2 State Rules 1）：State 只保存跨 Node 共享的摘要与 ID，
完整数据按需存放于外部 Store。raw_ref 形如 "store:funds/{code}"。
"""

from domain.fund import Fund, Holding, NAVPoint


class FundStore:
    """进程内简单存储。V1 单次运行即可，无需持久化。"""

    def __init__(self) -> None:
        self._funds: dict[str, Fund] = {}
        self._nav_series: dict[str, list[NAVPoint]] = {}
        self._holdings: dict[str, list[Holding]] = {}

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


__all__ = ["FundStore"]
