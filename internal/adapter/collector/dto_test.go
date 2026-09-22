package collector

import (
	"testing"
	"time"

	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/stretchr/testify/assert"
)

// fixture 对齐 collector FIELD_MAPS["fund_detail"] 的英文 item 输出
// （与 agent/tests/conftest.py 的 DETAIL_ROWS 同源）。
func detailFixture() []fundDetailJSON {
	strPtr := func(s string) *string { return &s }
	return []fundDetailJSON{
		{Item: strPtr("fund_code"), Value: strPtr("519770")},
		{Item: strPtr("fund_name"), Value: strPtr("交银优择回报A")},
		{Item: strPtr("fund_full_name"), Value: strPtr("交银施罗德优择回报灵活配置混合型证券投资基金")},
		{Item: strPtr("inception_date"), Value: strPtr("2016-04-22")},
		{Item: strPtr("aum"), Value: strPtr("44.16亿")},
		{Item: strPtr("fund_manager"), Value: strPtr("周珊珊 高扬")},
		{Item: strPtr("fund_type"), Value: strPtr("混合型-灵活配置")},
		{Item: strPtr("fund_company"), Value: strPtr("交银施罗德基金公司")},
		{Item: strPtr("custodian_bank"), Value: strPtr("中信银行股份有限公司")},
		{Item: strPtr("rating_agency"), Value: nil},
		{Item: strPtr("fund_rating"), Value: strPtr("暂无评级")},
		{Item: strPtr("investment_strategy"), Value: strPtr("灵活调整大类资产配置比例。")},
		{Item: strPtr("investment_objective"), Value: strPtr("力争长期稳健回报。")},
		{Item: strPtr("benchmark"), Value: strPtr("50%×沪深300指数收益率+50%×中债综合全价指数收益率")},
	}
}

func TestConvertFundDetail(t *testing.T) {
	detail := convertFundDetail(detailFixture())
	assert.Equal(t, "交银优择回报A", detail.Name)
	assert.Equal(t, "混合型-灵活配置", detail.FundType)
	assert.Equal(t, "交银施罗德基金公司", detail.Company)
	assert.Equal(t, "周珊珊 高扬", detail.Manager)
	assert.Equal(t, "中信银行股份有限公司", detail.CustodianBank)
	assert.Equal(t, "50%×沪深300指数收益率+50%×中债综合全价指数收益率", detail.Benchmark)
	assert.Equal(t, 44.16, detail.Size)
	if assert.NotNil(t, detail.EstablishDate) {
		assert.Equal(t, time.Date(2016, 4, 22, 0, 0, 0, 0, time.UTC), *detail.EstablishDate)
	}
}

func TestConvertFundDetailEmpty(t *testing.T) {
	var raw []fundDetailJSON
	assert.Nil(t, convertFundDetail(raw))
}

func TestConvertFundDetailNilValues(t *testing.T) {
	strPtr := func(s string) *string { return &s }
	detail := convertFundDetail([]fundDetailJSON{{Item: strPtr("fund_name"), Value: nil}})
	assert.Equal(t, &marketdata.FundDetail{Name: ""}, detail)
}

func TestConvertIndexDailies(t *testing.T) {
	f64Ptr := func(v float64) *float64 { return &v }
	raw := []indexDailyJSON{
		{TradeDate: "2026-09-01", Close: f64Ptr(100.0)},
		{TradeDate: "2026-09-02", Close: f64Ptr(102.0)},
		{TradeDate: "2026-09-03", Close: f64Ptr(99.96)},
		{TradeDate: "invalid", Close: f64Ptr(1.0)},
		{TradeDate: "2026-09-05", Close: nil},
	}
	dailies := convertIndexDailies(raw, "000905")

	// 非法日期与空 close 的行被跳过
	assert.Len(t, dailies, 3)
	assert.Equal(t, "000905", dailies[0].IndexCode)
	assert.InDelta(t, 100.0, dailies[0].ClosePrice, 1e-9)
	assert.InDelta(t, 0.0, dailies[0].DailyReturn, 1e-9)   // 首行无前值
	assert.InDelta(t, 2.0, dailies[1].DailyReturn, 1e-9)   // (102-100)/100 = 2%
	assert.InDelta(t, -2.0, dailies[2].DailyReturn, 1e-9)  // (99.96-102)/102 = -2%
	assert.False(t, dailies[0].TradeDate.IsZero())
	assert.False(t, dailies[0].FetchedAt.IsZero())
}
