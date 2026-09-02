package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/lixiang/fundforge/internal/adapter/collector"
	adapterhttp "github.com/lixiang/fundforge/internal/adapter/http"
	"github.com/lixiang/fundforge/internal/adapter/persistence/postgres"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/config"
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/infra/logger"
)

func main() {
	cfg := config.Load()
	log := logger.New(cfg.GinMode)
	ctx := context.Background()

	// 1. Database
	db, err := postgres.New(ctx, cfg.DatabaseURL, log, cfg.DBMaxConns, cfg.DBMinConns)
	if err != nil {
		log.Fatalw("failed to connect to database", "error", err)
	}
	defer db.Close()

	if err := db.RunMigrations(cfg.DatabaseURL, "file://migrations"); err != nil {
		log.Fatalw("failed to run migrations", "error", err)
	}

	// 2. Repositories
	fundRepo := postgres.NewFundRepo(db.Pool)
	navRepo := postgres.NewNAVRepo(db.Pool)
	benchmarkRepo := postgres.NewBenchmarkRepo(db.Pool)
	strategyRepo := postgres.NewStrategyRepo(db.Pool)
	alertRepo := postgres.NewAlertRepo(db.Pool)

	// 3. External adapters
	provider := collector.NewClient(cfg.CollectorBaseURL, log)

	// 4. Domain services
	alertService := alert.NewService(alertRepo)

	// 5. Application use cases
	fundUC := application.NewFundUseCase(fundRepo, navRepo, provider, log)
	analysisUC := application.NewAnalysisUseCase(
		fundRepo, navRepo, benchmarkRepo, strategyRepo, strategyRepo, alertService, log,
	)
	alertUC := application.NewAlertUseCase(alertRepo, log)
	strategyUC := application.NewStrategyUseCase(fundRepo, strategyRepo, strategyRepo)

	// 6. HTTP Server (Gin)
	router := adapterhttp.NewRouter(adapterhttp.Deps{
		FundUC:     fundUC,
		AnalysisUC: analysisUC,
		AlertUC:    alertUC,
		StrategyUC: strategyUC,
	})

	srv := &http.Server{
		Addr:    ":" + cfg.ServerPort,
		Handler: router,
	}

	go func() {
		log.Infow("HTTP server starting", "port", cfg.ServerPort)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalw("HTTP server error", "error", err)
		}
	}()

	// 8. Banner + graceful shutdown
	fmt.Println("========================================")
	fmt.Println("  FundForge - An AI Agent for fund investment research and portfolio decision support")
	fmt.Println("========================================")
	log.Infow("server started",
		"port", cfg.ServerPort,
		"collector", cfg.CollectorBaseURL,
	)

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info("shutting down...")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Warnw("HTTP server shutdown error", "error", err)
	}
	db.Close()
	log.Info("server stopped")
}