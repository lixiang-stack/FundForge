package alert

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// Service implements alert domain logic.
type Service struct {
	repo AlertRepository
}

// NewService creates a new alert domain service.
func NewService(repo AlertRepository) *Service {
	return &Service{repo: repo}
}

// TryTrigger creates a new alert if no recent alert exists for the same
// strategy+fund combination within the cooldown period. Returns nil (without
// error) when the cooldown is still active.
func (s *Service) TryTrigger(
	ctx context.Context,
	fundCode shared.FundCode,
	strategyID int64,
	severity string,
	dataDate time.Time,
	indicators map[string]float64,
	conditions json.RawMessage,
	cooldownDays int,
	message string,
) (*Alert, error) {
	since := time.Now().AddDate(0, 0, -cooldownDays)
	recent, err := s.repo.HasRecentAlert(ctx, strategyID, fundCode, since)
	if err != nil {
		return nil, fmt.Errorf("check recent alert: %w", err)
	}
	if recent {
		return nil, nil
	}

	now := time.Now()
	a := &Alert{
		FundCode:          fundCode,
		StrategyID:        strategyID,
		Status:            Triggered,
		Severity:          severity,
		DataDate:          dataDate,
		TriggeredAt:       now,
		IndicatorSnapshot: indicators,
		ConditionSnapshot: conditions,
		Message:           message,
		CreatedAt:         now,
		UpdatedAt:         now,
	}
	if err := s.repo.Save(ctx, a); err != nil {
		return nil, fmt.Errorf("save alert: %w", err)
	}
	return a, nil
}

// RecoverIfActive finds all active (triggered or confirmed) alerts for the
// given strategy+fund combination, transitions them to recovered, and
// persists the status change.
func (s *Service) RecoverIfActive(ctx context.Context, strategyID int64, fundCode shared.FundCode) ([]*Alert, error) {
	active, err := s.repo.ListByFund(ctx, fundCode, []Status{Triggered, Confirmed})
	if err != nil {
		return nil, fmt.Errorf("list active alerts: %w", err)
	}

	var recovered []*Alert
	for _, a := range active {
		if a.StrategyID != strategyID {
			continue
		}
		if err := a.Recover(); err != nil {
			continue
		}
		if err := s.repo.UpdateStatus(ctx, a); err != nil {
			return nil, fmt.Errorf("update alert status: %w", err)
		}
		recovered = append(recovered, a)
	}
	return recovered, nil
}
