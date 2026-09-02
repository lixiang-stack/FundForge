package dto

import (
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/benchmark"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/strategy"
)

// ============================================================================
// FUND CONVERTERS
// ============================================================================

func FundToDTO(f *fund.Fund) *Fund {
	if f == nil {
		return nil
	}
	return &Fund{
		Code:             string(f.Code), // FundCode is a string type alias
		Name:             f.Name,
		FundType:         f.FundType,
		PinyinAbbr:       f.PinyinAbbr,
		PinyinFull:       f.PinyinFull,
		Company:          f.Company,
		Manager:          f.Manager,
		Size:             f.Size,
		SizeDate:         f.SizeDate,
		EstablishDate:    f.EstablishDate,
		CustodianBank:    f.CustodianBank,
		ManagementFee:    f.ManagementFee,
		CustodianFee:     f.CustodianFee,
		Benchmark:        f.Benchmark,
		Status:           int(f.Status), // SubscriptionStatus enum to int
		SubscribedAt:     f.SubscribedAt,
		UnsubscribedAt:   f.UnsubscribedAt,
		InitialFetchDone: f.InitialFetchDone,
		LastNAVDate:      f.LastNAVDate,
		LastFetchAt:      f.LastFetchAt,
		CustomBenchmark:  f.CustomBenchmark,
		CreatedAt:        f.CreatedAt,
		UpdatedAt:        f.UpdatedAt,
	}
}

func FundsToDTO(funds []*fund.Fund) []Fund {
	if len(funds) == 0 {
		return []Fund{}
	}
	result := make([]Fund, len(funds))
	for i, f := range funds {
		dtoF := FundToDTO(f)
		if dtoF != nil {
			result[i] = *dtoF
		}
	}
	return result
}

func DividendToDTO(d fund.Dividend) Dividend {
	return Dividend{
		ID:              d.ID,
		FundCode:        string(d.FundCode),
		FundName:        d.FundName,
		RecordDate:      d.RecordDate,
		ExDate:          d.ExDate,
		DividendPerUnit: d.DividendPerUnit,
		PayDate:         d.PayDate,
		FetchedAt:       d.FetchedAt,
	}
}

func DividendsToDTO(divs []fund.Dividend) []Dividend {
	if len(divs) == 0 {
		return []Dividend{}
	}
	result := make([]Dividend, len(divs))
	for i, d := range divs {
		result[i] = DividendToDTO(d)
	}
	return result
}

func SplitToDTO(s fund.Split) Split {
	return Split{
		ID:         s.ID,
		FundCode:   string(s.FundCode),
		FundName:   s.FundName,
		SplitDate:  s.SplitDate,
		SplitType:  s.SplitType,
		SplitRatio: s.SplitRatio,
		FetchedAt:  s.FetchedAt,
	}
}

func SplitsToDTO(splits []fund.Split) []Split {
	if len(splits) == 0 {
		return []Split{}
	}
	result := make([]Split, len(splits))
	for i, s := range splits {
		result[i] = SplitToDTO(s)
	}
	return result
}

func ManagerChangeToDTO(mc fund.ManagerChange) ManagerChange {
	return ManagerChange{
		ID:              mc.ID,
		FundCode:        string(mc.FundCode),
		DetectedAt:      mc.DetectedAt,
		PreviousManager: mc.PreviousManager,
		CurrentManager:  mc.CurrentManager,
		ChangeDate:      mc.ChangeDate,
	}
}

func StockHoldingToDTO(sh fund.StockHolding) StockHolding {
	return StockHolding{
		ID:         sh.ID,
		FundCode:   string(sh.FundCode),
		ReportDate: sh.ReportDate,
		StockCode:  sh.StockCode,
		StockName:  sh.StockName,
		HoldRatio:  sh.HoldRatio,
		HoldShares: sh.HoldShares,
		HoldValue:  sh.HoldValue,
		FetchedAt:  sh.FetchedAt,
	}
}

func StockHoldingsToDTO(shs []fund.StockHolding) []StockHolding {
	if len(shs) == 0 {
		return []StockHolding{}
	}
	result := make([]StockHolding, len(shs))
	for i, sh := range shs {
		result[i] = StockHoldingToDTO(sh)
	}
	return result
}

