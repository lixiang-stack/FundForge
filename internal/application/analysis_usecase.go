package application

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/alert"
	"github.com/lixiang/fundforge/internal/domain/benchmark"
	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"github.com/lixiang/fundforge/internal/domain/strategy"
	"go.uber.org/zap"
)

// AnalysisUseCase orchestrates strategy evaluation workflows.
type AnalysisUseCase struct {
	fundRepo      fund.FundRepository
	navRepo       nav.Repository
	benchmarkRepo benchmark.Repository
	templateRepo  strategy.StrategyTemplateRepository
	bindingRepo   strategy.StrategyBindingRepository
	alertService  *alert.Service
	logger        *zap.SugaredLogger
}

func NewAnalysisUseCase(
	fundRepo fund.FundRepository,
	navRepo nav.Repository,
	benchmarkRepo benchmark.Repository,
	templateRepo strategy.StrategyTemplateRepository,
	bindingRepo strategy.StrategyBindingRepository,
	alertService *alert.Service,
	logger *zap.SugaredLogger,
) *AnalysisUseCase {
	return &AnalysisUseCase{
		fundRepo:      fundRepo,
		navRepo:       navRepo,
		benchmarkRepo: benchmarkRepo,
		templateRepo:  templateRepo,
		bindingRepo:   bindingRepo,
		alertService:  alertService,
		logger:        logger,
	}
}

// AnalysisResult summarizes one analysis run.
type AnalysisResult struct {
	FundsAnalyzed   int
	StrategiesRun   int
	AlertsTriggered int
	AlertsRecovered int
	Errors          int
}

// RunFullAnalysis evaluates all enabled strategies for all subscribed funds.
func (uc *AnalysisUseCase) RunFullAnalysis(ctx context.Context) (*AnalysisResult, error) {
	funds, err := uc.fundRepo.ListSubscribed(ctx)
	if err != nil {
		return nil, fmt.Errorf("AnalysisUseCase.RunFullAnalysis: %w", err)
	}

	result := &AnalysisResult{}
	for _, f := range funds {
		r, err := uc.analyzeFund(ctx, f)
		if err != nil {
			uc.logger.Warnw("analysis failed for fund", "code", f.Code, "error", err)
			result.Errors++
			continue
		}
		result.FundsAnalyzed++
		result.StrategiesRun += r.StrategiesRun
		result.AlertsTriggered += r.AlertsTriggered
		result.AlertsRecovered += r.AlertsRecovered
	}

	uc.logger.Infow("full analysis complete", "result", result)
	return result, nil
}

// RunIncrementalAnalysis evaluates strategies only for specified funds.
func (uc *AnalysisUseCase) RunIncrementalAnalysis(ctx context.Context, fundCodes []string) (*AnalysisResult, error) {
	result := &AnalysisResult{}
	for _, code := range fundCodes {
		f, err := uc.fundRepo.GetByCode(ctx, fund.FundCode(code))
		if err != nil || f == nil {
			uc.logger.Warnw("fund not found for incremental analysis", "code", code)
			result.Errors++
			continue
		}
		r, err := uc.analyzeFund(ctx, f)
		if err != nil {
			uc.logger.Warnw("incremental analysis failed", "code", code, "error", err)
			result.Errors++
			continue
		}
		result.FundsAnalyzed++
		result.StrategiesRun += r.StrategiesRun
		result.AlertsTriggered += r.AlertsTriggered
		result.AlertsRecovered += r.AlertsRecovered
	}
	return result, nil
}

// analyzeFund runs all bound strategies against a single fund.
func (uc *AnalysisUseCase) analyzeFund(ctx context.Context, f *fund.Fund) (*AnalysisResult, error) {
	result := &AnalysisResult{}

	// 1. Compute indicators
	snapshot, err := uc.ComputeIndicators(ctx, string(f.Code))
	if err != nil {
		return nil, fmt.Errorf("compute indicators: %w", err)
	}
	if len(snapshot) == 0 {
		return result, nil // no data, skip
	}

	// 2. Get bound strategies
	bindings, err := uc.bindingRepo.GetBindingsForFund(ctx, f.Code)
	if err != nil {
		return nil, fmt.Errorf("get bindings: %w", err)
	}

	dataDate := time.Now()
	if f.LastNAVDate != nil {
		dataDate = *f.LastNAVDate
	}

	// 3. Evaluate each strategy
	for _, binding := range bindings {
		tmpl, err := uc.templateRepo.GetByID(ctx, binding.StrategyID)
		if err != nil || tmpl == nil || !tmpl.IsEnabled {
			continue
		}
		result.StrategiesRun++

		triggered, detail := tmpl.Evaluate(snapshot)

		if triggered {
			// Try to trigger alert (respects cooldown)
			condJSON, _ := json.Marshal(tmpl.Conditions)
			message := fmt.Sprintf("%s: %s — %s", f.Name, tmpl.Name, detail)
			a, err := uc.alertService.TryTrigger(ctx, f.Code, tmpl.ID,
				string(tmpl.Severity), dataDate, snapshot, condJSON, tmpl.CooldownDays, message)
			if err != nil {
				uc.logger.Warnw("alert trigger error", "code", f.Code, "strategy", tmpl.Name, "error", err)
				continue
			}
			if a != nil {
				result.AlertsTriggered++
			}
		} else {
			// Check if we should recover any active alerts
			recovered, err := uc.alertService.RecoverIfActive(ctx, tmpl.ID, f.Code)
			if err != nil {
				uc.logger.Warnw("alert recovery error", "code", f.Code, "strategy", tmpl.Name, "error", err)
				continue
			}
			result.AlertsRecovered += len(recovered)
		}
	}

	return result, nil
}

// ComputeIndicators calculates the full IndicatorSnapshot for a fund.
func (uc *AnalysisUseCase) ComputeIndicators(ctx context.Context, fundCode string) (strategy.IndicatorSnapshot, error) {
	// Get NAV history (last 2 years to cover all rolling windows)
	end := time.Now()
	start := end.AddDate(-2, 0, 0)
	navs, err := uc.navRepo.GetByFundCode(ctx, shared.FundCode(fundCode), start, end)
	if err != nil {
		return nil, fmt.Errorf("get NAV data: %w", err)
	}
	if len(navs) < 20 {
		return nil, nil // insufficient data
	}

	fundBars := toPricePoints(nav.NAVsToPriceBars(navs))

	// Try to get benchmark data for Beta/ExcessReturn
	var benchBars []strategy.PricePoint
	f, _ := uc.fundRepo.GetByCode(ctx, fund.FundCode(fundCode))
	if f != nil {
		benchIdx, _ := uc.benchmarkRepo.GetDefaultForFundType(ctx, f.FundType)
		if benchIdx != nil {
			benchData, _ := uc.benchmarkRepo.GetDailyData(ctx, benchIdx.IndexCode, start, end)
			for _, d := range benchData {
				benchBars = append(benchBars, strategy.PricePoint{Date: d.TradeDate, Close: d.ClosePrice})
			}
		}
	}

	snapshot := strategy.ComputeSnapshot(fundBars, benchBars, 0.015) // 1.5% risk-free rate
	return snapshot, nil
}

func toPricePoints(bars []nav.PriceBar) []strategy.PricePoint {
	pts := make([]strategy.PricePoint, len(bars))
	for i, b := range bars {
		pts[i] = strategy.PricePoint{Date: b.Date, Close: b.Close}
	}
	return pts
}
