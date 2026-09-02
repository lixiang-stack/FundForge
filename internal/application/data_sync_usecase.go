package application

import (
	"context"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/benchmark"
	"github.com/lixiang/fundforge/internal/domain/calendar"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"go.uber.org/zap"
)

// DataSyncUseCase orchestrates all data synchronization workflows
// (calendar, NAV history, incremental NAV updates, dividends/splits,
// manager change detection).
type DataSyncUseCase struct {
	fundRepo      fund.FundRepository
	corpRepo      fund.CorporateActionRepository
	navRepo       nav.Repository
	calendarRepo  calendar.Repository
	benchmarkRepo benchmark.Repository
	fundProvider  marketdata.FundProvider
	corpProvider  marketdata.CorporateActionProvider
	toolProvider  marketdata.TradeCalendarProvider
	logger        *zap.SugaredLogger
	fetchInterval time.Duration
}

func NewDataSyncUseCase(
	fundRepo fund.FundRepository,
	corpRepo fund.CorporateActionRepository,
	navRepo nav.Repository,
	calendarRepo calendar.Repository,
	benchmarkRepo benchmark.Repository,
	fundProvider marketdata.FundProvider,
	corpProvider marketdata.CorporateActionProvider,
	toolProvider marketdata.TradeCalendarProvider,
	logger *zap.SugaredLogger,
	fetchInterval time.Duration,
) *DataSyncUseCase {
	return &DataSyncUseCase{
		fundRepo:      fundRepo,
		corpRepo:      corpRepo,
		navRepo:       navRepo,
		calendarRepo:  calendarRepo,
		benchmarkRepo: benchmarkRepo,
		fundProvider:  fundProvider,
		corpProvider:  corpProvider,
		toolProvider:  toolProvider,
		logger:        logger,
		fetchInterval: fetchInterval,
	}
}

// ---------- Calendar ----------

// SyncCalendar fetches the full A-share trading calendar and upserts it.
func (uc *DataSyncUseCase) SyncCalendar(ctx context.Context) error {
	dates, err := uc.toolProvider.FetchTradeCalendar(ctx)
	if err != nil {
		return err
	}

	tradeDates := make([]calendar.TradeDate, len(dates))
	for i, d := range dates {
		tradeDates[i] = calendar.TradeDate{Date: d, IsTradingDay: true}
	}

	if err := uc.calendarRepo.BatchSave(ctx, tradeDates); err != nil {
		return err
	}

	uc.logger.Infow("calendar synced", "dates", len(tradeDates))
	return nil
}

// ---------- Historical NAV ----------

// FetchHistoricalNAV fetches full NAV history for a single fund.
func (uc *DataSyncUseCase) FetchHistoricalNAV(ctx context.Context, code string) (int, error) {
	// Fetch unit NAV
	unitNAVs, err := uc.fundProvider.FetchFundNAV(ctx, code, "单位净值走势", "成立来")
	if err != nil {
		return 0, fmt.Errorf("fetch unit NAV for %s: %w", code, err)
	}

	// Fetch accumulated NAV
	accNAVs, err := uc.fundProvider.FetchFundNAV(ctx, code, "累计净值走势", "成立来")
	if err != nil {
		uc.logger.Warnw("failed to fetch acc NAV, proceeding with unit NAV only",
			"code", code, "error", err)
	}

	// Merge unit + accumulated
	merged := mergeNAVs(unitNAVs, accNAVs, code)

	// Batch save
	inserted, err := uc.navRepo.BatchSave(ctx, merged)
	if err != nil {
		return 0, fmt.Errorf("save NAV for %s: %w", code, err)
	}

	// Update fund fetch status
	if len(merged) > 0 {
		latest := merged[len(merged)-1]
		if err := uc.fundRepo.UpdateFetchStatus(ctx, fund.FundCode(code), latest.Date, time.Now()); err != nil {
			uc.logger.Warnw("failed to update fetch status", "code", code, "error", err)
		}
	}

	uc.logger.Infow("historical NAV fetched", "code", code, "total", len(merged), "inserted", inserted)
	return inserted, nil
}

// ---------- Incremental Update ----------

// IncrementalUpdate fetches latest NAV for all subscribed funds.
func (uc *DataSyncUseCase) IncrementalUpdate(ctx context.Context) error {
	funds, err := uc.fundRepo.ListSubscribed(ctx)
	if err != nil {
		return err
	}

	var totalInserted int
	var errCount int

	for _, f := range funds {
		if interval := uc.fetchInterval; interval > 0 {
			time.Sleep(interval)
		}

		period := "近1年"
		if f.LastNAVDate == nil || !f.InitialFetchDone {
			period = "成立来"
		}

		navs, err := uc.fundProvider.FetchFundNAV(ctx, string(f.Code), "单位净值走势", period)
		if err != nil {
			uc.logger.Warnw("incremental fetch failed", "code", f.Code, "error", err)
			errCount++
			continue
		}

		inserted, err := uc.navRepo.BatchSave(ctx, navs)
		if err != nil {
			uc.logger.Warnw("incremental save failed", "code", f.Code, "error", err)
			errCount++
			continue
		}

		totalInserted += inserted
		if len(navs) > 0 {
			if err := uc.fundRepo.UpdateFetchStatus(ctx, f.Code, navs[len(navs)-1].Date, time.Now()); err != nil {
				uc.logger.Warnw("failed to update fetch status", "code", f.Code, "error", err)
			}
		}
	}

	uc.logger.Infow("incremental update done",
		"funds", len(funds), "inserted", totalInserted, "errors", errCount)
	return nil
}