func BondHoldingToDTO(bh fund.BondHolding) BondHolding {
	return BondHolding{
		ID:         bh.ID,
		FundCode:   string(bh.FundCode),
		ReportDate: bh.ReportDate,
		BondCode:   bh.BondCode,
		BondName:   bh.BondName,
		HoldRatio:  bh.HoldRatio,
		HoldValue:  bh.HoldValue,
		FetchedAt:  bh.FetchedAt,
	}
}

func BondHoldingsToDTO(bhs []fund.BondHolding) []BondHolding {
	if len(bhs) == 0 {
		return []BondHolding{}
	}
	result := make([]BondHolding, len(bhs))
	for i, bh := range bhs {
		result[i] = BondHoldingToDTO(bh)
	}
	return result
}

// ============================================================================
// ALERT CONVERTERS
// ============================================================================

func AlertToDTO(a *alert.Alert) *Alert {
	if a == nil {
		return nil
	}
	return &Alert{
		ID:                a.ID,
		FundCode:          string(a.FundCode),
		StrategyID:        a.StrategyID,
		Status:            string(a.Status), // Status enum to string
		Severity:          a.Severity,
		DataDate:          a.DataDate,
		TriggeredAt:       a.TriggeredAt,
		RecoveredAt:       a.RecoveredAt,
		ConfirmedAt:       a.ConfirmedAt,
		IndicatorSnapshot: a.IndicatorSnapshot,
		ConditionSnapshot: a.ConditionSnapshot,
		Message:           a.Message,
		CreatedAt:         a.CreatedAt,
		UpdatedAt:         a.UpdatedAt,
	}
}

func AlertsToDTO(alerts []*alert.Alert) []Alert {
	if len(alerts) == 0 {
		return []Alert{}
	}
	result := make([]Alert, len(alerts))
	for i, a := range alerts {
		dtoA := AlertToDTO(a)
		if dtoA != nil {
			result[i] = *dtoA
		}
	}
	return result
}

// ============================================================================
// STRATEGY CONVERTERS
// ============================================================================

func StrategyTemplateToDTO(st *strategy.StrategyTemplate) *StrategyTemplate {
	if st == nil {
		return nil
	}
	return &StrategyTemplate{
		ID:           st.ID,
		Name:         st.Name,
		Description:  st.Description,
		Severity:     string(st.Severity), // Severity enum to string
		Logic:        string(st.Logic),    // LogicOp enum to string
		Conditions:   ConditionsToDTO(st.Conditions),
		CooldownDays: st.CooldownDays,
		IsEnabled:    st.IsEnabled,
		IsPreset:     st.IsPreset,
		CreatedAt:    st.CreatedAt,
		UpdatedAt:    st.UpdatedAt,
	}
}

func StrategyTemplatesToDTO(sts []*strategy.StrategyTemplate) []StrategyTemplate {
	if len(sts) == 0 {
		return []StrategyTemplate{}
	}
	result := make([]StrategyTemplate, len(sts))
	for i, st := range sts {
		dtoSt := StrategyTemplateToDTO(st)
		if dtoSt != nil {
			result[i] = *dtoSt
		}
	}
	return result
}

func ConditionToDTO(c strategy.Condition) Condition {
	return Condition{
		Indicator: c.Indicator,
		Operator:  string(c.Operator), // Operator enum to string
		Threshold: c.Threshold,
	}
}

func ConditionsToDTO(conds []strategy.Condition) []Condition {
	if len(conds) == 0 {
		return []Condition{}
	}
	result := make([]Condition, len(conds))
	for i, c := range conds {
		result[i] = ConditionToDTO(c)
	}
	return result
}

func StrategyBindingToDTO(sb *strategy.StrategyBinding) *StrategyBinding {
	if sb == nil {
		return nil
	}
	return &StrategyBinding{
		ID:         sb.ID,
		StrategyID: sb.StrategyID,
		FundCode:   string(sb.FundCode),
		IsEnabled:  sb.IsEnabled,
		CreatedAt:  sb.CreatedAt,
	}
}

