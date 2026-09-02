package postgres

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/fund"
)

// FundRepo implements fund.FundRepository.
type FundRepo struct {
	pool *pgxpool.Pool
}

func NewFundRepo(pool *pgxpool.Pool) *FundRepo {
	return &FundRepo{pool: pool}
}

// Column list used by SELECT and scan. The DB has an `id BIGSERIAL` PK but
// it is a surrogate without domain meaning — we do not select it.
const fundColumns = `fund_code, fund_name, fund_type, pinyin_abbr, pinyin_full,
	fund_company, fund_manager, fund_size, fund_size_date, establish_date,
	custodian_bank, management_fee_rate, custodian_fee_rate, benchmark,
	is_subscribed, subscribed_at, unsubscribed_at,
	initial_fetch_done, last_nav_date, last_fetch_at,
	custom_benchmark_code, created_at, updated_at`

func scanFund(row pgx.Row) (*fund.Fund, error) {
	var f fund.Fund
	var isSubscribed bool
	err := row.Scan(
		&f.Code, &f.Name, &f.FundType, &f.PinyinAbbr, &f.PinyinFull,
		&f.Company, &f.Manager, &f.Size, &f.SizeDate, &f.EstablishDate,
		&f.CustodianBank, &f.ManagementFee, &f.CustodianFee, &f.Benchmark,
		&isSubscribed, &f.SubscribedAt, &f.UnsubscribedAt,
		&f.InitialFetchDone, &f.LastNAVDate, &f.LastFetchAt,
		&f.CustomBenchmark, &f.CreatedAt, &f.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	if isSubscribed {
		f.Status = fund.Subscribed
	} else {
		f.Status = fund.Unsubscribed
	}
	return &f, nil
}

func scanFunds(rows pgx.Rows) ([]*fund.Fund, error) {
	defer rows.Close()
	var funds []*fund.Fund
	for rows.Next() {
		f, err := scanFund(rows)
		if err != nil {
			return nil, err
		}
		funds = append(funds, f)
	}
	return funds, rows.Err()
}

func (r *FundRepo) GetByCode(ctx context.Context, code fund.FundCode) (*fund.Fund, error) {
	row := r.pool.QueryRow(ctx, `SELECT `+fundColumns+` FROM fund_info WHERE fund_code = $1`, string(code))
	f, err := scanFund(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("FundRepo.GetByCode: %w", err)
	}
	return f, nil
}

func (r *FundRepo) ListSubscribed(ctx context.Context) ([]*fund.Fund, error) {
	rows, err := r.pool.Query(ctx, `SELECT `+fundColumns+` FROM fund_info WHERE is_subscribed = TRUE ORDER BY fund_code`)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.ListSubscribed: %w", err)
	}
	funds, err := scanFunds(rows)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.ListSubscribed: %w", err)
	}
	return funds, nil
}

func (r *FundRepo) ListAll(ctx context.Context) ([]*fund.Fund, error) {
	rows, err := r.pool.Query(ctx, `SELECT `+fundColumns+` FROM fund_info ORDER BY fund_code`)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.ListAll: %w", err)
	}
	funds, err := scanFunds(rows)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.ListAll: %w", err)
	}
	return funds, nil
}

