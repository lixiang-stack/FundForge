package postgres

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
)

// NAVRepo implements nav.Repository.
type NAVRepo struct {
	pool *pgxpool.Pool
}

func NewNAVRepo(pool *pgxpool.Pool) *NAVRepo {
	return &NAVRepo{pool: pool}
}

func (r *NAVRepo) GetByFundCode(ctx context.Context, code shared.FundCode, start, end time.Time) ([]nav.NAV, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT id, fund_code, nav_date, unit_nav, acc_nav, daily_return, fetched_at
		 FROM fund_nav WHERE fund_code = $1 AND nav_date BETWEEN $2 AND $3 ORDER BY nav_date`,
		code, start, end,
	)
	if err != nil {
		return nil, fmt.Errorf("NAVRepo.GetByFundCode: %w", err)
	}
	defer rows.Close()

	var navs []nav.NAV
	for rows.Next() {
		var n nav.NAV
		if err := rows.Scan(&n.ID, &n.FundCode, &n.Date, &n.UnitNAV, &n.AccNAV, &n.DailyReturn, &n.FetchedAt); err != nil {
			return nil, fmt.Errorf("NAVRepo.GetByFundCode: scan: %w", err)
		}
		navs = append(navs, n)
	}
	return navs, rows.Err()
}

func (r *NAVRepo) GetLatest(ctx context.Context, code shared.FundCode) (*nav.NAV, error) {
	var n nav.NAV
	err := r.pool.QueryRow(ctx,
		`SELECT id, fund_code, nav_date, unit_nav, acc_nav, daily_return, fetched_at
		 FROM fund_nav WHERE fund_code = $1 ORDER BY nav_date DESC LIMIT 1`,
		code,
	).Scan(&n.ID, &n.FundCode, &n.Date, &n.UnitNAV, &n.AccNAV, &n.DailyReturn, &n.FetchedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("NAVRepo.GetLatest: %w", err)
	}
	return &n, nil
}

// GetLatestBatch returns the latest NAV for each of the given fund codes in a single query.
func (r *NAVRepo) GetLatestBatch(ctx context.Context, codes []shared.FundCode) (map[shared.FundCode]*nav.NAV, error) {
	if len(codes) == 0 {
		return map[shared.FundCode]*nav.NAV{}, nil
	}
	codeStrs := make([]string, len(codes))
	for i, c := range codes {
		codeStrs[i] = string(c)
	}
	rows, err := r.pool.Query(ctx, `
		SELECT DISTINCT ON (fund_code) id, fund_code, nav_date, unit_nav, acc_nav, daily_return, fetched_at
		FROM fund_nav
		WHERE fund_code = ANY($1)
		ORDER BY fund_code, nav_date DESC`,
		codeStrs,
	)
	if err != nil {
		return nil, fmt.Errorf("NAVRepo.GetLatestBatch: %w", err)
	}
	defer rows.Close()

	result := make(map[shared.FundCode]*nav.NAV, len(codes))
	for rows.Next() {
		var n nav.NAV
		if err := rows.Scan(&n.ID, &n.FundCode, &n.Date, &n.UnitNAV, &n.AccNAV, &n.DailyReturn, &n.FetchedAt); err != nil {
			return nil, fmt.Errorf("NAVRepo.GetLatestBatch: scan: %w", err)
		}
		result[n.FundCode] = &n
	}
	return result, rows.Err()
}

// BatchSave inserts NAV records using unnest arrays for performance.
// Returns the number of actually inserted rows (ON CONFLICT DO NOTHING skips duplicates).
func (r *NAVRepo) BatchSave(ctx context.Context, navs []nav.NAV) (int, error) {
	if len(navs) == 0 {
		return 0, nil
	}

	codes := make([]string, len(navs))
	dates := make([]time.Time, len(navs))
	unitNAVs := make([]float64, len(navs))
	accNAVs := make([]float64, len(navs))
	returns := make([]float64, len(navs))
	fetchedAts := make([]time.Time, len(navs))

	for i, n := range navs {
		codes[i] = string(n.FundCode)
		dates[i] = n.Date
		unitNAVs[i] = n.UnitNAV
		accNAVs[i] = n.AccNAV
		returns[i] = n.DailyReturn
		fetchedAts[i] = n.FetchedAt
	}

	tag, err := r.pool.Exec(ctx, `
		INSERT INTO fund_nav (fund_code, nav_date, unit_nav, acc_nav, daily_return, fetched_at)
		SELECT * FROM unnest($1::text[], $2::date[], $3::numeric[], $4::numeric[], $5::numeric[], $6::timestamptz[])
		ON CONFLICT (fund_code, nav_date) DO NOTHING`,
		codes, dates, unitNAVs, accNAVs, returns, fetchedAts,
	)
	if err != nil {
		return 0, fmt.Errorf("NAVRepo.BatchSave: %w", err)
	}
	return int(tag.RowsAffected()), nil
}

func (r *NAVRepo) GetLatestDate(ctx context.Context, code shared.FundCode) (*time.Time, error) {
	var d *time.Time
	err := r.pool.QueryRow(ctx,
		`SELECT MAX(nav_date) FROM fund_nav WHERE fund_code = $1`, code,
	).Scan(&d)
	if err != nil {
		return nil, fmt.Errorf("NAVRepo.GetLatestDate: %w", err)
	}
	return d, nil
}

var _ nav.Repository = (*NAVRepo)(nil)

// MoneyFundNAVRepo implements nav.MoneyFundRepository.
// It is a separate aggregate from NAV: different table, different shape.
type MoneyFundNAVRepo struct {
	pool *pgxpool.Pool
}

func NewMoneyFundNAVRepo(pool *pgxpool.Pool) *MoneyFundNAVRepo {
	return &MoneyFundNAVRepo{pool: pool}
}

// BatchSave inserts money-market fund yield records.
func (r *MoneyFundNAVRepo) BatchSave(ctx context.Context, navs []nav.MoneyFundNAV) error {
	if len(navs) == 0 {
		return nil
	}

	codes := make([]string, len(navs))
	dates := make([]time.Time, len(navs))
	incomes := make([]float64, len(navs))
	yields := make([]float64, len(navs))
	fetchedAts := make([]time.Time, len(navs))

	for i, n := range navs {
		codes[i] = string(n.FundCode)
		dates[i] = n.Date
		incomes[i] = n.IncomePerTenThousand
		yields[i] = n.SevenDayYield
		fetchedAts[i] = n.FetchedAt
	}

	_, err := r.pool.Exec(ctx, `
		INSERT INTO fund_money_nav (fund_code, nav_date, income_per_ten_thousand, seven_day_yield, fetched_at)
		SELECT * FROM unnest($1::text[], $2::date[], $3::numeric[], $4::numeric[], $5::timestamptz[])
		ON CONFLICT (fund_code, nav_date) DO NOTHING`,
		codes, dates, incomes, yields, fetchedAts,
	)
	if err != nil {
		return fmt.Errorf("MoneyFundNAVRepo.BatchSave: %w", err)
	}
	return nil
}

var _ nav.MoneyFundRepository = (*MoneyFundNAVRepo)(nil)
