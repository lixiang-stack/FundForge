package http

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/adapter/http/dto"
	"github.com/lixiang/fundforge/internal/application"
)

// FundHandler handles fund-related HTTP requests.
type FundHandler struct {
	fundUC     *application.FundUseCase
	analysisUC *application.AnalysisUseCase
}

// NewFundHandler creates a new FundHandler.
func NewFundHandler(
	fundUC *application.FundUseCase,
	analysisUC *application.AnalysisUseCase,
) *FundHandler {
	return &FundHandler{
		fundUC:     fundUC,
		analysisUC: analysisUC,
	}
}

// RegisterFundRoutes registers fund-related routes on the given router group.
func RegisterFundRoutes(rg *gin.RouterGroup, h *FundHandler) {
	funds := rg.Group("/funds")
	{
		funds.GET("", h.listFunds)
		funds.GET("/all", h.listAllFunds)
		funds.POST("", h.subscribeFund)
		funds.POST("/add", h.addFund)
		funds.GET("/search", h.searchFunds)
		funds.GET("/:code", h.getFundDetail)
		funds.DELETE("/:code", h.unsubscribeFund)
		funds.DELETE("/:code/remove", h.removeFund)
		funds.GET("/:code/nav", h.getFundNAV)
	}
}

// listFunds returns all subscribed funds.
func (h *FundHandler) listFunds(c *gin.Context) {
	funds, err := h.fundUC.ListSubscribed(c.Request.Context())
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.FundsToDTO(funds))
}

// listAllFunds returns all funds (subscribed + unsubscribed) for the watchlist.
func (h *FundHandler) listAllFunds(c *gin.Context) {
	funds, err := h.fundUC.ListAll(c.Request.Context())
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.FundsToDTO(funds))
}

// subscribeFund subscribes to a new fund.
func (h *FundHandler) subscribeFund(c *gin.Context) {
	var req dto.SubscribeFundReq
	if err := c.ShouldBindJSON(&req); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}

	f, err := h.fundUC.Subscribe(c.Request.Context(), req.FundCode)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Created(c, dto.FundToDTO(f))
}

// addFund adds a fund to the watchlist without subscribing.
func (h *FundHandler) addFund(c *gin.Context) {
	var req dto.SubscribeFundReq
	if err := c.ShouldBindJSON(&req); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}

	f, err := h.fundUC.AddToWatchlist(c.Request.Context(), req.FundCode)
	if err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}
	dto.Created(c, dto.FundToDTO(f))
}

// unsubscribeFund unsubscribes from a fund.
func (h *FundHandler) unsubscribeFund(c *gin.Context) {
	code := c.Param("code")
	if err := h.fundUC.Unsubscribe(c.Request.Context(), code); err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, nil)
}

// removeFund permanently deletes a fund from the platform.
func (h *FundHandler) removeFund(c *gin.Context) {
	code := c.Param("code")
	if err := h.fundUC.Remove(c.Request.Context(), code); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}
	dto.Success(c, nil)
}

// getFundDetail returns fund detail with computed indicators and latest NAV.
func (h *FundHandler) getFundDetail(c *gin.Context) {
	code := c.Param("code")
	ctx := c.Request.Context()

	// Compute indicators for the fund.
	indicators, err := h.analysisUC.ComputeIndicators(ctx, code)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}

	// Get the latest NAV.
	latestNAV, err := h.fundUC.GetNAV(ctx, code)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}

	result := gin.H{
		"fund_code":  code,
		"indicators": indicators,
		"latest_nav": dto.NAVToDTO(latestNAV),
	}
	dto.Success(c, result)
}

// getFundNAV returns NAV history for a fund within an optional date range.
func (h *FundHandler) getFundNAV(c *gin.Context) {
	code := c.Param("code")

	var q dto.NAVQuery
	if err := c.ShouldBindQuery(&q); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}

	// Default date range: last 1 year.
	end := time.Now()
	start := end.AddDate(-1, 0, 0)

	if q.Start != "" {
		parsed, err := time.Parse("2006-01-02", q.Start)
		if err != nil {
			dto.Error(c, http.StatusBadRequest, "invalid start date format, expected YYYY-MM-DD")
			return
		}
		start = parsed
	}
	if q.End != "" {
		parsed, err := time.Parse("2006-01-02", q.End)
		if err != nil {
			dto.Error(c, http.StatusBadRequest, "invalid end date format, expected YYYY-MM-DD")
			return
		}
		end = parsed
	}

	navs, err := h.fundUC.GetNAVHistory(c.Request.Context(), code, start, end)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.NAVsToDTO(navs))
}

// searchFunds searches for funds by query string.
func (h *FundHandler) searchFunds(c *gin.Context) {
	var q dto.SearchQuery
	if err := c.ShouldBindQuery(&q); err != nil {
		dto.Error(c, http.StatusBadRequest, err.Error())
		return
	}

	limit := q.Limit
	if limit <= 0 {
		limit = 20
	}

	funds, err := h.fundUC.Search(c.Request.Context(), q.Q, limit)
	if err != nil {
		dto.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	dto.Success(c, dto.FundsToDTO(funds))
}
