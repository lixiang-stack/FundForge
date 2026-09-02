package benchmark

import (
	"context"
	"time"
)

// Repository defines persistence operations for benchmark index data.
type Repository interface {
	GetAllIndices(ctx context.Context) ([]BenchmarkIndex, error)
	GetDefaultForFundType(ctx context.Context, fundType string) (*BenchmarkIndex, error)
	GetDailyData(ctx context.Context, indexCode string, start, end time.Time) ([]BenchmarkDaily, error)
	BatchSaveDailyData(ctx context.Context, data []BenchmarkDaily) error
}
