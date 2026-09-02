package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
)

// StrategyRepo implements strategy.StrategyRepository.
type StrategyRepo struct {
	pool *pgxpool.Pool
}

func NewStrategyRepo(pool *pgxpool.Pool) *StrategyRepo {
	return &StrategyRepo{pool: pool}
}

// conditionsJSON is the DB-level JSONB format for strategy conditions.
type conditionsJSON struct {
	Logic      string              `json:"logic"`
	Conditions []conditionItemJSON `json:"conditions"`
}

type conditionItemJSON struct {
	Indicator string          `json:"indicator"`
	Operator  string          `json:"operator"`
	Threshold json.RawMessage `json:"threshold"`
}

func marshalConditions(s *strategy.StrategyTemplate) ([]byte, error) {
	cj := conditionsJSON{Logic: string(s.Logic)}
	for _, c := range s.Conditions {
		th, _ := json.Marshal(c.Threshold)
		cj.Conditions = append(cj.Conditions, conditionItemJSON{
			Indicator: c.Indicator, Operator: string(c.Operator), Threshold: th,
		})
	}
	return json.Marshal(cj)
}

func unmarshalConditions(data []byte, s *strategy.StrategyTemplate) error {
	var cj conditionsJSON
	if err := json.Unmarshal(data, &cj); err != nil {
		return err
	}
	s.Logic = strategy.LogicOp(cj.Logic)
	s.Conditions = make([]strategy.Condition, len(cj.Conditions))
	for i, c := range cj.Conditions {
		// Threshold can be float64 or bool (e.g. "manager_changed" uses true).
		var threshold float64
		if err := json.Unmarshal(c.Threshold, &threshold); err != nil {
			// Try bool: true → 1.0, false → 0.0
			var b bool
			if err2 := json.Unmarshal(c.Threshold, &b); err2 == nil {
				if b {
					threshold = 1.0
				}
			}
		}
		s.Conditions[i] = strategy.Condition{
			Indicator: c.Indicator, Operator: strategy.Operator(c.Operator), Threshold: threshold,
		}
	}
	return nil
}

