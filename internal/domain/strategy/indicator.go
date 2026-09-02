package strategy

import (
	"fmt"
	"math"
)

// dailyReturns computes the simple daily return series from a slice of
// PricePoints. The returned slice has length len(bars)-1.
func dailyReturns(bars []PricePoint) []float64 {
	if len(bars) < 2 {
		return nil
	}
	rets := make([]float64, len(bars)-1)
	for i := 1; i < len(bars); i++ {
		if bars[i-1].Close == 0 {
			rets[i-1] = 0
			continue
		}
		rets[i-1] = (bars[i].Close - bars[i-1].Close) / bars[i-1].Close
	}
	return rets
}

// MaxDrawdown computes the maximum peak-to-trough drawdown over the bar
// series, expressed as a positive fraction (e.g. 0.15 = 15 %).
func MaxDrawdown(bars []PricePoint) float64 {
	if len(bars) < 2 {
		return 0
	}
	peak := bars[0].Close
	maxDD := 0.0
	for _, b := range bars[1:] {
		if b.Close > peak {
			peak = b.Close
		}
		if peak > 0 {
			dd := (peak - b.Close) / peak
			if dd > maxDD {
				maxDD = dd
			}
		}
	}
	return maxDD
}

// RollingReturn computes the simple return over the last N bars.
func RollingReturn(bars []PricePoint, days int) float64 {
	if len(bars) < days+1 || days <= 0 {
		return 0
	}
	start := bars[len(bars)-1-days].Close
	end := bars[len(bars)-1].Close
	if start == 0 {
		return 0
	}
	return (end - start) / start
}

// AnnualizedVolatility computes the annualized standard deviation of daily
// returns (daily std × √250).
func AnnualizedVolatility(bars []PricePoint) float64 {
	rets := dailyReturns(bars)
	if len(rets) == 0 {
		return 0
	}
	return sampleStdDev(rets) * math.Sqrt(250)
}

// DownsideVolatility is identical to AnnualizedVolatility but considers only
// negative daily returns.
func DownsideVolatility(bars []PricePoint) float64 {
	rets := dailyReturns(bars)
	if len(rets) == 0 {
		return 0
	}
	var neg []float64
	for _, r := range rets {
		if r < 0 {
			neg = append(neg, r)
		}
	}
	if len(neg) == 0 {
		return 0
	}
	return sampleStdDev(neg) * math.Sqrt(250)
}

// SharpeRatio computes the annualized Sharpe ratio:
//
//	(mean daily return − daily risk-free rate) / daily std × √250
func SharpeRatio(bars []PricePoint, riskFreeRate float64) float64 {
	rets := dailyReturns(bars)
	if len(rets) == 0 {
		return 0
	}
	m := sliceMean(rets)
	sd := sampleStdDev(rets)
	if sd == 0 {
		return 0
	}
	dailyRf := riskFreeRate / 250
	return (m - dailyRf) / sd * math.Sqrt(250)
}

// Beta computes the CAPM beta of fundBars relative to benchBars.
//
//	β = Cov(fund, bench) / Var(bench)
func Beta(fundBars, benchBars []PricePoint) float64 {
	fundRets := dailyReturns(fundBars)
	benchRets := dailyReturns(benchBars)
	n := min(len(fundRets), len(benchRets))
	if n == 0 {
		return 0
	}
	// Align from the tail so the most recent dates match.
	fundRets = fundRets[len(fundRets)-n:]
	benchRets = benchRets[len(benchRets)-n:]

	fundMean := sliceMean(fundRets)
	benchMean := sliceMean(benchRets)

	var cov, variance float64
	for i := range n {
		fd := fundRets[i] - fundMean
		bd := benchRets[i] - benchMean
		cov += fd * bd
		variance += bd * bd
	}
	if variance == 0 {
		return 0
	}
	return cov / variance
}

// ExcessReturn computes the total return of the fund minus the total return
// of the benchmark over the entire bar series.
func ExcessReturn(fundBars, benchBars []PricePoint) float64 {
	if len(fundBars) < 2 || len(benchBars) < 2 {
		return 0
	}
	fundReturn := (fundBars[len(fundBars)-1].Close - fundBars[0].Close) / fundBars[0].Close
	benchReturn := (benchBars[len(benchBars)-1].Close - benchBars[0].Close) / benchBars[0].Close
	return fundReturn - benchReturn
}

// ComputeSnapshot calculates all supported indicators and returns them as
// an IndicatorSnapshot keyed by indicator name.
func ComputeSnapshot(fundBars, benchBars []PricePoint, riskFreeRate float64) IndicatorSnapshot {
	snap := make(IndicatorSnapshot)

	// Max drawdown (stored as negative percentage for threshold comparison, e.g. -20.0 for 20% drawdown)
	mdd := MaxDrawdown(fundBars)
	snap["max_drawdown"] = -mdd * 100

	// Max drawdown for recent 1 year (~250 trading days)
	if len(fundBars) > 250 {
		mdd1y := MaxDrawdown(fundBars[len(fundBars)-250:])
		snap["max_drawdown_1y"] = -mdd1y * 100
	} else {
		snap["max_drawdown_1y"] = -mdd * 100
	}

	// Volatility (as percentage)
	av := AnnualizedVolatility(fundBars)
	snap["annualized_volatility"] = av * 100
	snap["annual_volatility"] = av * 100 // alias used by some preset strategies
	snap["downside_volatility"] = DownsideVolatility(fundBars) * 100

	// Risk-adjusted
	snap["sharpe_ratio"] = SharpeRatio(fundBars, riskFreeRate)
	snap["annual_sharpe"] = snap["sharpe_ratio"] // alias

	// Beta and excess return
	snap["beta"] = Beta(fundBars, benchBars)
	snap["excess_return"] = ExcessReturn(fundBars, benchBars) * 100

	// Rolling returns (as percentage)
	for _, days := range []int{5, 20, 60, 120, 250} {
		key := fmt.Sprintf("rolling_return_%dd", days)
		snap[key] = RollingReturn(fundBars, days) * 100
	}

	return snap
}

// ---------------------------------------------------------------------------
// internal math helpers
// ---------------------------------------------------------------------------

func sliceMean(data []float64) float64 {
	if len(data) == 0 {
		return 0
	}
	sum := 0.0
	for _, v := range data {
		sum += v
	}
	return sum / float64(len(data))
}

func sampleStdDev(data []float64) float64 {
	if len(data) < 2 {
		return 0
	}
	m := sliceMean(data)
	sumSq := 0.0
	for _, v := range data {
		d := v - m
		sumSq += d * d
	}
	return math.Sqrt(sumSq / float64(len(data)-1))
}
