package postgres

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/benchmark"
)

// BenchmarkRepo implements benchmark.Repository.
type BenchmarkRepo struct {
	pool *pgxpool.Pool
}

func NewBenchmarkRepo(pool *pgxpool.Pool) *BenchmarkRepo {
	return &BenchmarkRepo{pool: pool}
}

func (r *BenchmarkRepo) GetAllIndices(ctx context.Context) ([]benchmark.BenchmarkIndex, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT id, index_code, index_name, applicable_fund_types, is_default, created_at FROM benchmark_index ORDER BY index_code`,
	)
	if err != nil {
		return nil, fmt.Errorf("BenchmarkRepo.GetAllIndices: %w", err)
	}
	defer rows.Close()

	var indices []benchmark.BenchmarkIndex
	for rows.Next() {
		var b benchmark.BenchmarkIndex
		if err := rows.Scan(&b.ID, &b.IndexCode, &b.IndexName, &b.ApplicableFundTypes, &b.IsDefault, &b.CreatedAt); err != nil {
			return nil, fmt.Errorf("BenchmarkRepo.GetAllIndices: scan: %w", err)
		}
		indices = append(indices, b)
	}
	return indices, rows.Err()
}

func (r *BenchmarkRepo) GetDefaultForFundType(ctx context.Context, fundType string) (*benchmark.BenchmarkIndex, error) {
	var b benchmark.BenchmarkIndex
	err := r.pool.QueryRow(ctx,
		`SELECT id, index_code, index_name, applicable_fund_types, is_default, created_at
		 FROM benchmark_index WHERE $1 = ANY(applicable_fund_types) AND is_default = TRUE LIMIT 1`,
		fundType,
	).Scan(&b.ID, &b.IndexCode, &b.IndexName, &b.ApplicableFundTypes, &b.IsDefault, &b.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("BenchmarkRepo.GetDefaultForFundType: %w", err)
	}
	return &b, nil
}

func (r *BenchmarkRepo) GetDailyData(ctx context.Context, indexCode string, start, end time.Time) ([]benchmark.BenchmarkDaily, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT id, index_code, trade_date, close_price, daily_return, fetched_at
		 FROM benchmark_index_daily WHERE index_code = $1 AND trade_date BETWEEN $2 AND $3 ORDER BY trade_date`,
		indexCode, start, end,
	)
	if err != nil {
		return nil, fmt.Errorf("BenchmarkRepo.GetDailyData: %w", err)
	}
	defer rows.Close()

	var data []benchmark.BenchmarkDaily
	for rows.Next() {
		var d benchmark.BenchmarkDaily
		if err := rows.Scan(&d.ID, &d.IndexCode, &d.TradeDate, &d.ClosePrice, &d.DailyReturn, &d.FetchedAt); err != nil {
			return nil, fmt.Errorf("BenchmarkRepo.GetDailyData: scan: %w", err)
		}
		data = append(data, d)
	}
	return data, rows.Err()
}

func (r *BenchmarkRepo) BatchSaveDailyData(ctx context.Context, data []benchmark.BenchmarkDaily) error {
	if len(data) == 0 {
		return nil
	}

	codes := make([]string, len(data))
	dates := make([]time.Time, len(data))
	closes := make([]float64, len(data))
	returns := make([]float64, len(data))
	fetchedAts := make([]time.Time, len(data))

	for i, d := range data {
		codes[i] = d.IndexCode
		dates[i] = d.TradeDate
		closes[i] = d.ClosePrice
		returns[i] = d.DailyReturn
		fetchedAts[i] = d.FetchedAt
	}

	_, err := r.pool.Exec(ctx, `
		INSERT INTO benchmark_index_daily (index_code, trade_date, close_price, daily_return, fetched_at)
		SELECT * FROM unnest($1::text[], $2::date[], $3::numeric[], $4::numeric[], $5::timestamptz[])
		ON CONFLICT (index_code, trade_date) DO NOTHING`,
		codes, dates, closes, returns, fetchedAts,
	)
	if err != nil {
		return fmt.Errorf("BenchmarkRepo.BatchSaveDailyData: %w", err)
	}
	return nil
}

var _ benchmark.Repository = (*BenchmarkRepo)(nil)
