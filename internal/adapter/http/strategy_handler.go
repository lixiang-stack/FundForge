package http

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/adapter/http/dto"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
)

// StrategyHandler handles strategy-related HTTP requests.
type StrategyHandler struct {
	strategyUC *application.StrategyUseCase
}

// NewStrategyHandler creates a new StrategyHandler.
func NewStrategyHandler(strategyUC *application.StrategyUseCase) *StrategyHandler {
	return &StrategyHandler{
		strategyUC: strategyUC,
	}
}

// RegisterStrategyRoutes registers strategy-related routes on the given router group.
func RegisterStrategyRoutes(rg *gin.RouterGroup, h *StrategyHandler) {
	strategies := rg.Group("/strategies")
	{
		strategies.GET("", h.listStrategies)
		strategies.GET("/:id", h.getStrategy)
		strategies.PUT("/:id", h.updateStrategy)
		strategies.DELETE("/:id", h.deleteStrategy)
		strategies.POST("/:id/bindings", h.bindStrategy)
		strategies.GET("/:id/bindings", h.listBindings)
		strategies.DELETE("/:id/bindings/:code", h.unbindStrategy)
	}
}

// parseStrategyID extracts and validates the :id parameter as int64.
func parseStrategyID(c *gin.Context) (int64, bool) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		dto.Error(c, http.StatusBadRequest, "invalid strategy id")
		return 0, false
	}
	return id, true
}

// listStrategies returns all strategy templates.
func (h *StrategyHandler) listStrategies(c *gin.Context) {
	strategies, err := h.strategyUC.ListAll(c.Request.Context())
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.StrategyTemplatesToDTO(strategies))
}

// getStrategy returns a single strategy template by ID.
func (h *StrategyHandler) getStrategy(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	s, err := h.strategyUC.GetByID(c.Request.Context(), id)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	if s == nil {
		dto.Error(c, http.StatusNotFound, "strategy not found")
		return
	}
	dto.Success(c, dto.StrategyTemplateToDTO(s))
}

// updateStrategy updates an existing strategy template.
func (h *StrategyHandler) updateStrategy(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	ctx := c.Request.Context()

	existing, err := h.strategyUC.GetByID(ctx, id)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	if existing == nil {
		dto.Error(c, http.StatusNotFound, "strategy not found")
		return
	}

	// Bind the update payload onto the existing strategy.
	if err := c.ShouldBindJSON(existing); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}
	existing.ID = id // Ensure ID is not overwritten by JSON binding.

	if err := h.strategyUC.Update(ctx, existing); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.StrategyTemplateToDTO(existing))
}

// deleteStrategy deletes a strategy template by ID.
func (h *StrategyHandler) deleteStrategy(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	if err := h.strategyUC.Delete(c.Request.Context(), id); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, nil)
}

// bindStrategy creates a binding between a strategy and a fund.
func (h *StrategyHandler) bindStrategy(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	var req dto.BindStrategyReq
	if err := c.ShouldBindJSON(&req); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}

	st, err := h.strategyUC.SaveBinding(c.Request.Context(), id, shared.FundCode(req.FundCode))
	if err != nil {
		if errors.Is(err, strategy.ErrStrategyNotFound) {
			dto.Error(c, http.StatusNotFound, "strategy not found")
			return
		}
		if errors.Is(err, fund.ErrFundNotFound) {
			dto.Error(c, http.StatusNotFound, "fund not found")
			return
		}
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Created(c, gin.H{
		"strategy_id":   id,
		"fund_code":     req.FundCode,
		"strategy_name": st.Name,
	})
}

// unbindStrategy deletes a binding between a strategy and a fund.
func (h *StrategyHandler) unbindStrategy(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	code := c.Param("code")
	if err := h.strategyUC.DeleteBinding(c.Request.Context(), id, shared.FundCode(code)); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, nil)
}

// listBindings returns all bindings for a given strategy.
func (h *StrategyHandler) listBindings(c *gin.Context) {
	id, ok := parseStrategyID(c)
	if !ok {
		return
	}

	bindings, err := h.strategyUC.GetBindingsForStrategy(c.Request.Context(), id)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.StrategyBindingsToDTO(bindings))
}