func StrategyBindingsToDTO(sbs []*strategy.StrategyBinding) []StrategyBinding {
	if len(sbs) == 0 {
		return []StrategyBinding{}
	}
	result := make([]StrategyBinding, len(sbs))
	for i, sb := range sbs {
		dtoSb := StrategyBindingToDTO(sb)
		if dtoSb != nil {
			result[i] = *dtoSb
		}
	}
	return result
}

// ============================================================================
// MARKET DATA CONVERTERS
// ============================================================================

func NAVToDTO(n *nav.NAV) *NAV {
	if n == nil {
		return nil
	}
	return &NAV{
		ID:          n.ID,
		FundCode:    string(n.FundCode),
		Date:        n.Date,
		UnitNAV:     n.UnitNAV,
		AccNAV:      n.AccNAV,
		DailyReturn: n.DailyReturn,
		FetchedAt:   n.FetchedAt,
	}
}

func NAVsToDTO(navs []nav.NAV) []NAV {
	if len(navs) == 0 {
		return []NAV{}
	}
	result := make([]NAV, len(navs))
	for i, n := range navs {
		dtoNav := NAVToDTO(&n)
		if dtoNav != nil {
			result[i] = *dtoNav
		}
	}
	return result
}

func MoneyFundNAVToDTO(mfn *nav.MoneyFundNAV) *MoneyFundNAV {
	if mfn == nil {
		return nil
	}
	return &MoneyFundNAV{
		ID:                   mfn.ID,
		FundCode:             string(mfn.FundCode),
		Date:                 mfn.Date,
		IncomePerTenThousand: mfn.IncomePerTenThousand,
		SevenDayYield:        mfn.SevenDayYield,
		FetchedAt:            mfn.FetchedAt,
	}
}

func MoneyFundNAVsToDTO(mfns []nav.MoneyFundNAV) []MoneyFundNAV {
	if len(mfns) == 0 {
		return []MoneyFundNAV{}
	}
	result := make([]MoneyFundNAV, len(mfns))
	for i, mfn := range mfns {
		dtoMfn := MoneyFundNAVToDTO(&mfn)
		if dtoMfn != nil {
			result[i] = *dtoMfn
		}
	}
	return result
}

func BenchmarkIndexToDTO(bi benchmark.BenchmarkIndex) BenchmarkIndex {
	return BenchmarkIndex{
		ID:                  bi.ID,
		IndexCode:           bi.IndexCode,
		IndexName:           bi.IndexName,
		ApplicableFundTypes: bi.ApplicableFundTypes,
		IsDefault:           bi.IsDefault,
		CreatedAt:           bi.CreatedAt,
	}
}

func BenchmarkIndicesToDTO(bis []benchmark.BenchmarkIndex) []BenchmarkIndex {
	if len(bis) == 0 {
		return []BenchmarkIndex{}
	}
	result := make([]BenchmarkIndex, len(bis))
	for i, bi := range bis {
		result[i] = BenchmarkIndexToDTO(bi)
	}
	return result
}

func BenchmarkDailyToDTO(bd benchmark.BenchmarkDaily) BenchmarkDaily {
	return BenchmarkDaily{
		ID:          bd.ID,
		IndexCode:   bd.IndexCode,
		TradeDate:   bd.TradeDate,
		ClosePrice:  bd.ClosePrice,
		DailyReturn: bd.DailyReturn,
		FetchedAt:   bd.FetchedAt,
	}
}

func BenchmarkDailySliceToDTO(bds []benchmark.BenchmarkDaily) []BenchmarkDaily {
	if len(bds) == 0 {
		return []BenchmarkDaily{}
	}
	result := make([]BenchmarkDaily, len(bds))
	for i, bd := range bds {
		result[i] = BenchmarkDailyToDTO(bd)
	}
	return result
}

func PriceBarToDTO(pb nav.PriceBar) PriceBar {
	return PriceBar{
		Date:  pb.Date,
		Close: pb.Close,
	}
}

func PriceBarsToDTO(pbs []nav.PriceBar) []PriceBar {
	if len(pbs) == 0 {
		return []PriceBar{}
	}
	result := make([]PriceBar, len(pbs))
	for i, pb := range pbs {
		result[i] = PriceBarToDTO(pb)
	}
	return result
}
