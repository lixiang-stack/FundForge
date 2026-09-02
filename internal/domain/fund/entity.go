package fund

import (
	"errors"
	"fmt"
	"time"

	"github.com/lixiang/fundforge/internal/domain/shared"
)

// FundCode is re-exported from the shared kernel for backward compatibility
// and ergonomics. The canonical definition lives in `internal/domain/shared`.
type FundCode = shared.FundCode

// Sentinel errors for fund operations.
var (
	ErrFundNotFound       = errors.New("fund not found")
	ErrAlreadyInWatchlist = errors.New("fund already in watchlist")
)

// --- SubscriptionStatus enum ---

// SubscriptionStatus represents whether a fund is subscribed.
type SubscriptionStatus int

const (
	Subscribed   SubscriptionStatus = 1
	Unsubscribed SubscriptionStatus = 2
)

// String returns a human-readable label.
func (s SubscriptionStatus) String() string {
	switch s {
	case Subscribed:
		return "subscribed"
	case Unsubscribed:
		return "unsubscribed"
	default:
		return "unknown"
	}
}

// Validate returns an error if s is not a known SubscriptionStatus value.
func (s SubscriptionStatus) Validate() error {
	switch s {
	case Subscribed, Unsubscribed:
		return nil
	default:
		return fmt.Errorf("invalid subscription status: %d", int(s))
	}
}

// --- Fund entity (maps to fund_info table) ---

var (
	ErrAlreadySubscribed = errors.New("fund is already subscribed")
	ErrNotSubscribed     = errors.New("fund is not subscribed")
)

// Fund represents a mutual fund tracked by the platform.
// Identity is the FundCode (a 6-digit value object). The DB has an internal
// surrogate primary key but it is not surfaced in the domain.
type Fund struct {
	Code             FundCode
	Name             string
	FundType         string
	PinyinAbbr       string
	PinyinFull       string
	Company          string
	Manager          string
	Size             *float64
	SizeDate         *time.Time
	EstablishDate    *time.Time
	CustodianBank    string
	ManagementFee    *float64
	CustodianFee     *float64
	Benchmark        string
	Status           SubscriptionStatus
	SubscribedAt     *time.Time
	UnsubscribedAt   *time.Time
	InitialFetchDone bool
	LastNAVDate      *time.Time
	LastFetchAt      *time.Time
	CustomBenchmark  string
	CreatedAt        time.Time
	UpdatedAt        time.Time
}

// Subscribe transitions the fund to the Subscribed state.
// It can be called from any state (new, unsubscribed, or re-subscribe).
func (f *Fund) Subscribe() error {
	if f.Status == Subscribed {
		return ErrAlreadySubscribed
	}
	now := time.Now()
	f.Status = Subscribed
	f.SubscribedAt = &now
	f.UpdatedAt = now
	return nil
}

// Unsubscribe transitions the fund from Subscribed to Unsubscribed.
func (f *Fund) Unsubscribe() error {
	if f.Status != Subscribed {
		return ErrNotSubscribed
	}
	now := time.Now()
	f.Status = Unsubscribed
	f.UnsubscribedAt = &now
	f.UpdatedAt = now
	return nil
}

// CanResubscribe returns true if the fund can be re-subscribed
// (i.e., it is currently unsubscribed).
func (f *Fund) CanResubscribe() bool {
	return f.Status == Unsubscribed
}

// --- Dividend ---

// Dividend represents a fund's cash dividend record.
type Dividend struct {
	ID              int64
	FundCode        FundCode
	FundName        string
	RecordDate      string
	ExDate          string
	DividendPerUnit float64
	PayDate         string
	FetchedAt       time.Time
}

// --- Split ---

// Split represents a fund share split or merge record.
type Split struct {
	ID         int64
	FundCode   FundCode
	FundName   string
	SplitDate  string
	SplitType  string
	SplitRatio float64
	FetchedAt  time.Time
}

// --- ManagerChange ---

// ManagerChange records a detected fund manager change.
type ManagerChange struct {
	ID              int64
	FundCode        FundCode
	DetectedAt      time.Time
	PreviousManager string
	CurrentManager  string
	ChangeDate      string
}

// --- StockHolding ---

// StockHolding represents a fund's stock holding from a periodic report.
type StockHolding struct {
	ID         int64
	FundCode   FundCode
	ReportDate string
	StockCode  string
	StockName  string
	HoldRatio  float64
	HoldShares float64
	HoldValue  float64
	FetchedAt  time.Time
}

// --- BondHolding ---

// BondHolding represents a fund's bond holding from a periodic report.
type BondHolding struct {
	ID         int64
	FundCode   FundCode
	ReportDate string
	BondCode   string
	BondName   string
	HoldRatio  float64
	HoldValue  float64
	FetchedAt  time.Time
}

// DetectManagerChange compares the fund's current manager with a newly fetched
// manager name. If they differ a ManagerChange record is returned together with
// true; otherwise nil and false are returned.
func DetectManagerChange(f *Fund, currentManager string) (*ManagerChange, bool, error) {
	if f.Manager == currentManager || currentManager == "" {
		return nil, false, nil
	}

	mc := &ManagerChange{
		FundCode:        f.Code,
		DetectedAt:      time.Now(),
		PreviousManager: f.Manager,
		CurrentManager:  currentManager,
	}
	return mc, true, nil
}