// ---------- Dividends & Splits ----------

// SyncDividendsAndSplits fetches all dividends/splits and saves for subscribed funds.
func (uc *DataSyncUseCase) SyncDividendsAndSplits(ctx context.Context) error {
	// Get subscribed fund codes for filtering.
	funds, err := uc.fundRepo.ListSubscribed(ctx)
	if err != nil {
		return err
	}
	subscribedCodes := make(map[string]bool, len(funds))
	for _, f := range funds {
		subscribedCodes[string(f.Code)] = true
	}

	// Dividends
	dividendCount := 0
	rawDividends, err := uc.corpProvider.FetchDividends(ctx)
	if err != nil {
		uc.logger.Warnw("failed to fetch dividends", "error", err)
	} else {
		var filtered []fund.Dividend
		for _, d := range rawDividends {
			if subscribedCodes[d.FundCode] {
				filtered = append(filtered, fund.Dividend{
					FundCode: fund.FundCode(d.FundCode), FundName: d.FundName,
					RecordDate: d.RecordDate, ExDate: d.ExDate,
					DividendPerUnit: d.DividendPerUnit, PayDate: d.PayDate,
					FetchedAt: time.Now(),
				})
			}
		}
		if err := uc.corpRepo.SaveDividends(ctx, filtered); err != nil {
			uc.logger.Warnw("save dividends failed", "error", err)
		}
		dividendCount = len(filtered)
	}

	// Splits
	splitCount := 0
	rawSplits, err := uc.corpProvider.FetchSplits(ctx)
	if err != nil {
		uc.logger.Warnw("failed to fetch splits", "error", err)
	} else {
		var filtered []fund.Split
		for _, s := range rawSplits {
			if subscribedCodes[s.FundCode] {
				filtered = append(filtered, fund.Split{
					FundCode: fund.FundCode(s.FundCode), FundName: s.FundName,
					SplitDate: s.SplitDate, SplitType: s.SplitType,
					SplitRatio: s.SplitRatio, FetchedAt: time.Now(),
				})
			}
		}
		if err := uc.corpRepo.SaveSplits(ctx, filtered); err != nil {
			uc.logger.Warnw("save splits failed", "error", err)
		}
		splitCount = len(filtered)
	}

	uc.logger.Infow("dividends & splits synced", "dividends", dividendCount, "splits", splitCount)
	return nil
}

// ---------- Manager Change Detection ----------

// DetectManagerChanges compares current fund manager with stored value.
func (uc *DataSyncUseCase) DetectManagerChanges(ctx context.Context) error {
	funds, err := uc.fundRepo.ListSubscribed(ctx)
	if err != nil {
		return err
	}

	var changes int
	for _, f := range funds {
		if interval := uc.fetchInterval; interval > 0 {
			time.Sleep(interval)
		}

		detail, err := uc.fundProvider.FetchFundDetail(ctx, string(f.Code))
		if err != nil {
			uc.logger.Warnw("failed to fetch detail for manager check", "code", f.Code, "error", err)
			continue
		}

		mc, changed, err := fund.DetectManagerChange(f, detail.Manager)
		if err != nil {
			uc.logger.Warnw("manager change detection error", "code", f.Code, "error", err)
			continue
		}
		if changed && mc != nil {
			changes++
			uc.logger.Infow("manager change detected",
				"code", f.Code, "from", mc.PreviousManager, "to", mc.CurrentManager)
		}
	}

	return nil
}

// ---------- Benchmark Data ----------

// SyncBenchmarkData is a placeholder for Phase 1 (benchmark data source TBD).
func (uc *DataSyncUseCase) SyncBenchmarkData(ctx context.Context) error {
	uc.logger.Info("SyncBenchmarkData: not yet implemented in Phase 1")
	return nil
}

// ---------- NAV merge helper ----------

// mergeNAVs combines unit NAV and accumulated NAV by date.
func mergeNAVs(unitNAVs, accNAVs []nav.NAV, code string) []nav.NAV {
	accMap := make(map[string]float64, len(accNAVs))
	for _, n := range accNAVs {
		accMap[n.Date.Format("2006-01-02")] = n.AccNAV
	}

	now := time.Now()
	for i := range unitNAVs {
		unitNAVs[i].FundCode = shared.FundCode(code)
		unitNAVs[i].FetchedAt = now
		if accVal, ok := accMap[unitNAVs[i].Date.Format("2006-01-02")]; ok {
			unitNAVs[i].AccNAV = accVal
		}
	}
	return unitNAVs
}