func (r *FundRepo) Save(ctx context.Context, f *fund.Fund) error {
	isSubscribed := f.Status == fund.Subscribed
	_, err := r.pool.Exec(ctx, `
		INSERT INTO fund_info (
			fund_code, fund_name, fund_type, pinyin_abbr, pinyin_full,
			fund_company, fund_manager, fund_size, fund_size_date, establish_date,
			custodian_bank, management_fee_rate, custodian_fee_rate, benchmark,
			is_subscribed, subscribed_at, unsubscribed_at,
			initial_fetch_done, last_nav_date, last_fetch_at,
			custom_benchmark_code, updated_at
		) VALUES (
			$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,NOW()
		)
		ON CONFLICT (fund_code) DO UPDATE SET
			fund_name = EXCLUDED.fund_name,
			fund_type = COALESCE(EXCLUDED.fund_type, fund_info.fund_type),
			pinyin_abbr = COALESCE(EXCLUDED.pinyin_abbr, fund_info.pinyin_abbr),
			pinyin_full = COALESCE(EXCLUDED.pinyin_full, fund_info.pinyin_full),
			fund_company = COALESCE(EXCLUDED.fund_company, fund_info.fund_company),
			fund_manager = COALESCE(EXCLUDED.fund_manager, fund_info.fund_manager),
			fund_size = COALESCE(EXCLUDED.fund_size, fund_info.fund_size),
			fund_size_date = COALESCE(EXCLUDED.fund_size_date, fund_info.fund_size_date),
			establish_date = COALESCE(EXCLUDED.establish_date, fund_info.establish_date),
			custodian_bank = COALESCE(EXCLUDED.custodian_bank, fund_info.custodian_bank),
			management_fee_rate = COALESCE(EXCLUDED.management_fee_rate, fund_info.management_fee_rate),
			custodian_fee_rate = COALESCE(EXCLUDED.custodian_fee_rate, fund_info.custodian_fee_rate),
			benchmark = COALESCE(EXCLUDED.benchmark, fund_info.benchmark),
			is_subscribed = EXCLUDED.is_subscribed,
			subscribed_at = COALESCE(EXCLUDED.subscribed_at, fund_info.subscribed_at),
			unsubscribed_at = EXCLUDED.unsubscribed_at,
			updated_at = NOW()`,
		string(f.Code), f.Name, f.FundType, f.PinyinAbbr, f.PinyinFull,
		f.Company, f.Manager, f.Size, f.SizeDate, f.EstablishDate,
		f.CustodianBank, f.ManagementFee, f.CustodianFee, f.Benchmark,
		isSubscribed, f.SubscribedAt, f.UnsubscribedAt,
		f.InitialFetchDone, f.LastNAVDate, f.LastFetchAt,
		f.CustomBenchmark,
	)
	if err != nil {
		return fmt.Errorf("FundRepo.Save: %w", err)
	}
	return nil
}

func (r *FundRepo) UpdateFetchStatus(ctx context.Context, code fund.FundCode, lastNAVDate time.Time, fetchedAt time.Time) error {
	_, err := r.pool.Exec(ctx,
		`UPDATE fund_info SET last_nav_date = $2, last_fetch_at = $3, initial_fetch_done = TRUE, updated_at = NOW() WHERE fund_code = $1`,
		string(code), lastNAVDate, fetchedAt,
	)
	if err != nil {
		return fmt.Errorf("FundRepo.UpdateFetchStatus: %w", err)
	}
	return nil
}

func (r *FundRepo) Search(ctx context.Context, query string, limit int) ([]*fund.Fund, error) {
	pattern := "%" + query + "%"
	rows, err := r.pool.Query(ctx,
		`SELECT `+fundColumns+` FROM fund_info WHERE fund_code ILIKE $1 OR fund_name ILIKE $1 OR pinyin_abbr ILIKE $1 ORDER BY fund_code LIMIT $2`,
		pattern, limit,
	)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.Search: %w", err)
	}
	funds, err := scanFunds(rows)
	if err != nil {
		return nil, fmt.Errorf("FundRepo.Search: %w", err)
	}
	return funds, nil
}

func (r *FundRepo) SaveDividends(ctx context.Context, dividends []fund.Dividend) error {
	if len(dividends) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for _, d := range dividends {
		batch.Queue(
			`INSERT INTO fund_dividend (fund_code, fund_name, record_date, ex_date, dividend_per_unit, pay_date)
			 VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (fund_code, ex_date, dividend_per_unit) DO NOTHING`,
			d.FundCode, d.FundName, d.RecordDate, d.ExDate, d.DividendPerUnit, d.PayDate,
		)
	}
	br := r.pool.SendBatch(ctx, batch)
	defer br.Close()
	for range dividends {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("FundRepo.SaveDividends: %w", err)
		}
	}
	return nil
}

