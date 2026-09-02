package alert

import (
	"context"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// AlertRepository defines persistence operations for alert entities.
type AlertRepository interface {
	GetByID(ctx context.Context, id int64) (*Alert, error)
	ListByFund(ctx context.Context, fundCode shared.FundCode, statuses []Status) ([]*Alert, error)
	ListActive(ctx context.Context) ([]*Alert, error)
	ListRecent(ctx context.Context, since time.Time) ([]*Alert, error)
	Save(ctx context.Context, a *Alert) error
	UpdateStatus(ctx context.Context, a *Alert) error
	HasRecentAlert(ctx context.Context, strategyID int64, fundCode shared.FundCode, since time.Time) (bool, error)
}
