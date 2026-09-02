package application

import (
	"context"

	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"go.uber.org/zap"
)

// AlertUseCase handles alert management operations.
type AlertUseCase struct {
	alertRepo alert.AlertRepository
	logger    *zap.SugaredLogger
}

func NewAlertUseCase(alertRepo alert.AlertRepository, logger *zap.SugaredLogger) *AlertUseCase {
	return &AlertUseCase{alertRepo: alertRepo, logger: logger}
}

// ListActive returns all triggered or confirmed alerts.
func (uc *AlertUseCase) ListActive(ctx context.Context) ([]*alert.Alert, error) {
	alerts, err := uc.alertRepo.ListActive(ctx)
	if err != nil {
		return nil, err
	}
	// Sort by severity
	sortAlertsBySeverity(alerts)
	return alerts, nil
}

// ListByFund returns alerts for a specific fund.
func (uc *AlertUseCase) ListByFund(ctx context.Context, fundCode shared.FundCode) ([]*alert.Alert, error) {
	return uc.alertRepo.ListByFund(ctx, fundCode, []alert.Status{alert.Triggered, alert.Confirmed})
}

// ConfirmAlert marks an alert as confirmed by the user.
func (uc *AlertUseCase) ConfirmAlert(ctx context.Context, alertID int64) error {
	a, err := uc.alertRepo.GetByID(ctx, alertID)
	if err != nil {
		return err
	}
	if a == nil {
		return alert.ErrInvalidTransition
	}
	if err := a.Confirm(); err != nil {
		return err
	}
	if err := uc.alertRepo.UpdateStatus(ctx, a); err != nil {
		return err
	}
	uc.logger.Infow("alert confirmed", "id", alertID, "fund", a.FundCode)
	return nil
}

// IgnoreAlert marks an alert as ignored by the user.
func (uc *AlertUseCase) IgnoreAlert(ctx context.Context, alertID int64) error {
	a, err := uc.alertRepo.GetByID(ctx, alertID)
	if err != nil {
		return err
	}
	if a == nil {
		return alert.ErrInvalidTransition
	}
	if err := a.Ignore(); err != nil {
		return err
	}
	if err := uc.alertRepo.UpdateStatus(ctx, a); err != nil {
		return err
	}
	uc.logger.Infow("alert ignored", "id", alertID, "fund", a.FundCode)
	return nil
}

func (uc *AlertUseCase) GetByID(ctx context.Context, alertID int64) (*alert.Alert, error) {
	return uc.alertRepo.GetByID(ctx, alertID)
}

func sortAlertsBySeverity(alerts []*alert.Alert) {
	order := func(s string) int {
		switch s {
		case "critical":
			return 0
		case "warning":
			return 1
		default:
			return 2
		}
	}
	for i := 0; i < len(alerts)-1; i++ {
		for j := i + 1; j < len(alerts); j++ {
			if order(alerts[j].Severity) < order(alerts[i].Severity) {
				alerts[i], alerts[j] = alerts[j], alerts[i]
			}
		}
	}
}
