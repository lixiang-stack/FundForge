package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/shared"
)

// AlertRepo implements alert.AlertRepository.
type AlertRepo struct {
	pool *pgxpool.Pool
}

func NewAlertRepo(pool *pgxpool.Pool) *AlertRepo {
	return &AlertRepo{pool: pool}
}

const alertColumns = `id, fund_code, strategy_id, status, severity, data_date,
	triggered_at, recovered_at, confirmed_at,
	indicator_snapshot, condition_snapshot, message,
	created_at, updated_at`

func scanAlert(row pgx.Row) (*alert.Alert, error) {
	var a alert.Alert
	var status, severity string
	var indicatorJSON, conditionJSON []byte
	err := row.Scan(
		&a.ID, &a.FundCode, &a.StrategyID, &status, &severity, &a.DataDate,
		&a.TriggeredAt, &a.RecoveredAt, &a.ConfirmedAt,
		&indicatorJSON, &conditionJSON, &a.Message,
		&a.CreatedAt, &a.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	a.Status = alert.Status(status)
	a.Severity = severity
	if indicatorJSON != nil {
		if err := json.Unmarshal(indicatorJSON, &a.IndicatorSnapshot); err != nil {
			log.Printf("WARN AlertRepo: failed to unmarshal indicator_snapshot for alert %d: %v", a.ID, err)
		}
	}
	a.ConditionSnapshot = conditionJSON
	return &a, nil
}

func (r *AlertRepo) GetByID(ctx context.Context, id int64) (*alert.Alert, error) {
	row := r.pool.QueryRow(ctx, `SELECT `+alertColumns+` FROM alert WHERE id = $1`, id)
	a, err := scanAlert(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("AlertRepo.GetByID: %w", err)
	}
	return a, nil
}

func (r *AlertRepo) ListByFund(ctx context.Context, fundCode shared.FundCode, statuses []alert.Status) ([]*alert.Alert, error) {
	statusStrings := make([]string, len(statuses))
	for i, s := range statuses {
		statusStrings[i] = string(s)
	}
	rows, err := r.pool.Query(ctx,
		`SELECT `+alertColumns+` FROM alert WHERE fund_code = $1 AND status = ANY($2) ORDER BY triggered_at DESC`,
		string(fundCode), statusStrings,
	)
	if err != nil {
		return nil, fmt.Errorf("AlertRepo.ListByFund: %w", err)
	}
	return collectAlerts(rows)
}

func (r *AlertRepo) ListActive(ctx context.Context) ([]*alert.Alert, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+alertColumns+` FROM alert WHERE status IN ('triggered','confirmed') ORDER BY triggered_at DESC`,
	)
	if err != nil {
		return nil, fmt.Errorf("AlertRepo.ListActive: %w", err)
	}
	return collectAlerts(rows)
}

func (r *AlertRepo) ListRecent(ctx context.Context, since time.Time) ([]*alert.Alert, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+alertColumns+` FROM alert WHERE triggered_at >= $1 ORDER BY triggered_at DESC`,
		since,
	)
	if err != nil {
		return nil, fmt.Errorf("AlertRepo.ListRecent: %w", err)
	}
	return collectAlerts(rows)
}

func collectAlerts(rows pgx.Rows) ([]*alert.Alert, error) {
	defer rows.Close()
	var list []*alert.Alert
	for rows.Next() {
		a, err := scanAlert(rows)
		if err != nil {
			return nil, err
		}
		list = append(list, a)
	}
	return list, rows.Err()
}

func (r *AlertRepo) Save(ctx context.Context, a *alert.Alert) error {
	indicatorJSON, err := json.Marshal(a.IndicatorSnapshot)
	if err != nil {
		return fmt.Errorf("AlertRepo.Save: marshal indicator_snapshot: %w", err)
	}
	err = r.pool.QueryRow(ctx, `
		INSERT INTO alert (fund_code, strategy_id, status, severity, data_date,
			triggered_at, recovered_at, confirmed_at,
			indicator_snapshot, condition_snapshot, message)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`,
		a.FundCode, a.StrategyID, string(a.Status), a.Severity, a.DataDate,
		a.TriggeredAt, a.RecoveredAt, a.ConfirmedAt,
		indicatorJSON, a.ConditionSnapshot, a.Message,
	).Scan(&a.ID)
	if err != nil {
		return fmt.Errorf("AlertRepo.Save: %w", err)
	}
	return nil
}

func (r *AlertRepo) UpdateStatus(ctx context.Context, a *alert.Alert) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE alert SET status=$2, recovered_at=$3, confirmed_at=$4, updated_at=NOW() WHERE id=$1`,
		a.ID, string(a.Status), a.RecoveredAt, a.ConfirmedAt,
	)
	if err != nil {
		return fmt.Errorf("AlertRepo.UpdateStatus: %w", err)
	}
	return nil
}

func (r *AlertRepo) HasRecentAlert(ctx context.Context, strategyID int64, fundCode shared.FundCode, since time.Time) (bool, error) {
	var exists bool
	err := r.pool.QueryRow(ctx,
		`SELECT EXISTS(SELECT 1 FROM alert WHERE strategy_id=$1 AND fund_code=$2 AND triggered_at >= $3 AND status != 'recovered')`,
		strategyID, string(fundCode), since,
	).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("AlertRepo.HasRecentAlert: %w", err)
	}
	return exists, nil
}

var _ alert.AlertRepository = (*AlertRepo)(nil)
