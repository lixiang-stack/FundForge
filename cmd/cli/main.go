package main

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/spf13/cobra"

	"github.com/lixiang/fundforge/internal/adapter/collector"
	"github.com/lixiang/fundforge/internal/adapter/persistence/postgres"
	"github.com/lixiang/fundforge/internal/application"
	"github.com/lixiang/fundforge/internal/config"
	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
	"github.com/lixiang/fundforge/internal/infra/logger"
)

type cliApp struct {
	db           *postgres.DB
	cfg          *config.Config
	fundUC       *application.FundUseCase
	dataSyncUC   *application.DataSyncUseCase
	analysisUC   *application.AnalysisUseCase
	alertUC      *application.AlertUseCase
	templateRepo strategy.StrategyTemplateRepository
	bindingRepo  strategy.StrategyBindingRepository
}

var app cliApp

func main() {
	rootCmd := &cobra.Command{
		Use:   "client",
		Short: "CLIENT - Fund investment research and portfolio decision support management tool",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			if isMetaCommand(cmd) {
				return nil
			}
			return initApp()
		},
		PersistentPostRun: func(cmd *cobra.Command, args []string) {
			if app.db != nil {
				app.db.Close()
			}
		},
	}

	rootCmd.AddCommand(fundCmd(), syncCmd(), strategyCmd(), analyzeCmd(), alertCmd(), migrateCmd())

	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

// isMetaCommand reports whether cmd belongs to Cobra's built-in meta
// commands (help, completion and its subcommands). These should not
// trigger database initialization.
func isMetaCommand(cmd *cobra.Command) bool {
	for c := cmd; c != nil; c = c.Parent() {
		switch c.Name() {
		case "help", "completion":
			return true
		}
	}
	return false
}

func fundCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "fund", Short: "Fund management"}

	cmd.AddCommand(&cobra.Command{
		Use: "subscribe [code]", Short: "Subscribe to a fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			f, err := app.fundUC.Subscribe(context.Background(), args[0])
			if err != nil {
				return err
			}
			fmt.Printf("Subscribed: %s| %s| (%s)\n", f.Code, f.Name, f.FundType)
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "unsubscribe [code]", Short: "Unsubscribe from a fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := app.fundUC.Unsubscribe(context.Background(), args[0]); err != nil {
				return err
			}
			fmt.Printf("Unsubscribed: %s\n", args[0])
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "list", Short: "List subscribed funds",
		RunE: func(cmd *cobra.Command, args []string) error {
			funds, err := app.fundUC.ListSubscribed(context.Background())
			if err != nil {
				return err
			}
			if len(funds) == 0 {
				fmt.Println("No subscribed funds.")
				return nil
			}
			fmt.Printf("%-8s %-30s %-14s %-12s %s\n", "Code", "Name", "Type", "Last NAV", "Status")
			fmt.Println("-------- ------------------------------ -------------- ------------ ----------")
			for _, f := range funds {
				lastNAV := "-"
				if f.LastNAVDate != nil {
					lastNAV = f.LastNAVDate.Format("2006-01-02")
				}
				fmt.Printf("%-8s %-30s %-14s %-12s %s\n",
					f.Code, truncate(f.Name, 28), truncate(f.FundType, 12), lastNAV, f.Status)
			}
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "search [query]", Short: "Search funds by code/name/pinyin", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			funds, err := app.fundUC.Search(context.Background(), args[0], 20)
			if err != nil {
				return err
			}
			for _, f := range funds {
				fmt.Printf("%-8s %-30s %s\n", f.Code, f.Name, f.FundType)
			}
			return nil
		},
	})

	return cmd
}

func syncCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "sync", Short: "Data synchronization"}

	cmd.AddCommand(&cobra.Command{
		Use: "calendar", Short: "Sync trade calendar",
		RunE: func(cmd *cobra.Command, args []string) error {
			return app.dataSyncUC.SyncCalendar(context.Background())
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use: "nav [code]", Short: "Fetch historical NAV for a fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			inserted, err := app.dataSyncUC.FetchHistoricalNAV(context.Background(), args[0])
			if err != nil {
				return err
			}
			fmt.Printf("Fetched %d NAV records for %s\n", inserted, args[0])
			return nil
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use: "update", Short: "Incremental NAV update for all subscribed funds",
		RunE: func(cmd *cobra.Command, args []string) error {
			return app.dataSyncUC.IncrementalUpdate(context.Background())
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use: "dividends", Short: "Sync dividends and splits",
		RunE: func(cmd *cobra.Command, args []string) error {
			return app.dataSyncUC.SyncDividendsAndSplits(context.Background())
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use: "managers", Short: "Detect fund manager changes",
		RunE: func(cmd *cobra.Command, args []string) error {
			return app.dataSyncUC.DetectManagerChanges(context.Background())
		},
	})

	return cmd
}

func strategyCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "strategy", Short: "Strategy management"}

	cmd.AddCommand(&cobra.Command{
		Use: "list", Short: "List all strategies",
		RunE: func(cmd *cobra.Command, args []string) error {
			strategies, err := app.templateRepo.ListAll(context.Background())
			if err != nil {
				return err
			}
			if len(strategies) == 0 {
				fmt.Println("No strategies found.")
				return nil
			}
			fmt.Printf("%-4s %-20s %-10s %-8s %-8s %-8s %s\n", "ID", "Name", "Severity", "Cooldown", "Enabled", "Logic", "Conditions")
			fmt.Println("---- -------------------- ---------- -------- -------- -------- ----------")
			for _, s := range strategies {
				fmt.Printf("%-4d %-20s %-10s %-8d %-8v %-8s %d conditions\n",
					s.ID, truncate(s.Name, 18), s.Severity, s.CooldownDays, s.IsEnabled, s.Logic, len(s.Conditions))
			}
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "bind [strategy_id] [fund_code]", Short: "Bind strategy to fund", Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			sid, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid strategy ID: %w", err)
			}
			if err := app.bindingRepo.SaveBinding(context.Background(), sid, shared.FundCode(args[1])); err != nil {
				return err
			}
			fmt.Printf("Bound strategy %d to fund %s\n", sid, args[1])
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "unbind [strategy_id] [fund_code]", Short: "Unbind strategy from fund", Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			sid, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid strategy ID: %w", err)
			}
			return app.bindingRepo.DeleteBinding(context.Background(), sid, shared.FundCode(args[1]))
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "bindings [fund_code]", Short: "List bindings for a fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			bindings, err := app.bindingRepo.GetBindingsForFund(context.Background(), shared.FundCode(args[0]))
			if err != nil {
				return err
			}
			if len(bindings) == 0 {
				fmt.Println("No strategy bindings for this fund.")
				return nil
			}
			for _, b := range bindings {
				fmt.Printf("Strategy ID: %d  Fund: %s  Enabled: %v\n", b.StrategyID, b.FundCode, b.IsEnabled)
			}
			return nil
		},
	})

	return cmd
}

func analyzeCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "analyze", Short: "Strategy analysis"}

	cmd.AddCommand(&cobra.Command{
		Use: "all", Short: "Run full analysis on all subscribed funds",
		RunE: func(cmd *cobra.Command, args []string) error {
			result, err := app.analysisUC.RunFullAnalysis(context.Background())
			if err != nil {
				return err
			}
			fmt.Printf("Analysis complete: %d funds, %d strategies, %d alerts triggered, %d recovered, %d errors\n",
				result.FundsAnalyzed, result.StrategiesRun, result.AlertsTriggered, result.AlertsRecovered, result.Errors)
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "run [code]", Short: "Run analysis on a single fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			result, err := app.analysisUC.RunIncrementalAnalysis(context.Background(), []string{args[0]})
			if err != nil {
				return err
			}
			fmt.Printf("Analysis for %s: %d strategies, %d alerts triggered, %d recovered\n",
				args[0], result.StrategiesRun, result.AlertsTriggered, result.AlertsRecovered)
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "indicators [code]", Short: "Compute and display indicators for a fund", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			snapshot, err := app.analysisUC.ComputeIndicators(context.Background(), args[0])
			if err != nil {
				return err
			}
			if snapshot == nil {
				fmt.Println("Insufficient data to compute indicators.")
				return nil
			}
			fmt.Printf("Indicators for %s:\n", args[0])
			for k, v := range snapshot {
				fmt.Printf("  %-25s %.4f\n", k, v)
			}
			return nil
		},
	})

	return cmd
}

func alertCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "alert", Short: "Alert management"}

	cmd.AddCommand(&cobra.Command{
		Use: "list", Short: "List active alerts",
		RunE: func(cmd *cobra.Command, args []string) error {
			alerts, err := app.alertUC.ListActive(context.Background())
			if err != nil {
				return err
			}
			if len(alerts) == 0 {
				fmt.Println("No active alerts.")
				return nil
			}
			fmt.Printf("%-4s %-8s %-10s %-10s %-12s %s\n", "ID", "Fund", "Severity", "Status", "Date", "Message")
			fmt.Println("---- -------- ---------- ---------- ------------ ----------------------------------------")
			for _, a := range alerts {
				fmt.Printf("%-4d %-8s %-10s %-10s %-12s %s\n",
					a.ID, a.FundCode, a.Severity, a.Status, a.DataDate.Format("2006-01-02"), truncate(a.Message, 40))
			}
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "confirm [id]", Short: "Confirm an alert", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid alert ID: %w", err)
			}
			if err := app.alertUC.ConfirmAlert(context.Background(), id); err != nil {
				return err
			}
			fmt.Printf("Alert %d confirmed.\n", id)
			return nil
		},
	})

	cmd.AddCommand(&cobra.Command{
		Use: "ignore [id]", Short: "Ignore an alert", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid alert ID: %w", err)
			}
			if err := app.alertUC.IgnoreAlert(context.Background(), id); err != nil {
				return err
			}
			fmt.Printf("Alert %d ignored.\n", id)
			return nil
		},
	})

	return cmd
}

func migrateCmd() *cobra.Command {
	return &cobra.Command{
		Use: "migrate", Short: "Run database migrations",
		RunE: func(cmd *cobra.Command, args []string) error {
			return app.db.RunMigrations(app.cfg.DatabaseURL, app.cfg.MigrationsPath)
		},
	}
}

func initApp() error {
	app.cfg = config.Load()
	log := logger.New(app.cfg.GinMode)
	ctx := context.Background()

	db, err := postgres.New(ctx, app.cfg.DatabaseURL, log, app.cfg.DBMaxConns, app.cfg.DBMinConns)
	if err != nil {
		return fmt.Errorf("database: %w", err)
	}
	app.db = db

	fundRepo := postgres.NewFundRepo(db.Pool)
	navRepo := postgres.NewNAVRepo(db.Pool)
	calendarRepo := postgres.NewCalendarRepo(db.Pool)
	benchmarkRepo := postgres.NewBenchmarkRepo(db.Pool)
	sRepo := postgres.NewStrategyRepo(db.Pool)
	alertRepo := postgres.NewAlertRepo(db.Pool)
	app.templateRepo = sRepo
	app.bindingRepo = sRepo

	provider := collector.NewClient(app.cfg.CollectorBaseURL, log)

	alertService := alert.NewService(alertRepo)

	app.fundUC = application.NewFundUseCase(fundRepo, navRepo, provider, log)
	app.dataSyncUC = application.NewDataSyncUseCase(
		fundRepo, fundRepo, navRepo, calendarRepo, benchmarkRepo,
		provider, provider, provider, log,
		time.Duration(app.cfg.FetchIntervalMs)*time.Millisecond,
	)
	app.analysisUC = application.NewAnalysisUseCase(
		fundRepo, navRepo, benchmarkRepo, sRepo, sRepo, alertService, log,
	)
	app.alertUC = application.NewAlertUseCase(alertRepo, log)

	return nil
}

func truncate(s string, maxLen int) string {
	runes := []rune(s)
	if len(runes) <= maxLen {
		return s
	}
	return string(runes[:maxLen-1]) + "…"
}
