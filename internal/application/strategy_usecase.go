package application

import (
	"context"
	"fmt"

	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
)

type StrategyUseCase struct {
	fundRepo     fund.FundRepository
	templateRepo strategy.StrategyTemplateRepository
	bindingRepo  strategy.StrategyBindingRepository
}

func NewStrategyUseCase(
	fr fund.FundRepository,
	tr strategy.StrategyTemplateRepository,
	br strategy.StrategyBindingRepository,
) *StrategyUseCase {
	return &StrategyUseCase{
		fundRepo:     fr,
		templateRepo: tr,
		bindingRepo:  br,
	}
}

func (uc *StrategyUseCase) GetByID(ctx context.Context, id int64) (*strategy.StrategyTemplate, error) {
	return uc.templateRepo.GetByID(ctx, id)
}

func (uc *StrategyUseCase) ListEnabled(ctx context.Context) ([]*strategy.StrategyTemplate, error) {
	return uc.templateRepo.ListEnabled(ctx)
}

func (uc *StrategyUseCase) ListAll(ctx context.Context) ([]*strategy.StrategyTemplate, error) {
	return uc.templateRepo.ListAll(ctx)
}

func (uc *StrategyUseCase) Save(ctx context.Context, s *strategy.StrategyTemplate) error {
	return uc.templateRepo.Save(ctx, s)
}

func (uc *StrategyUseCase) Update(ctx context.Context, s *strategy.StrategyTemplate) error {
	return uc.templateRepo.Update(ctx, s)
}

func (uc *StrategyUseCase) Delete(ctx context.Context, id int64) error {
	return uc.templateRepo.Delete(ctx, id)
}

func (uc *StrategyUseCase) GetBindingsForFund(ctx context.Context, fundCode shared.FundCode) ([]*strategy.StrategyBinding, error) {
	return uc.bindingRepo.GetBindingsForFund(ctx, fundCode)
}

func (uc *StrategyUseCase) GetBindingsForStrategy(ctx context.Context, strategyID int64) ([]*strategy.StrategyBinding, error) {
	return uc.bindingRepo.GetBindingsForStrategy(ctx, strategyID)
}

// SaveBinding validates that the strategy and fund exist, then persists the binding.
// Returns the matched StrategyTemplate for caller to use (e.g. display strategy name).
func (uc *StrategyUseCase) SaveBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) (*strategy.StrategyTemplate, error) {
	st, err := uc.templateRepo.GetByID(ctx, strategyID)
	if err != nil {
		return nil, fmt.Errorf("SaveBinding: %w", err)
	}
	if st == nil {
		return nil, strategy.ErrStrategyNotFound
	}

	f, err := uc.fundRepo.GetByCode(ctx, fundCode)
	if err != nil {
		return nil, fmt.Errorf("SaveBinding: %w", err)
	}
	if f == nil {
		return nil, fund.ErrFundNotFound
	}

	if err := uc.bindingRepo.SaveBinding(ctx, strategyID, fundCode); err != nil {
		return nil, fmt.Errorf("SaveBinding: %w", err)
	}
	return st, nil
}

func (uc *StrategyUseCase) DeleteBinding(ctx context.Context, strategyID int64, fundCode shared.FundCode) error {
	return uc.bindingRepo.DeleteBinding(ctx, strategyID, fundCode)
}
