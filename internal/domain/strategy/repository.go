package strategy

import (
	"context"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// StrategyTemplateRepository persists StrategyTemplate aggregates.
// One Repository per Aggregate Root: this interface owns the persistence
// surface for the StrategyTemplate aggregate only.
type StrategyTemplateRepository interface {
	GetByID(ctx context.Context, id int64) (*StrategyTemplate, error)
	ListEnabled(ctx context.Context) ([]*StrategyTemplate, error)
	ListAll(ctx context.Context) ([]*StrategyTemplate, error)
	Save(ctx context.Context, s *StrategyTemplate) error
	Update(ctx context.Context, s *StrategyTemplate) error
	Delete(ctx context.Context, id int64) error
}

// StrategyBindingRepository persists StrategyBinding aggregates.
// A binding is its own aggregate (independent enable/disable lifecycle); it
// references StrategyTemplate by ID and Fund by Code, never by direct object.
type StrategyBindingRepository interface {
	GetBindingsForFund(ctx context.Context, fundCode shared.FundCode) ([]*StrategyBinding, error)
	GetBindingsForStrategy(ctx context.Context, strategyID int64) ([]*StrategyBinding, error)
	SaveBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) error
	DeleteBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) error
}
