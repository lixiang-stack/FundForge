package application

import (
	"context"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/fund"
	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/domain/shared"
	"go.uber.org/zap"
)

// FundUseCase orchestrates fund subscription workflows.
type FundUseCase struct {
	fundRepo     fund.FundRepository
	navRepo      nav.Repository
	fundProvider marketdata.FundProvider
	logger       *zap.SugaredLogger
}

func NewFundUseCase(
	fundRepo fund.FundRepository,
	navRepo nav.Repository,
	fundProvider marketdata.FundProvider,
	logger *zap.SugaredLogger,
) *FundUseCase {
	return &FundUseCase{
		fundRepo:     fundRepo,
		navRepo:      navRepo,
		fundProvider: fundProvider,
		logger:       logger,
	}
}

// Subscribe validates the fund code, fetches metadata from collector, and saves.
func (uc *FundUseCase) Subscribe(ctx context.Context, code string) (*fund.Fund, error) {
	fc := fund.FundCode(code)
	if err := fc.Validate(); err != nil {
		return nil, fmt.Errorf("invalid fund code: %w", err)
	}

	existing, err := uc.fundRepo.GetByCode(ctx, fc)
	if err != nil {
		return nil, fmt.Errorf("get fund by code: %w", err)
	}

	// Handle re-subscribe: transition existing unsubscribed fund back to subscribed.
	if existing != nil {
		if existing.Status == fund.Subscribed {
			return nil, fund.ErrAlreadySubscribed
		}
		// Re-subscribe an unsubscribed fund.
		if err := existing.Subscribe(); err != nil {
			return nil, err
		}
		if err := uc.fundRepo.Save(ctx, existing); err != nil {
			return nil, fmt.Errorf("save fund: %w", err)
		}
		return existing, nil
	}

	// Brand-new fund – create in subscribed state.
	now := time.Now()
	f := &fund.Fund{
		Code:         fc,
		Status:       fund.Subscribed,
		SubscribedAt: &now,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	if err := uc.fundRepo.Save(ctx, f); err != nil {
		return nil, fmt.Errorf("FundUseCase.Subscribe: %w", err)
	}

	// 2. Fetch metadata from collector to enrich fund info.
	detail, err := uc.fundProvider.FetchFundDetail(ctx, code)
	if err != nil {
		uc.logger.Warnw("failed to fetch fund detail, proceeding without metadata",
			"code", code, "error", err)
		return nil, fmt.Errorf("FundUseCase.Subscribe: fetch detail: %w", err)
	} else {
		f.Name = detail.Name
		f.FundType = detail.FundType
		f.Company = detail.Company
		f.Manager = detail.Manager
		size := detail.Size
		f.Size = &size
		f.EstablishDate = detail.EstablishDate
		f.SizeDate = detail.SizeDate
		f.CustodianBank = detail.CustodianBank
		f.Benchmark = detail.Benchmark
		f.ManagementFee = detail.ManagementFee
		f.CustodianFee = detail.CustodianFee
		f.UpdatedAt = time.Now()

		if saveErr := uc.fundRepo.Save(ctx, f); saveErr != nil {
			return nil, fmt.Errorf("FundUseCase.Subscribe: save detail: %w", saveErr)
		}
	}

	// 3. Log success.
	uc.logger.Infow("fund subscribed", "code", f.Code, "name", f.Name)
	return f, nil
}

// Unsubscribe marks a fund as unsubscribed.
func (uc *FundUseCase) Unsubscribe(ctx context.Context, code string) error {
	f, err := uc.fundRepo.GetByCode(ctx, fund.FundCode(code))
	if err != nil {
		return fmt.Errorf("get fund by code: %w", err)
	}
	if f == nil {
		return fmt.Errorf("fund %s not found", code)
	}
	if err := f.Unsubscribe(); err != nil {
		return err
	}

	err = uc.fundRepo.Save(ctx, f)
	if err != nil {
		return fmt.Errorf("FundUseCase.Unsubscribe: %w", err)
	}
	uc.logger.Infow("fund unsubscribed", "code", code)
	return nil
}

// ListSubscribed returns all subscribed funds.
func (uc *FundUseCase) ListSubscribed(ctx context.Context) ([]*fund.Fund, error) {
	return uc.fundRepo.ListSubscribed(ctx)
}

// ListAll returns all funds (subscribed and unsubscribed).
func (uc *FundUseCase) ListAll(ctx context.Context) ([]*fund.Fund, error) {
	return uc.fundRepo.ListAll(ctx)
}

// AddToWatchlist adds a fund to the watchlist without subscribing (is_subscribed=false).
// Fetches fund detail from collector to populate metadata.
func (uc *FundUseCase) AddToWatchlist(ctx context.Context, code string) (*fund.Fund, error) {
	fc := fund.FundCode(code)
	if err := fc.Validate(); err != nil {
		return nil, fmt.Errorf("FundUseCase.AddToWatchlist: %w", err)
	}

	// Check if fund already exists.
	existing, err := uc.fundRepo.GetByCode(ctx, fc)
	if err != nil {
		return nil, fmt.Errorf("FundUseCase.AddToWatchlist: %w", err)
	}
	if existing != nil {
		return nil, fund.ErrAlreadyInWatchlist
	}

	// Fetch metadata from collector.
	detail, err := uc.fundProvider.FetchFundDetail(ctx, code)
	if err != nil {
		return nil, fmt.Errorf("FundUseCase.AddToWatchlist: fetch detail: %w", err)
	}

	now := time.Now()
	f := &fund.Fund{
		Code:          fc,
		Name:          detail.Name,
		FundType:      detail.FundType,
		Company:       detail.Company,
		Manager:       detail.Manager,
		EstablishDate: detail.EstablishDate,
		SizeDate:      detail.SizeDate,
		CustodianBank: detail.CustodianBank,
		Benchmark:     detail.Benchmark,
		ManagementFee: detail.ManagementFee,
		CustodianFee:  detail.CustodianFee,
		Status:        fund.Unsubscribed,
		CreatedAt:     now,
		UpdatedAt:     now,
	}
	if detail.Size > 0 {
		size := detail.Size
		f.Size = &size
	}

	if err := uc.fundRepo.Save(ctx, f); err != nil {
		return nil, fmt.Errorf("FundUseCase.AddToWatchlist: save: %w", err)
	}

	uc.logger.Infow("fund added to watchlist", "code", code, "name", f.Name)
	return f, nil
}

// Remove permanently deletes a fund from the platform.
func (uc *FundUseCase) Remove(ctx context.Context, code string) error {
	fc := fund.FundCode(code)
	existing, err := uc.fundRepo.GetByCode(ctx, fc)
	if err != nil {
		return fmt.Errorf("FundUseCase.Remove: %w", err)
	}
	if existing == nil {
		return fund.ErrFundNotFound
	}

	if err := uc.fundRepo.Delete(ctx, fc); err != nil {
		return fmt.Errorf("FundUseCase.Remove: %w", err)
	}

	uc.logger.Infow("fund removed", "code", code)
	return nil
}

// Search finds funds by code, name, or pinyin.
func (uc *FundUseCase) Search(ctx context.Context, query string, limit int) ([]*fund.Fund, error) {
	if limit <= 0 {
		limit = 20
	}
	return uc.fundRepo.Search(ctx, query, limit)
}

func (uc *FundUseCase) GetByCode(ctx context.Context, code string) (*fund.Fund, error) {
	return uc.fundRepo.GetByCode(ctx, fund.FundCode(code))
}

func (uc *FundUseCase) GetNAV(ctx context.Context, code string) (*nav.NAV, error) {
	return uc.navRepo.GetLatest(ctx, shared.FundCode(code))
}

func (uc *FundUseCase) GetNAVs(ctx context.Context, codes []string) (map[string]*nav.NAV, error) {
	fcodes := make([]shared.FundCode, len(codes))
	for i, c := range codes {
		fcodes[i] = shared.FundCode(c)
	}
	res, err := uc.navRepo.GetLatestBatch(ctx, fcodes)
	if err != nil {
		return nil, err
	}
	out := make(map[string]*nav.NAV, len(res))
	for k, v := range res {
		out[string(k)] = v
	}
	return out, nil
}

func (uc *FundUseCase) GetNAVHistory(ctx context.Context, code string, start, end time.Time) ([]nav.NAV, error) {
	return uc.navRepo.GetByFundCode(ctx, shared.FundCode(code), start, end)
}
