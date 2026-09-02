package marketdata

import (
	"context"
	"time"

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
