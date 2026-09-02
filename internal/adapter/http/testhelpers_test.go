package http

import (
	"context"
	"encoding/json"
	"time"

	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/benchmark"
	"github.com/lixiang/fundforge/internal/domain/calendar"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
	"go.uber.org/zap"
)

// ---- Mock Fund Repository ----

type mockFundRepo struct {
	funds     []*fund.Fund
	searchRes []*fund.Fund
	saved     []*fund.Fund
	getByCode map[string]*fund.Fund
	getByErr  error
	searchErr error
	saveErr   error
	listErr   error
}

func (m *mockFundRepo) GetByCode(_ context.Context, code fund.FundCode) (*fund.Fund, error) {
	if m.getByErr != nil {
		return nil, m.getByErr
	}
	if m.getByCode != nil {
		return m.getByCode[string(code)], nil
	}
	return nil, nil
}
func (m *mockFundRepo) ListSubscribed(_ context.Context) ([]*fund.Fund, error) {
	if m.listErr != nil {
		return nil, m.listErr
	}
	return m.funds, nil
}
func (m *mockFundRepo) ListAll(_ context.Context) ([]*fund.Fund, error) { return m.funds, nil }
func (m *mockFundRepo) Save(_ context.Context, f *fund.Fund) error {
	m.saved = append(m.saved, f)
	return m.saveErr
}
func (m *mockFundRepo) UpdateFetchStatus(_ context.Context, _ fund.FundCode, _ time.Time, _ time.Time) error {
	return nil
}
func (m *mockFundRepo) Search(_ context.Context, _ string, _ int) ([]*fund.Fund, error) {
	if m.searchErr != nil {
		return nil, m.searchErr
	}
	return m.searchRes, nil
}
func (m *mockFundRepo) Delete(_ context.Context, _ fund.FundCode) error { return nil }

// ---- Mock NAV Repository ----

type mockNAVRepo struct {
	navs      []nav.NAV
	latest    *nav.NAV
	getErr    error
	latestErr error
}

func (m *mockNAVRepo) GetByFundCode(_ context.Context, _ shared.FundCode, _, _ time.Time) ([]nav.NAV, error) {
	return m.navs, m.getErr
}
func (m *mockNAVRepo) GetLatest(_ context.Context, _ shared.FundCode) (*nav.NAV, error) {
	return m.latest, m.latestErr
}
func (m *mockNAVRepo) GetLatestBatch(_ context.Context, codes []shared.FundCode) (map[shared.FundCode]*nav.NAV, error) {
	result := make(map[shared.FundCode]*nav.NAV)
	if m.latest != nil {
		for _, code := range codes {
			result[code] = m.latest
		}
	}
	return result, m.latestErr
}
func (m *mockNAVRepo) BatchSave(_ context.Context, _ []nav.NAV) (int, error) { return 0, nil }
func (m *mockNAVRepo) GetLatestDate(_ context.Context, _ shared.FundCode) (*time.Time, error) {
	return nil, nil
}
func (m *mockNAVRepo) SaveMoneyFundNAV(_ context.Context, _ []nav.MoneyFundNAV) error {
	return nil
}

// ---- Mock Alert Repository ----

type mockAlertRepo struct {
	alerts    []*alert.Alert
	byFund    []*alert.Alert
	byID      *alert.Alert
	listErr   error
	getErr    error
	updateErr error
}

func (m *mockAlertRepo) GetByID(_ context.Context, _ int64) (*alert.Alert, error) {
	return m.byID, m.getErr
}
func (m *mockAlertRepo) ListByFund(_ context.Context, _ shared.FundCode, _ []alert.Status) ([]*alert.Alert, error) {
	return m.byFund, nil
}
func (m *mockAlertRepo) ListActive(_ context.Context) ([]*alert.Alert, error) {
	return m.alerts, m.listErr
}
func (m *mockAlertRepo) ListRecent(_ context.Context, _ time.Time) ([]*alert.Alert, error) {
	return m.alerts, nil
}
func (m *mockAlertRepo) Save(_ context.Context, _ *alert.Alert) error         { return nil }
func (m *mockAlertRepo) UpdateStatus(_ context.Context, _ *alert.Alert) error { return m.updateErr }
func (m *mockAlertRepo) HasRecentAlert(_ context.Context, _ int64, _ shared.FundCode, _ time.Time) (bool, error) {
	return false, nil
}

// ---- Mock Strategy Repository ----

type mockStrategyRepo struct {
	strategies []*strategy.StrategyTemplate
	byID       *strategy.StrategyTemplate
	bindings   []*strategy.StrategyBinding
	listErr    error
	getErr     error
	saveErr    error
	updateErr  error
	deleteErr  error
}