func scanStrategy(row pgx.Row) (*strategy.StrategyTemplate, error) {
	var s strategy.StrategyTemplate
	var severity, condData string
	err := row.Scan(
		&s.ID, &s.Name, &s.Description, &severity,
		&condData,
		&s.CooldownDays, &s.IsEnabled, &s.IsPreset,
		&s.CreatedAt, &s.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	s.Severity = strategy.Severity(severity)
	if err := unmarshalConditions([]byte(condData), &s); err != nil {
		return nil, fmt.Errorf("unmarshal conditions: %w", err)
	}
	return &s, nil
}

const strategyColumns = `id, name, description, severity, conditions, cooldown_days, is_enabled, is_preset, created_at, updated_at`

func (r *StrategyRepo) GetByID(ctx context.Context, id int64) (*strategy.StrategyTemplate, error) {
	row := r.pool.QueryRow(ctx, `SELECT `+strategyColumns+` FROM strategy_template WHERE id = $1`, id)
	s, err := scanStrategy(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("StrategyRepo.GetByID: %w", err)
	}
	return s, nil
}

func (r *StrategyRepo) ListEnabled(ctx context.Context) ([]*strategy.StrategyTemplate, error) {
	rows, err := r.pool.Query(ctx, `SELECT `+strategyColumns+` FROM strategy_template WHERE is_enabled = TRUE ORDER BY id`)
	if err != nil {
		return nil, fmt.Errorf("StrategyRepo.ListEnabled: %w", err)
	}
	return collectStrategies(rows)
}

func (r *StrategyRepo) ListAll(ctx context.Context) ([]*strategy.StrategyTemplate, error) {
	rows, err := r.pool.Query(ctx, `SELECT `+strategyColumns+` FROM strategy_template ORDER BY id`)
	if err != nil {
		return nil, fmt.Errorf("StrategyRepo.ListAll: %w", err)
	}
	return collectStrategies(rows)
}

func collectStrategies(rows pgx.Rows) ([]*strategy.StrategyTemplate, error) {
	defer rows.Close()
	var list []*strategy.StrategyTemplate
	for rows.Next() {
		s, err := scanStrategy(rows)
		if err != nil {
			return nil, err
		}
		list = append(list, s)
	}
	return list, rows.Err()
}

func (r *StrategyRepo) Save(ctx context.Context, s *strategy.StrategyTemplate) error {
	condBytes, err := marshalConditions(s)
	if err != nil {
		return fmt.Errorf("StrategyRepo.Save: marshal: %w", err)
	}
	err = r.pool.QueryRow(ctx, `
		INSERT INTO strategy_template (name, description, severity, conditions, cooldown_days, is_enabled, is_preset)
		VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id`,
		s.Name, s.Description, string(s.Severity), condBytes,
		s.CooldownDays, s.IsEnabled, s.IsPreset,
	).Scan(&s.ID)
	if err != nil {
		return fmt.Errorf("StrategyRepo.Save: %w", err)
	}
	return nil
}

func (r *StrategyRepo) Update(ctx context.Context, s *strategy.StrategyTemplate) error {
	condBytes, err := marshalConditions(s)
	if err != nil {
		return fmt.Errorf("StrategyRepo.Update: marshal: %w", err)
	}
	_, err = r.pool.Exec(ctx, `
		UPDATE strategy_template SET name=$2, description=$3, severity=$4, conditions=$5,
		cooldown_days=$6, is_enabled=$7, updated_at=NOW() WHERE id=$1`,
		s.ID, s.Name, s.Description, string(s.Severity), condBytes,
		s.CooldownDays, s.IsEnabled,
	)
	if err != nil {
		return fmt.Errorf("StrategyRepo.Update: %w", err)
	}
	return nil
}

func (r *StrategyRepo) Delete(ctx context.Context, id int64) error {
	_, err := r.pool.Exec(ctx, `DELETE FROM strategy_template WHERE id = $1`, id)
	if err != nil {
		return fmt.Errorf("StrategyRepo.Delete: %w", err)
	}
	return nil
}

func (r *StrategyRepo) GetBindingsForFund(ctx context.Context, fundCode shared.FundCode) ([]*strategy.StrategyBinding, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT id, strategy_id, fund_code, is_enabled, created_at FROM strategy_binding WHERE fund_code = $1 AND is_enabled = TRUE`,
		string(fundCode),
	)
	if err != nil {
		return nil, fmt.Errorf("StrategyRepo.GetBindingsForFund: %w", err)
	}
	return collectBindings(rows)
}

func (r *StrategyRepo) GetBindingsForStrategy(ctx context.Context, strategyID int64) ([]*strategy.StrategyBinding, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT id, strategy_id, fund_code, is_enabled, created_at FROM strategy_binding WHERE strategy_id = $1`,
		strategyID,
	)
	if err != nil {
		return nil, fmt.Errorf("StrategyRepo.GetBindingsForStrategy: %w", err)
	}
	return collectBindings(rows)
}

func collectBindings(rows pgx.Rows) ([]*strategy.StrategyBinding, error) {
	defer rows.Close()
	var list []*strategy.StrategyBinding
	for rows.Next() {
		var b strategy.StrategyBinding
		if err := rows.Scan(&b.ID, &b.StrategyID, &b.FundCode, &b.IsEnabled, &b.CreatedAt); err != nil {
			return nil, err
		}
		list = append(list, &b)
	}
	return list, rows.Err()
}

func (r *StrategyRepo) SaveBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO strategy_binding (strategy_id, fund_code, is_enabled)
		VALUES ($1,$2,$3)
		ON CONFLICT (strategy_id, fund_code) DO UPDATE SET is_enabled = EXCLUDED.is_enabled`,
		strategyID, string(fundCode), true,
	)
	if err != nil {
		return fmt.Errorf("StrategyRepo.SaveBinding: %w", err)
	}
	return nil
}

func (r *StrategyRepo) DeleteBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) error {
	_, err := r.pool.Exec(ctx,
		`DELETE FROM strategy_binding WHERE strategy_id = $1 AND fund_code = $2`,
		strategyID, string(fundCode),
	)
	if err != nil {
		return fmt.Errorf("StrategyRepo.DeleteBinding: %w", err)
	}
	return nil
}

var _ strategy.StrategyTemplateRepository = (*StrategyRepo)(nil)
var _ strategy.StrategyBindingRepository = (*StrategyRepo)(nil)

// --- Helper: time for conditions column ---

func init() {
	_ = time.Now // ensure time is used if needed
}
