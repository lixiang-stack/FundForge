// Package calendar owns the trading calendar aggregate.
//
// TradeDate is the aggregate root: each calendar date is its own aggregate.
// The Repository exposes calendar-aware queries (next trading day,
// trading days between two dates, etc.) so callers don't reimplement the
// same date-arithmetic.
package calendar

import "time"

// TradeDate records whether a calendar date is a trading day.
type TradeDate struct {
	Date         time.Time
	IsTradingDay bool
}
