package postgres

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/calendar"
)

// CalendarRepo implements calendar.Repository.
type CalendarRepo struct {
	pool *pgxpool.Pool
}

func NewCalendarRepo(pool *pgxpool.Pool) *CalendarRepo {
	return &CalendarRepo{pool: pool}
}

func (r *CalendarRepo) IsTradingDay(ctx context.Context, date time.Time) (bool, error) {
	var exists bool
	err := r.pool.QueryRow(ctx,
		`SELECT EXISTS(SELECT 1 FROM trade_calendar WHERE trade_date = $1 AND is_trading_day = TRUE)`,
		date,
	).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("CalendarRepo.IsTradingDay: %w", err)
	}
	return exists, nil
}

func (r *CalendarRepo) GetTradingDaysBetween(ctx context.Context, start, end time.Time) ([]time.Time, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT trade_date FROM trade_calendar WHERE trade_date BETWEEN $1 AND $2 AND is_trading_day = TRUE ORDER BY trade_date`,
		start, end,
	)
	if err != nil {
		return nil, fmt.Errorf("CalendarRepo.GetTradingDaysBetween: %w", err)
	}
	defer rows.Close()

	dates, err := pgx.CollectRows(rows, pgx.RowTo[time.Time])
	if err != nil {
		return nil, fmt.Errorf("CalendarRepo.GetTradingDaysBetween: collect: %w", err)
	}
	return dates, nil
}

func (r *CalendarRepo) GetRecentTradingDays(ctx context.Context, n int) ([]time.Time, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT trade_date FROM trade_calendar WHERE trade_date <= CURRENT_DATE AND is_trading_day = TRUE ORDER BY trade_date DESC LIMIT $1`,
		n,
	)
	if err != nil {
		return nil, fmt.Errorf("CalendarRepo.GetRecentTradingDays: %w", err)
	}
	defer rows.Close()

	dates, err := pgx.CollectRows(rows, pgx.RowTo[time.Time])
	if err != nil {
		return nil, fmt.Errorf("CalendarRepo.GetRecentTradingDays: collect: %w", err)
	}
	return dates, nil
}

func (r *CalendarRepo) BatchSave(ctx context.Context, dates []calendar.TradeDate) error {
	if len(dates) == 0 {
		return nil
	}

	batch := &pgx.Batch{}
	for _, d := range dates {
		batch.Queue(
			`INSERT INTO trade_calendar (trade_date, is_trading_day) VALUES ($1, $2) ON CONFLICT (trade_date) DO NOTHING`,
			d.Date, d.IsTradingDay,
		)
	}

	br := r.pool.SendBatch(ctx, batch)
	defer br.Close()

	for range dates {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("CalendarRepo.BatchSave: %w", err)
		}
	}
	return nil
}

var _ calendar.Repository = (*CalendarRepo)(nil)
