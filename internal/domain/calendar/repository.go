package calendar

import (
	"context"
	"time"
)

// Repository defines persistence operations for trading calendar data.
type Repository interface {
	IsTradingDay(ctx context.Context, date time.Time) (bool, error)
	GetTradingDaysBetween(ctx context.Context, start, end time.Time) ([]time.Time, error)
	GetRecentTradingDays(ctx context.Context, n int) ([]time.Time, error)
	BatchSave(ctx context.Context, dates []TradeDate) error
}
