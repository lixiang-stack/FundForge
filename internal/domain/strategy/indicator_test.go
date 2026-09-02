package strategy

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

const tolerance = 1e-4

// makeBars creates PricePoints from a price sequence with dates starting from 2024-01-01.
func makeBars(prices []float64) []PricePoint {
	bars := make([]PricePoint, len(prices))
	start := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	for i, p := range prices {
		bars[i] = PricePoint{
			Date:  start.AddDate(0, 0, i),
			Close: p,
		}
	}
	return bars
}

func TestMaxDrawdown(t *testing.T) {
	tests := []struct {
		name   string
		prices []float64
		want   float64
	}{
		{
			name:   "normal sequence",
			prices: []float64{100, 110, 105, 95, 100},
			want:   (110.0 - 95.0) / 110.0, // ~0.1364
		},
		{
			name:   "all up (0)",
			prices: []float64{100, 110, 120, 130},
			want:   0,
		},
		{
			name:   "all down",
			prices: []float64{100, 80, 60, 40},
			want:   (100.0 - 40.0) / 100.0, // 0.60
		},
		{
			name:   "single bar (0)",
			prices: []float64{100},
			want:   0,
		},
		{
			name:   "empty (0)",
			prices: []float64{},
			want:   0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := MaxDrawdown(makeBars(tt.prices))
			assert.InDelta(t, tt.want, got, tolerance)
		})
	}
}

func TestRollingReturn(t *testing.T) {
	tests := []struct {
		name   string
		prices []float64
		days   int
		want   float64
	}{
		{
			name:   "normal 3-day return",
			prices: []float64{100, 105, 110, 120},
			days:   3,
			want:   (120.0 - 100.0) / 100.0, // 0.20
		},
		{
			name:   "insufficient data (0)",
			prices: []float64{100, 110},
			days:   5,
			want:   0,
		},
		{
			name:   "1-day return",
			prices: []float64{100, 108},
			days:   1,
			want:   0.08,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := RollingReturn(makeBars(tt.prices), tt.days)
			assert.InDelta(t, tt.want, got, tolerance)
		})
	}
}

func TestAnnualizedVolatility(t *testing.T) {
	tests := []struct {
		name   string
		prices []float64
	}{
		{
			name:   "normal sequence returns positive",
			prices: []float64{100, 102, 98, 103, 99, 101},
		},
		{
			name:   "single bar returns 0",
			prices: []float64{100},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := AnnualizedVolatility(makeBars(tt.prices))
			if len(tt.prices) < 2 {
				assert.InDelta(t, 0.0, got, tolerance)
			} else {
				assert.Greater(t, got, 0.0)
			}
		})
	}
}

func TestDownsideVolatility(t *testing.T) {
	tests := []struct {
		name   string
		prices []float64
		isZero bool
	}{
		{
			name:   "all positive returns (0)",
			prices: []float64{100, 110, 120, 130, 140},
			isZero: true,
		},
		{
			name:   "mixed returns positive downside vol",
			prices: []float64{100, 95, 105, 90, 100},
			isZero: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := DownsideVolatility(makeBars(tt.prices))
			if tt.isZero {
				assert.InDelta(t, 0.0, got, tolerance)
			} else {
				assert.Greater(t, got, 0.0)
			}
		})
	}
}

func TestSharpeRatio(t *testing.T) {
	tests := []struct {
		name         string
		prices       []float64
		riskFreeRate float64
		wantPositive bool
		wantZero     bool
	}{
		{
			name:         "positive sharpe with upward trend",
			prices:       []float64{100, 102, 104, 106, 108, 110},
			riskFreeRate: 0.02,
			wantPositive: true,
		},
		{
			name:         "zero volatility constant prices",
			prices:       []float64{100, 100, 100, 100},
			riskFreeRate: 0.02,
			wantZero:     true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := SharpeRatio(makeBars(tt.prices), tt.riskFreeRate)
			if tt.wantZero {
				assert.InDelta(t, 0.0, got, tolerance)
			} else if tt.wantPositive {
				assert.Greater(t, got, 0.0)
			}
		})
	}
}

func TestComputeSnapshot(t *testing.T) {
	tests := []struct {
		name        string
		fundPrices  []float64
		benchPrices []float64
	}{
		{
			name:        "verify all expected keys present",
			fundPrices:  []float64{100, 102, 98, 103, 99, 101, 105, 97, 110, 108},
			benchPrices: []float64{1000, 1010, 1005, 1020, 1015, 1025, 1030, 1010, 1050, 1040},
		},
		{
			name:        "no panic with short data",
			fundPrices:  []float64{100, 102},
			benchPrices: []float64{1000, 1010},
		},
	}

	expectedKeys := []string{
		"max_drawdown", "max_drawdown_1y",
		"annualized_volatility", "annual_volatility", "downside_volatility",
		"sharpe_ratio", "annual_sharpe",
		"beta", "excess_return",
		"rolling_return_5d", "rolling_return_20d", "rolling_return_60d",
		"rolling_return_120d", "rolling_return_250d",
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			fundBars := makeBars(tt.fundPrices)
			benchBars := makeBars(tt.benchPrices)

			require.NotPanics(t, func() {
				snap := ComputeSnapshot(fundBars, benchBars, 0.02)
				for _, key := range expectedKeys {
					_, ok := snap[key]
					assert.True(t, ok, "missing key: %s", key)
				}
			})
		})
	}
}