func (r *FundRepo) SaveSplits(ctx context.Context, splits []fund.Split) error {
	if len(splits) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for _, s := range splits {
		batch.Queue(
			`INSERT INTO fund_split (fund_code, fund_name, split_date, split_type, split_ratio)
			 VALUES ($1,$2,$3,$4,$5) ON CONFLICT (fund_code, split_date) DO NOTHING`,
			s.FundCode, s.FundName, s.SplitDate, s.SplitType, s.SplitRatio,
		)
	}
	br := r.pool.SendBatch(ctx, batch)
	defer br.Close()
	for range splits {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("FundRepo.SaveSplits: %w", err)
		}
	}
	return nil
}

func (r *FundRepo) SaveManagerChange(ctx context.Context, mc fund.ManagerChange) error {
	_, err := r.pool.Exec(ctx,
		`INSERT INTO fund_manager_change (fund_code, detected_at, previous_manager, current_manager, change_date) VALUES ($1,$2,$3,$4,$5)`,
		mc.FundCode, mc.DetectedAt, mc.PreviousManager, mc.CurrentManager, mc.ChangeDate,
	)
	if err != nil {
		return fmt.Errorf("FundRepo.SaveManagerChange: %w", err)
	}
	return nil
}

func (r *FundRepo) GetLatestManager(ctx context.Context, code fund.FundCode) (string, error) {
	var manager string
	err := r.pool.QueryRow(ctx,
		`SELECT COALESCE(fund_manager, '') FROM fund_info WHERE fund_code = $1`, string(code),
	).Scan(&manager)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("FundRepo.GetLatestManager: %w", err)
	}
	return manager, nil
}

func (r *FundRepo) SaveStockHoldings(ctx context.Context, holdings []fund.StockHolding) error {
	if len(holdings) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for _, h := range holdings {
		batch.Queue(
			`INSERT INTO fund_holding_stock (fund_code, report_date, stock_code, stock_name, hold_ratio, hold_shares, hold_value)
			 VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (fund_code, report_date, stock_code) DO NOTHING`,
			h.FundCode, h.ReportDate, h.StockCode, h.StockName, h.HoldRatio, h.HoldShares, h.HoldValue,
		)
	}
	br := r.pool.SendBatch(ctx, batch)
	defer br.Close()
	for range holdings {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("FundRepo.SaveStockHoldings: %w", err)
		}
	}
	return nil
}

func (r *FundRepo) SaveBondHoldings(ctx context.Context, holdings []fund.BondHolding) error {
	if len(holdings) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for _, h := range holdings {
		batch.Queue(
			`INSERT INTO fund_holding_bond (fund_code, report_date, bond_code, bond_name, hold_ratio, hold_value)
			 VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (fund_code, report_date, bond_code) DO NOTHING`,
			h.FundCode, h.ReportDate, h.BondCode, h.BondName, h.HoldRatio, h.HoldValue,
		)
	}
	br := r.pool.SendBatch(ctx, batch)
	defer br.Close()
	for range holdings {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("FundRepo.SaveBondHoldings: %w", err)
		}
	}
	return nil
}

// Delete permanently removes a fund and its associated NAV data.
func (r *FundRepo) Delete(ctx context.Context, code fund.FundCode) error {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("FundRepo.Delete: begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Delete associated NAV data.
	if _, err := tx.Exec(ctx, `DELETE FROM fund_nav WHERE fund_code = $1`, string(code)); err != nil {
		return fmt.Errorf("FundRepo.Delete: delete nav: %w", err)
	}

	// Delete fund info.
	result, err := tx.Exec(ctx, `DELETE FROM fund_info WHERE fund_code = $1`, string(code))
	if err != nil {
		return fmt.Errorf("FundRepo.Delete: delete fund: %w", err)
	}
	if result.RowsAffected() == 0 {
		return fmt.Errorf("FundRepo.Delete: fund not found")
	}

	return tx.Commit(ctx)
}

var _ fund.FundRepository = (*FundRepo)(nil)
var _ fund.CorporateActionRepository = (*FundRepo)(nil)
var _ fund.HoldingsRepository = (*FundRepo)(nil)
