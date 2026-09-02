// Package nav owns the fund Net Asset Value aggregate.
//
// Aggregate root: NAV (one per fund per day for regular funds; MoneyFundNAV
// for money-market funds — separate aggregate, separate table, different
// shape — Yield vs UnitNAV).
//
// Identity is composite: (FundCode, Date). The surrogate ID exists only
// for storage joins; domain logic uses the composite key.
package nav

import (
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// NAV represents a fund's net asset value on a specific date.
type NAV struct {
	ID          int64
	FundCode    shared.FundCode
	Date        time.Time
	UnitNAV     float64
	AccNAV      float64
	DailyReturn float64
	FetchedAt   time.Time
}

// MoneyFundNAV represents a money-market fund's daily yield data.
// This is a SEPARATE aggregate from NAV: different fields (SevenDayYield
// vs UnitNAV), different table, different lifecycle.
type MoneyFundNAV struct {
	ID                   int64
	FundCode             shared.FundCode
	Date                 time.Time
	IncomePerTenThousand float64
	SevenDayYield        float64
	FetchedAt            time.Time
}

// PriceBar is the price representation used by indicator/strategy
// computations. Currently only Close is needed (NAVs only carry close
// prices). If a future data source provides OHLV, this type can be
// extended — for now we keep it minimal to avoid carrying optional
// fields that no caller populates.
type PriceBar struct {
	Date  time.Time
	Close float64
}

// NAVToPriceBar converts a single NAV record into a PriceBar.
func NAVToPriceBar(nav NAV) PriceBar {
	return PriceBar{
		Date:  nav.Date,
		Close: nav.UnitNAV,
	}
}

// NAVsToPriceBars converts a slice of NAV records into PriceBars.
func NAVsToPriceBars(navs []NAV) []PriceBar {
	bars := make([]PriceBar, len(navs))
	for i, nav := range navs {
		bars[i] = NAVToPriceBar(nav)
	}
	return bars
}
