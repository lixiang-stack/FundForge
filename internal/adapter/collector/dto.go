package collector

import (
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
)

// ---------------------------------------------------------------------------
// JSON response structs matching Python collector's normalized output.
// Field names match the FIELD_MAPS in collector/main.py.
// ---------------------------------------------------------------------------

type navItemJSON struct {
	NavDate     *string  `json:"nav_date"`
	UnitNav     *float64 `json:"unit_nav"`
	AccNav      *float64 `json:"acc_nav"`
	DailyReturn *float64 `json:"daily_return"`
}

type tradeCalendarJSON struct {
	TradeDate string `json:"trade_date"`
}

// fund_individual_basic_info_xq returns key-value pairs.
type fundDetailJSON struct {
	Item  *string `json:"item"`
	Value *string `json:"value"`
}

type dividendJSON struct {
	FundCode        *string  `json:"fund_code"`
	FundName        *string  `json:"fund_name"`
	RecordDate      *string  `json:"record_date"`
	ExDate          *string  `json:"ex_date"`
	DividendPerUnit *float64 `json:"dividend_per_unit"`
	PayDate         *string  `json:"pay_date"`
}

type splitJSON struct {
	FundCode   *string  `json:"fund_code"`
	FundName   *string  `json:"fund_name"`
	SplitDate  *string  `json:"split_date"`
	SplitType  *string  `json:"split_type"`
	SplitRatio *float64 `json:"split_ratio"`
}

// ---------------------------------------------------------------------------
// Conversion functions: JSON → domain DTOs
// ---------------------------------------------------------------------------

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func f64(p *float64) float64 {
	if p == nil {
		return 0
	}
	return *p
}

func convertNAVs(raw []navItemJSON, fundCode string) []nav.NAV {
	navs := make([]nav.NAV, 0, len(raw))
	now := time.Now()
	for _, r := range raw {
		d := parseDate(str(r.NavDate))
		if d.IsZero() {
			continue
		}
		navs = append(navs, nav.NAV{
			FundCode:    shared.FundCode(fundCode),
			Date:        d,
			UnitNAV:     f64(r.UnitNav),
			AccNAV:      f64(r.AccNav),
			DailyReturn: f64(r.DailyReturn),
			FetchedAt:   now,
		})
	}
	return navs
}

func convertCalendar(raw []tradeCalendarJSON) []time.Time {
	dates := make([]time.Time, 0, len(raw))
	for _, r := range raw {
		d := parseDate(r.TradeDate)
		if !d.IsZero() {
			dates = append(dates, d)
		}
	}
	return dates
}

func convertFundDetail(raw []fundDetailJSON) *marketdata.FundDetail {
	if len(raw) == 0 {
		return nil
	}
	detail := &marketdata.FundDetail{}
	kv := make(map[string]string)
	for _, r := range raw {
		kv[str(r.Item)] = str(r.Value)
	}
	detail.Name = kv["基金名称"]
	detail.FundType = kv["基金类型"]
	detail.Company = kv["基金公司"]
	detail.Manager = kv["基金经理"]
	detail.CustodianBank = kv["托管银行"]
	detail.Benchmark = kv["业绩基准"]
	if v, ok := kv["基金规模"]; ok {
		detail.Size = parseFloatFromStr(v)
	}
	if v, ok := kv["成立时间"]; ok {
		t := parseDate(v)
		if !t.IsZero() {
			detail.EstablishDate = &t
		}
	}
	return detail
}

func convertDividends(raw []dividendJSON) []marketdata.DividendRaw {
	items := make([]marketdata.DividendRaw, 0, len(raw))
	for _, r := range raw {
		items = append(items, marketdata.DividendRaw{
			FundCode:        str(r.FundCode),
			FundName:        str(r.FundName),
			RecordDate:      str(r.RecordDate),
			ExDate:          str(r.ExDate),
			PayDate:         str(r.PayDate),
			DividendPerUnit: f64(r.DividendPerUnit),
		})
	}
	return items
}

func convertSplits(raw []splitJSON) []marketdata.SplitRaw {
	items := make([]marketdata.SplitRaw, 0, len(raw))
	for _, r := range raw {
		items = append(items, marketdata.SplitRaw{
			FundCode:   str(r.FundCode),
			FundName:   str(r.FundName),
			SplitDate:  str(r.SplitDate),
			SplitType:  str(r.SplitType),
			SplitRatio: f64(r.SplitRatio),
		})
	}
	return items
}

// ---------------------------------------------------------------------------
// Date / number parsing helpers
// ---------------------------------------------------------------------------

func parseDate(s string) time.Time {
	for _, layout := range []string{"2006-01-02", "2006/01/02", "20060102"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t
		}
	}
	return time.Time{}
}

func parseFloatFromStr(s string) float64 {
	var v float64
	for _, ch := range s {
		if (ch >= '0' && ch <= '9') || ch == '.' {
			// simple extraction of first float-like substring
			break
		}
	}
	// Use fmt.Sscanf for robust extraction
	_, _ = fmt.Sscanf(s, "%f", &v)
	return v
}
