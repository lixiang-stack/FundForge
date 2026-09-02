package http

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/adapter/http/dto"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/strategy"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// newTestStrategyRouter creates a gin engine wired with StrategyHandler for testing.
func newTestStrategyRouter(repo *mockStrategyRepo) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	// Create a mock fund repo that returns a valid fund for SaveBinding validation.
	fundRepo := &mockFundRepo{
		getByCode: map[string]*fund.Fund{
			"000001": {Code: "000001", Name: "测试基金", Status: fund.Subscribed},
		},
	}
	strategyUC := application.NewStrategyUseCase(fundRepo, repo, repo)
	h := NewStrategyHandler(strategyUC)
	RegisterStrategyRoutes(r.Group(""), h)
	return r
}

func TestStrategyHandler_ListStrategies(t *testing.T) {
	repo := &mockStrategyRepo{
		strategies: []*strategy.StrategyTemplate{
			{ID: 1, Name: "回撤告警", Severity: strategy.Critical, Logic: strategy.AND, IsEnabled: true},
			{ID: 2, Name: "波动率告警", Severity: strategy.Warning, Logic: strategy.AND, IsEnabled: true},
		},
	}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/strategies", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)

	var strategies []dto.StrategyTemplate
	require.NoError(t, json.Unmarshal(resp.Data, &strategies))
	assert.Len(t, strategies, 2)
	assert.Equal(t, "回撤告警", strategies[0].Name)
	assert.Equal(t, "critical", strategies[0].Severity)
}

func TestStrategyHandler_GetStrategy_Found(t *testing.T) {
	repo := &mockStrategyRepo{
		byID: &strategy.StrategyTemplate{
			ID: 1, Name: "回撤告警", Severity: strategy.Critical, Logic: strategy.AND,
			Conditions:   []strategy.Condition{{Indicator: "max_drawdown_1y", Operator: strategy.LTE, Threshold: -15}},
			CooldownDays: 7, IsEnabled: true, IsPreset: true,
		},
	}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/strategies/1", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)

	var strategy dto.StrategyTemplate
	require.NoError(t, json.Unmarshal(resp.Data, &strategy))
	assert.Equal(t, int64(1), strategy.ID)
	assert.Equal(t, "回撤告警", strategy.Name)
	assert.Equal(t, "critical", strategy.Severity)
	assert.Len(t, strategy.Conditions, 1)
}

func TestStrategyHandler_GetStrategy_NotFound(t *testing.T) {
	repo := &mockStrategyRepo{
		byID: nil, // not found
	}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/strategies/999", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusNotFound, w.Code)
	assert.Contains(t, w.Body.String(), "strategy not found")
}

func TestStrategyHandler_GetStrategy_InvalidID(t *testing.T) {
	repo := &mockStrategyRepo{}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/strategies/abc", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "invalid strategy id")
}

func TestStrategyHandler_DeleteStrategy(t *testing.T) {
	repo := &mockStrategyRepo{}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/strategies/1", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestStrategyHandler_BindStrategy(t *testing.T) {
	repo := &mockStrategyRepo{
		byID: &strategy.StrategyTemplate{ID: 1, Name: "回撤告警"},
	}
	r := newTestStrategyRouter(repo)

	body := `{"fund_code":"000001"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/strategies/1/bindings", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusCreated, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestStrategyHandler_BindStrategy_MissingFundCode(t *testing.T) {
	repo := &mockStrategyRepo{}
	r := newTestStrategyRouter(repo)

	body := `{}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/strategies/1/bindings", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestStrategyHandler_UnbindStrategy(t *testing.T) {
	repo := &mockStrategyRepo{}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/strategies/1/bindings/000001", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestStrategyHandler_ListBindings(t *testing.T) {
	repo := &mockStrategyRepo{
		bindings: []*strategy.StrategyBinding{
			{ID: 1, StrategyID: 1, FundCode: "000001", IsEnabled: true, CreatedAt: time.Now()},
			{ID: 2, StrategyID: 1, FundCode: "110011", IsEnabled: true, CreatedAt: time.Now()},
		},
	}
	r := newTestStrategyRouter(repo)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/strategies/1/bindings", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)

	var bindings []dto.StrategyBinding
	require.NoError(t, json.Unmarshal(resp.Data, &bindings))
	assert.Len(t, bindings, 2)
	assert.Equal(t, "000001", bindings[0].FundCode)
}

func TestStrategyHandler_UpdateStrategy(t *testing.T) {
	repo := &mockStrategyRepo{
		byID: &strategy.StrategyTemplate{
			ID: 1, Name: "回撤告警", Severity: strategy.Critical, Logic: strategy.AND,
			IsEnabled: true,
		},
	}
	r := newTestStrategyRouter(repo)

	body := `{"name":"更新后的策略","description":"updated"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/strategies/1", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestStrategyHandler_UpdateStrategy_NotFound(t *testing.T) {
	repo := &mockStrategyRepo{
		byID: nil,
	}
	r := newTestStrategyRouter(repo)

	body := `{"name":"updated"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/strategies/999", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusNotFound, w.Code)
}
