package http

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/adapter/http/dto"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/domain/shared"
)

// AlertHandler handles alert-related HTTP requests.
type AlertHandler struct {
	alertUC *application.AlertUseCase
}

// NewAlertHandler creates a new AlertHandler.
func NewAlertHandler(alertUC *application.AlertUseCase) *AlertHandler {
	return &AlertHandler{alertUC: alertUC}
}

// RegisterAlertRoutes registers alert-related routes on the given router group.
func RegisterAlertRoutes(rg *gin.RouterGroup, h *AlertHandler) {
	alerts := rg.Group("/alerts")
	{
		alerts.GET("", h.listActive)
		alerts.GET("/fund/:code", h.listByFund)
		alerts.POST("/:id/confirm", h.confirmAlert)
		alerts.POST("/:id/ignore", h.ignoreAlert)
	}
}

// parseAlertID extracts and validates the :id parameter as int64.
func parseAlertID(c *gin.Context) (int64, bool) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		dto.Error(c, http.StatusBadRequest, "invalid alert id")
		return 0, false
	}
	return id, true
}

// listActive returns all active (triggered or confirmed) alerts.
func (h *AlertHandler) listActive(c *gin.Context) {
	alerts, err := h.alertUC.ListActive(c.Request.Context())
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}

	dto.Success(c, dto.AlertsToDTO(alerts))
}

// listByFund returns alerts for a specific fund.
func (h *AlertHandler) listByFund(c *gin.Context) {
	code := c.Param("code")
	alerts, err := h.alertUC.ListByFund(c.Request.Context(), shared.FundCode(code))
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.AlertsToDTO(alerts))
}

// confirmAlert marks an alert as confirmed by the user.
func (h *AlertHandler) confirmAlert(c *gin.Context) {
	id, ok := parseAlertID(c)
	if !ok {
		return
	}

	if err := h.alertUC.ConfirmAlert(c.Request.Context(), id); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, nil)
}

// ignoreAlert marks an alert as ignored by the user.
func (h *AlertHandler) ignoreAlert(c *gin.Context) {
	id, ok := parseAlertID(c)
	if !ok {
		return
	}

	if err := h.alertUC.IgnoreAlert(c.Request.Context(), id); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, nil)
}
