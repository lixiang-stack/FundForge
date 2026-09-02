package fund

import (
	"context"
	"time"
)

// FundRepository defines persistence operations for fund aggregate root.
type FundRepository interface {
	GetByCode(ctx context.Context, code FundCode) (*Fund, error)
	ListSubscribed(ctx context.Context) ([]*Fund, error)
	ListAll(ctx context.Context) ([]*Fund, error)
	Save(ctx context.Context, f *Fund) error
	Delete(ctx context.Context, code FundCode) error
	UpdateFetchStatus(ctx context.Context, code FundCode, lastNAVDate time.Time, fetchedAt time.Time) error
	Search(ctx context.Context, query string, limit int) ([]*Fund, error)
}

// CorporateActionRepository defines persistence for dividends, splits, and manager changes.
type CorporateActionRepository interface {
	SaveDividends(ctx context.Context, dividends []Dividend) error
	SaveSplits(ctx context.Context, splits []Split) error
	SaveManagerChange(ctx context.Context, mc ManagerChange) error
	GetLatestManager(ctx context.Context, code FundCode) (string, error)
}

// HoldingsRepository defines persistence for fund stock/bond holdings.
type HoldingsRepository interface {
	SaveStockHoldings(ctx context.Context, holdings []StockHolding) error
	SaveBondHoldings(ctx context.Context, holdings []BondHolding) error
}
