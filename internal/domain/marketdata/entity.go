// the marketdata interface ports (FundProvider, TradeCalendarProvider,
// CorporateActionProvider) and the raw DTOs that providers return.
//
// Real domain aggregates that consume this data live in their own modules:
//   - nav:       NAV / MoneyFundNAV (price-and-yield time-series)
//   - calendar:  TradeDate (trading-day calendar)
//   - benchmark: BenchmarkIndex / BenchmarkDaily (index reference data)
//
// This module exists only to translate raw external data into clean DTOs.
// Domain logic must NOT live here.
package marketdata

import "time"

// FundDetail contains detailed metadata for a single fund.
type FundDetail struct {
	Name          string
	FundType      string
	Company       string
	Manager       string
	Size          float64
	EstablishDate *time.Time
	SizeDate      *time.Time
	CustodianBank string
	Benchmark     string
	ManagementFee *float64
	CustodianFee  *float64
}

// DividendRaw represents a raw dividend record from the data source.
type DividendRaw struct {
	FundCode        string
	FundName        string
	RecordDate      string
	ExDate          string
	PayDate         string
	DividendPerUnit float64
}

// SplitRaw represents a raw fund split/merge record from the data source.
type SplitRaw struct {
	FundCode   string
	FundName   string
	SplitDate  string
	SplitType  string
	SplitRatio float64
}
