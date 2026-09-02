package nav

import (
	"context"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// Repository persists fund NAV time-series. NAV is its own aggregate
// (one per fund per day). Money-market funds have a different shape and
// belong to MoneyFundRepository.
type Repository interface {
	GetByFundCode(ctx context.Context, code shared.FundCode, start, end time.Time) ([]NAV, error)
	GetLatest(ctx context.Context, code shared.FundCode) (*NAV, error)
	GetLatestBatch(ctx context.Context, codes []shared.FundCode) (map[shared.FundCode]*NAV, error)
	BatchSave(ctx context.Context, navs []NAV) (inserted int, err error)
	GetLatestDate(ctx context.Context, code shared.FundCode) (*time.Time, error)
}

// MoneyFundRepository persists money-market fund yield data.
// Separate aggregate from NAV: different fields (SevenDayYield vs UnitNAV),
// different table, different lifecycle.
type MoneyFundRepository interface {
	BatchSave(ctx context.Context, navs []MoneyFundNAV) error
}
