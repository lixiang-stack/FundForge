package strategy

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestStrategyTemplate_Evaluate_AND(t *testing.T) {
	tests := []struct {
		name        string
		strategy    *StrategyTemplate
		snapshot    IndicatorSnapshot
		wantTrigger bool
	}{
		{
			name: "all match triggers",
			strategy: &StrategyTemplate{
				Logic: AND,
				Conditions: []Condition{
					{Indicator: "max_drawdown", Operator: LTE, Threshold: -10},
					{Indicator: "annualized_volatility", Operator: GTE, Threshold: 20},
				},
			},
			snapshot: IndicatorSnapshot{
				"max_drawdown":          -15,
				"annualized_volatility": 25,
			},
			wantTrigger: true,
		},
		{
			name: "partial match does not trigger",
			strategy: &StrategyTemplate{
				Logic: AND,
				Conditions: []Condition{
					{Indicator: "max_drawdown", Operator: LTE, Threshold: -10},
					{Indicator: "annualized_volatility", Operator: GTE, Threshold: 30},
				},
			},
			snapshot: IndicatorSnapshot{
				"max_drawdown":          -15,
				"annualized_volatility": 25,
			},
			wantTrigger: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			triggered, _ := tt.strategy.Evaluate(tt.snapshot)
			assert.Equal(t, tt.wantTrigger, triggered)
		})
	}
}

func TestStrategyTemplate_Evaluate_OR(t *testing.T) {
	tests := []struct {
		name        string
		strategy    *StrategyTemplate
		snapshot    IndicatorSnapshot
		wantTrigger bool
	}{
		{
			name: "any match triggers",
			strategy: &StrategyTemplate{
				Logic: OR,
				Conditions: []Condition{
					{Indicator: "max_drawdown", Operator: LTE, Threshold: -10},
					{Indicator: "annualized_volatility", Operator: GTE, Threshold: 30},
				},
			},
			snapshot: IndicatorSnapshot{
				"max_drawdown":          -5,
				"annualized_volatility": 35,
			},
			wantTrigger: true,
		},
		{
			name: "none match does not trigger",
			strategy: &StrategyTemplate{
				Logic: OR,
				Conditions: []Condition{
					{Indicator: "max_drawdown", Operator: LTE, Threshold: -10},
					{Indicator: "annualized_volatility", Operator: GTE, Threshold: 30},
				},
			},
			snapshot: IndicatorSnapshot{
				"max_drawdown":          -5,
				"annualized_volatility": 20,
			},
			wantTrigger: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			triggered, _ := tt.strategy.Evaluate(tt.snapshot)
			assert.Equal(t, tt.wantTrigger, triggered)
		})
	}
}

func TestCondition_Matches(t *testing.T) {
	tests := []struct {
		name      string
		condition Condition
		snapshot  IndicatorSnapshot
		want      bool
	}{
		{
			name:      "GTE true when equal",
			condition: Condition{Indicator: "vol", Operator: GTE, Threshold: 10},
			snapshot:  IndicatorSnapshot{"vol": 10},
			want:      true,
		},
		{
			name:      "GTE true when greater",
			condition: Condition{Indicator: "vol", Operator: GTE, Threshold: 10},
			snapshot:  IndicatorSnapshot{"vol": 15},
			want:      true,
		},
		{
			name:      "GTE false when less",
			condition: Condition{Indicator: "vol", Operator: GTE, Threshold: 10},
			snapshot:  IndicatorSnapshot{"vol": 5},
			want:      false,
		},
		{
			name:      "LTE true when equal",
			condition: Condition{Indicator: "dd", Operator: LTE, Threshold: -10},
			snapshot:  IndicatorSnapshot{"dd": -10},
			want:      true,
		},
		{
			name:      "LTE true when less",
			condition: Condition{Indicator: "dd", Operator: LTE, Threshold: -10},
			snapshot:  IndicatorSnapshot{"dd": -20},
			want:      true,
		},
		{
			name:      "LTE false when greater",
			condition: Condition{Indicator: "dd", Operator: LTE, Threshold: -10},
			snapshot:  IndicatorSnapshot{"dd": -5},
			want:      false,
		},
		{
			name:      "GT true",
			condition: Condition{Indicator: "x", Operator: GT, Threshold: 5},
			snapshot:  IndicatorSnapshot{"x": 6},
			want:      true,
		},
		{
			name:      "GT false when equal",
			condition: Condition{Indicator: "x", Operator: GT, Threshold: 5},
			snapshot:  IndicatorSnapshot{"x": 5},
			want:      false,
		},
		{
			name:      "LT true",
			condition: Condition{Indicator: "x", Operator: LT, Threshold: 5},
			snapshot:  IndicatorSnapshot{"x": 4},
			want:      true,
		},
		{
			name:      "LT false when equal",
			condition: Condition{Indicator: "x", Operator: LT, Threshold: 5},
			snapshot:  IndicatorSnapshot{"x": 5},
			want:      false,
		},
		{
			name:      "EQ true",
			condition: Condition{Indicator: "x", Operator: EQ, Threshold: 42},
			snapshot:  IndicatorSnapshot{"x": 42},
			want:      true,
		},
		{
			name:      "EQ false",
			condition: Condition{Indicator: "x", Operator: EQ, Threshold: 42},
			snapshot:  IndicatorSnapshot{"x": 43},
			want:      false,
		},
		{
			name:      "NEQ true",
			condition: Condition{Indicator: "x", Operator: NEQ, Threshold: 42},
			snapshot:  IndicatorSnapshot{"x": 43},
			want:      true,
		},
		{
			name:      "NEQ false",
			condition: Condition{Indicator: "x", Operator: NEQ, Threshold: 42},
			snapshot:  IndicatorSnapshot{"x": 42},
			want:      false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.condition.Matches(tt.snapshot)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestCondition_Matches_MissingIndicator(t *testing.T) {
	tests := []struct {
		name      string
		condition Condition
		snapshot  IndicatorSnapshot
	}{
		{
			name:      "indicator not in snapshot",
			condition: Condition{Indicator: "missing", Operator: GTE, Threshold: 10},
			snapshot:  IndicatorSnapshot{"other": 20},
		},
		{
			name:      "empty snapshot",
			condition: Condition{Indicator: "vol", Operator: GTE, Threshold: 10},
			snapshot:  IndicatorSnapshot{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.condition.Matches(tt.snapshot)
			assert.False(t, got)
		})
	}
}