func (m *mockStrategyRepo) GetByID(_ context.Context, _ int64) (*strategy.StrategyTemplate, error) {
	if m.getErr != nil {
		return nil, m.getErr
	}
	return m.byID, nil
}
func (m *mockStrategyRepo) ListEnabled(_ context.Context) ([]*strategy.StrategyTemplate, error) {
	return m.strategies, m.listErr
}
func (m *mockStrategyRepo) ListAll(_ context.Context) ([]*strategy.StrategyTemplate, error) {
	return m.strategies, m.listErr
}
func (m *mockStrategyRepo) Save(_ context.Context, _ *strategy.StrategyTemplate) error {
	return m.saveErr
}
func (m *mockStrategyRepo) Update(_ context.Context, _ *strategy.StrategyTemplate) error {
	return m.updateErr
}
func (m *mockStrategyRepo) Delete(_ context.Context, _ int64) error { return m.deleteErr }
func (m *mockStrategyRepo) GetBindingsForFund(_ context.Context, _ shared.FundCode) ([]*strategy.StrategyBinding, error) {
	return m.bindings, nil
}
func (m *mockStrategyRepo) GetBindingsForStrategy(_ context.Context, _ int64) ([]*strategy.StrategyBinding, error) {
	return m.bindings, nil
}
func (m *mockStrategyRepo) SaveBinding(_ context.Context, _ int64, _ shared.FundCode) error {
	return m.saveErr
}
func (m *mockStrategyRepo) DeleteBinding(_ context.Context, _ int64, _ shared.FundCode) error {
	return m.deleteErr
}

// ---- Mock Market Data Provider ----

type mockMarketDataClient struct{}

func (m *mockMarketDataClient) FetchFundNAV(_ context.Context, _, _, _ string) ([]nav.NAV, error) {
	return nil, nil
}
func (m *mockMarketDataClient) FetchTradeCalendar(_ context.Context) ([]time.Time, error) {
	return nil, nil
}
func (m *mockMarketDataClient) FetchFundDetail(_ context.Context, _ string) (*marketdata.FundDetail, error) {
	return &marketdata.FundDetail{Name: "Test Fund"}, nil
}
func (m *mockMarketDataClient) FetchDividends(_ context.Context) ([]marketdata.DividendRaw, error) {
	return nil, nil
}
func (m *mockMarketDataClient) FetchSplits(_ context.Context) ([]marketdata.SplitRaw, error) {
	return nil, nil
}

// ---- Mock Calendar Repository ----

type mockCalendarRepo struct{}

func (m *mockCalendarRepo) IsTradingDay(_ context.Context, _ time.Time) (bool, error) {
	return true, nil
}
func (m *mockCalendarRepo) GetTradingDaysBetween(_ context.Context, _, _ time.Time) ([]time.Time, error) {
	return nil, nil
}
func (m *mockCalendarRepo) GetRecentTradingDays(_ context.Context, _ int) ([]time.Time, error) {
	return nil, nil
}
func (m *mockCalendarRepo) BatchSave(_ context.Context, _ []calendar.TradeDate) error { return nil }

// ---- Mock Benchmark Repository ----

type mockBenchmarkRepo struct{}

func (m *mockBenchmarkRepo) GetAllIndices(_ context.Context) ([]benchmark.BenchmarkIndex, error) {
	return nil, nil
}
func (m *mockBenchmarkRepo) GetDefaultForFundType(_ context.Context, _ string) (*benchmark.BenchmarkIndex, error) {
	return nil, nil
}
func (m *mockBenchmarkRepo) GetDailyData(_ context.Context, _ string, _, _ time.Time) ([]benchmark.BenchmarkDaily, error) {
	return nil, nil
}
func (m *mockBenchmarkRepo) BatchSaveDailyData(_ context.Context, _ []benchmark.BenchmarkDaily) error {
	return nil
}

// ---- Helper constructors for use case wiring in tests ----

func newTestLogger() *zap.SugaredLogger {
	return zap.NewNop().Sugar()
}

func newMockFundUC(repo fund.FundRepository, logger *zap.SugaredLogger) *application.FundUseCase {
	return application.NewFundUseCase(repo, &mockNAVRepo{}, &mockMarketDataClient{}, logger)
}

func newMockAlertUC(repo alert.AlertRepository, logger *zap.SugaredLogger) *application.AlertUseCase {
	return application.NewAlertUseCase(repo, logger)
}

// ---- parseJSONResponse helper ----

type apiResponse struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

var (
	_ marketdata.FundProvider            = (*mockMarketDataClient)(nil)
	_ marketdata.TradeCalendarProvider   = (*mockMarketDataClient)(nil)
	_ marketdata.CorporateActionProvider = (*mockMarketDataClient)(nil)
)
