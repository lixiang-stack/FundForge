package alert

import (
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// --- Status ---

// Status represents the lifecycle state of an alert.
type Status string

const (
	Triggered Status = "triggered"
	Confirmed Status = "confirmed"
	Ignored   Status = "ignored"
	Recovered Status = "recovered"
)

// ErrInvalidTransition is returned when an invalid status transition is attempted.
var ErrInvalidTransition = errors.New("invalid alert status transition")

// validTransitions defines the allowed status transitions.
var validTransitions = map[Status][]Status{
	Triggered: {Confirmed, Ignored, Recovered},
	Confirmed: {Recovered},
	// Ignored and Recovered are terminal states.
}

// Validate returns an error if s is not a known Status value.
func (s Status) Validate() error {
	switch s {
	case Triggered, Confirmed, Ignored, Recovered:
		return nil
	default:
		return fmt.Errorf("invalid alert status: %q", string(s))
	}
}

// --- Alert entity ---

// Alert represents a triggered strategy alert for a fund.
type Alert struct {
	ID                int64
	FundCode          shared.FundCode
	StrategyID        int64
	Status            Status
	Severity          string
	DataDate          time.Time
	TriggeredAt       time.Time
	RecoveredAt       *time.Time
	ConfirmedAt       *time.Time
	IndicatorSnapshot map[string]float64
	ConditionSnapshot json.RawMessage
	Message           string
	CreatedAt         time.Time
	UpdatedAt         time.Time
}

// CanTransitionTo returns true if the alert can move from its current
// status to the given target status.
func (a *Alert) CanTransitionTo(target Status) bool {
	allowed, ok := validTransitions[a.Status]
	if !ok {
		return false
	}
	return slices.Contains(allowed, target)
}

// transition is the internal helper that validates and applies a status change.
func (a *Alert) transition(target Status) error {
	if !a.CanTransitionTo(target) {
		return fmt.Errorf("%w: %s -> %s", ErrInvalidTransition, a.Status, target)
	}
	a.Status = target
	a.UpdatedAt = time.Now()
	return nil
}

// Confirm moves the alert from triggered to confirmed.
func (a *Alert) Confirm() error {
	if err := a.transition(Confirmed); err != nil {
		return err
	}
	now := time.Now()
	a.ConfirmedAt = &now
	return nil
}

// Ignore moves the alert from triggered to ignored.
func (a *Alert) Ignore() error {
	return a.transition(Ignored)
}

// Recover moves the alert from triggered or confirmed to recovered.
func (a *Alert) Recover() error {
	if err := a.transition(Recovered); err != nil {
		return err
	}
	now := time.Now()
	a.RecoveredAt = &now
	return nil
}
