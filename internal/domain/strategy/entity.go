package strategy

import (
	"errors"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// Sentinel errors for strategy operations.
var (
	ErrStrategyNotFound = errors.New("strategy not found")
)

// --- Severity ---

// Severity indicates how critical a strategy alert is.
type Severity string

const (
	Info     Severity = "info"
	Warning  Severity = "warning"
	Critical Severity = "critical"
)

// Validate returns an error if s is not a known Severity value.
func (s Severity) Validate() error {
	switch s {
	case Info, Warning, Critical:
		return nil
	default:
		return fmt.Errorf("invalid severity: %q", string(s))
	}
}

// --- LogicOp ---

// LogicOp defines how multiple conditions are combined.
type LogicOp string

const (
	AND LogicOp = "AND"
	OR  LogicOp = "OR"
)

// Validate returns an error if op is not AND or OR.
func (op LogicOp) Validate() error {
	switch op {
	case AND, OR:
		return nil
	default:
		return fmt.Errorf("invalid logic op: %q", string(op))
	}
}

// --- Operator ---

// Operator is a comparison operator used in strategy conditions.
type Operator string

const (
	GTE Operator = ">="
	LTE Operator = "<="
	GT  Operator = ">"
	LT  Operator = "<"
	EQ  Operator = "=="
	NEQ Operator = "!="
)

// Validate returns an error if op is not a known comparison operator.
func (op Operator) Validate() error {
	switch op {
	case GTE, LTE, GT, LT, EQ, NEQ:
		return nil
	default:
		return fmt.Errorf("invalid operator: %q", string(op))
	}
}

// --- Condition ---

// Condition represents a single indicator threshold check.
type Condition struct {
	Indicator string
	Operator  Operator
	Threshold float64
}

// --- StrategyTemplate ---

// StrategyTemplate defines a reusable alert strategy with one or more
// conditions combined by a logic operator.
type StrategyTemplate struct {
	ID           int64
	Name         string
	Description  string
	Severity     Severity
	Logic        LogicOp
	Conditions   []Condition
	CooldownDays int
	IsEnabled    bool
	IsPreset     bool
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// Evaluate checks all conditions in this template against the snapshot and
// returns whether the strategy was triggered, along with a human-readable
// detail string.
//
// For AND logic all conditions must match; for OR logic any single match
// is sufficient.
func (s *StrategyTemplate) Evaluate(snapshot IndicatorSnapshot) (triggered bool, detail string) {
	switch s.Logic {
	case AND:
		for _, c := range s.Conditions {
			if !c.Matches(snapshot) {
				return false, ""
			}
		}
		return true, fmt.Sprintf("all %d conditions met (AND)", len(s.Conditions))
	case OR:
		for _, c := range s.Conditions {
			if c.Matches(snapshot) {
				return true, fmt.Sprintf("condition met: %s %s %.4f (OR)", c.Indicator, string(c.Operator), c.Threshold)
			}
		}
		return false, ""
	default:
		return false, ""
	}
}

// Matches returns true if the snapshot value satisfies this Condition.
// Returns false if the indicator is not present in the snapshot.
func (c Condition) Matches(snapshot IndicatorSnapshot) bool {
	value, ok := snapshot[c.Indicator]
	if !ok {
		return false
	}
	switch c.Operator {
	case GT:
		return value > c.Threshold
	case GTE:
		return value >= c.Threshold
	case LT:
		return value < c.Threshold
	case LTE:
		return value <= c.Threshold
	case EQ:
		return value == c.Threshold
	case NEQ:
		return value != c.Threshold
	default:
		return false
	}
}

// --- StrategyBinding ---

// StrategyBinding links a StrategyTemplate to a specific fund.
type StrategyBinding struct {
	ID         int64
	StrategyID int64
	FundCode   shared.FundCode
	IsEnabled  bool
	CreatedAt  time.Time
}

// --- IndicatorSnapshot ---

// IndicatorSnapshot captures the computed indicator values at a point in time.
type IndicatorSnapshot = map[string]float64
