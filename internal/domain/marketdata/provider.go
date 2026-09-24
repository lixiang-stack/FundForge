package marketdata

import (
	"context"
	"time"

	"github.com/lixiang/fundforge/internal/domain/benchmark"
	"github.com/lixiang/fundforge/internal/domain/nav"
)

type FundProvider interface {
	FetchFundDetail(ctx context.Context, code string) (*FundDetail, error)
	FetchFundNAV(ctx context.Context, code string, indicator string, period string) ([]nav.NAV, error)
}

type TradeCalendarProvider interface {
	FetchTradeCalendar(ctx context.Context) ([]time.Time, error)
}

type CorporateActionProvider interface {
	FetchDividends(ctx context.Context) ([]DividendRaw, error)
	FetchSplits(ctx context.Context) ([]SplitRaw, error)
}

// IndexProvider exposes benchmark index daily data for excess-return /
// beta computations. indexCode is the bare DB code (e.g. "000905");
// the adapter maps it to the data-source symbol format.
type IndexProvider interface {
	FetchIndexDaily(ctx context.Context, indexCode string, start, end time.Time) ([]benchmark.BenchmarkDaily, error)
}
