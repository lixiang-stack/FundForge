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
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"
)

// newTestFundRouter creates a gin engine wired with FundHandler for testing.
func newTestFundRouter(fundUC *application.FundUseCase, analysisUC *application.AnalysisUseCase) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewFundHandler(fundUC, analysisUC)
	RegisterFundRoutes(r.Group(""), h)
	return r
}

func TestFundHandler_ListFunds(t *testing.T) {
	fundRepo := &mockFundRepo{
		funds: []*fund.Fund{
			{Code: "000001", Name: "华夏成长混合", Status: fund.Subscribed},
			{Code: "110011", Name: "易方达中小盘混合", Status: fund.Subscribed},
		},
	}
	navRepo := &mockNAVRepo{}

	provider := &mockMarketDataClient{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, provider, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
	assert.Equal(t, "ok", resp.Message)

	var funds []dto.Fund
	require.NoError(t, json.Unmarshal(resp.Data, &funds))
	assert.Len(t, funds, 2)
	assert.Equal(t, "000001", funds[0].Code)
	assert.Equal(t, "华夏成长混合", funds[0].Name)
}

func TestFundHandler_ListFunds_Empty(t *testing.T) {
	fundRepo := &mockFundRepo{funds: []*fund.Fund{}}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestFundHandler_SubscribeFund_Success(t *testing.T) {
	fundRepo := &mockFundRepo{
		getByCode: map[string]*fund.Fund{},
	}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	body := `{"fund_code":"000001"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/funds", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusCreated, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestFundHandler_SubscribeFund_MissingCode(t *testing.T) {
	fundRepo := &mockFundRepo{}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	body := `{}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/funds", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestFundHandler_SubscribeFund_InvalidCode(t *testing.T) {
	fundRepo := &mockFundRepo{
		getByCode: map[string]*fund.Fund{},
	}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	body := `{"fund_code":"abc"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/funds", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	assert.Contains(t, w.Body.String(), "fund code must be 6 digits")
}

func TestFundHandler_SubscribeFund_AlreadySubscribed(t *testing.T) {
	now := time.Now()
	fundRepo := &mockFundRepo{
		getByCode: map[string]*fund.Fund{
			"000001": {Code: "000001", Name: "华夏成长", Status: fund.Subscribed, SubscribedAt: &now},
		},
	}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	body := `{"fund_code":"000001"}`
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/funds", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	assert.Contains(t, w.Body.String(), "already subscribed")
}

func TestFundHandler_UnsubscribeFund_Success(t *testing.T) {
	now := time.Now()
	fundRepo := &mockFundRepo{
		getByCode: map[string]*fund.Fund{
			"000001": {Code: "000001", Name: "华夏成长", Status: fund.Subscribed, SubscribedAt: &now},
		},
	}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodDelete, "/funds/000001", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestFundHandler_SearchFunds(t *testing.T) {
	fundRepo := &mockFundRepo{
		searchRes: []*fund.Fund{
			{Code: "000001", Name: "华夏成长混合"},
		},
	}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds/search?q=华夏", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestFundHandler_SearchFunds_MissingQuery(t *testing.T) {
	fundRepo := &mockFundRepo{}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds/search", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestFundHandler_GetFundNAV(t *testing.T) {
	fundRepo := &mockFundRepo{}
	navRepo := &mockNAVRepo{
		navs: []nav.NAV{
			{FundCode: "000001", Date: time.Date(2026, 4, 20, 0, 0, 0, 0, time.UTC), UnitNAV: 1.1},
			{FundCode: "000001", Date: time.Date(2026, 4, 21, 0, 0, 0, 0, time.UTC), UnitNAV: 1.12},
		},
	}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds/000001/nav?start=2026-04-01&end=2026-04-24", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)

	var navs []dto.NAV
	require.NoError(t, json.Unmarshal(resp.Data, &navs))
	assert.Len(t, navs, 2)
	assert.Equal(t, 1.1, navs[0].UnitNAV)
	assert.Equal(t, 1.12, navs[1].UnitNAV)
}

func TestFundHandler_GetFundNAV_InvalidDate(t *testing.T) {
	fundRepo := &mockFundRepo{}
	navRepo := &mockNAVRepo{}
	logger := zap.NewNop().Sugar()

	fundUC := application.NewFundUseCase(fundRepo, navRepo, &mockMarketDataClient{}, logger)
	r := newTestFundRouter(fundUC, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/funds/000001/nav?start=bad-date", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "invalid start date")
}

// Suppress unused variable warnings.
var _ alert.AlertRepository = (*mockAlertRepo)(nil)
