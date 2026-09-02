package http

import (
	"github.com/gin-gonic/gin"
	"github.com/lixiang/fundforge/internal/application"
)

type Deps struct {
	FundUC     *application.FundUseCase
	AnalysisUC *application.AnalysisUseCase
	AlertUC    *application.AlertUseCase
	StrategyUC *application.StrategyUseCase
}

func NewRouter(deps Deps) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(gin.Logger())

	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	fundHandler := NewFundHandler(deps.FundUC, deps.AnalysisUC)
	RegisterFundRoutes(r.Group("/api/funds"), fundHandler)

	strategyHandler := NewStrategyHandler(deps.StrategyUC)
	RegisterStrategyRoutes(r.Group("/api/strategies"), strategyHandler)

	alertHandler := NewAlertHandler(deps.AlertUC)
	RegisterAlertRoutes(r.Group("/api/alerts"), alertHandler)

	return r
}
