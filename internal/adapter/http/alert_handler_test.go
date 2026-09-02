package http

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/adapter/http/dto"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"
)

// newTestAlertRouter creates a gin engine wired with AlertHandler for testing.
func newTestAlertRouter(alertUC *application.AlertUseCase) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewAlertHandler(alertUC)
	RegisterAlertRoutes(r.Group(""), h)
	return r
}

func TestAlertHandler_ListActive(t *testing.T) {
	alertRepo := &mockAlertRepo{
		alerts: []*alert.Alert{
			{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Triggered, Severity: "critical"},
			{ID: 2, FundCode: "110011", StrategyID: 2, Status: alert.Confirmed, Severity: "warning"},
		},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/alerts", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)

	var alerts []dto.Alert
	require.NoError(t, json.Unmarshal(resp.Data, &alerts))
	assert.Len(t, alerts, 2)
	assert.Equal(t, int64(1), alerts[0].ID)
	assert.Equal(t, "critical", alerts[0].Severity)
}

func TestAlertHandler_ListActive_Empty(t *testing.T) {
	alertRepo := &mockAlertRepo{alerts: []*alert.Alert{}}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/alerts", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAlertHandler_ListByFund(t *testing.T) {
	alertRepo := &mockAlertRepo{
		byFund: []*alert.Alert{
			{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Triggered, Severity: "critical"},
		},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/alerts/fund/000001", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestAlertHandler_ConfirmAlert_Success(t *testing.T) {
	alertRepo := &mockAlertRepo{
		byID: &alert.Alert{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Triggered, Severity: "critical"},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/alerts/1/confirm", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp apiResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Code)
}

func TestAlertHandler_ConfirmAlert_InvalidTransition(t *testing.T) {
	// Alert is already confirmed, cannot confirm again.
	alertRepo := &mockAlertRepo{
		byID: &alert.Alert{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Confirmed, Severity: "critical"},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/alerts/1/confirm", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	assert.Contains(t, w.Body.String(), "confirmed")
}

func TestAlertHandler_ConfirmAlert_InvalidID(t *testing.T) {
	alertRepo := &mockAlertRepo{}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/alerts/abc/confirm", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "invalid alert id")
}

func TestAlertHandler_IgnoreAlert_Success(t *testing.T) {
	alertRepo := &mockAlertRepo{
		byID: &alert.Alert{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Triggered, Severity: "warning"},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/alerts/1/ignore", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAlertHandler_IgnoreAlert_InvalidTransition(t *testing.T) {
	// Alert is already recovered, cannot ignore.
	alertRepo := &mockAlertRepo{
		byID: &alert.Alert{ID: 1, FundCode: "000001", StrategyID: 1, Status: alert.Recovered, Severity: "warning"},
	}
	logger := zap.NewNop().Sugar()
	alertUC := application.NewAlertUseCase(alertRepo, logger)
	r := newTestAlertRouter(alertUC)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/alerts/1/ignore", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
}
