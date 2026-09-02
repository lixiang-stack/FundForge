// Package benchmark owns the benchmark index aggregate.
//
// Aggregate root: BenchmarkIndex (e.g. CSI-300, CSI-500) — each index is
// its own aggregate identified by IndexCode. BenchmarkDaily is a separate
// aggregate (one per index per day) that stores time-series close/return
// data; it references BenchmarkIndex by IndexCode but does not belong to
// the same aggregate.
package benchmark

import "time"

// BenchmarkIndex represents a benchmark index that can be used to
// compare fund performance against.
type BenchmarkIndex struct {
	ID                  int64
	IndexCode           string
	IndexName           string
	ApplicableFundTypes []string
	IsDefault           bool
	CreatedAt           time.Time
}

// BenchmarkDaily stores daily close/return data for a benchmark index.
type BenchmarkDaily struct {
	ID          int64
	IndexCode   string
	TradeDate   time.Time
	ClosePrice  float64
	DailyReturn float64
	FetchedAt   time.Time
}
