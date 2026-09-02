package dto

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

type APIResponse struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

func Success(c *gin.Context, data any) {
	c.JSON(http.StatusOK, APIResponse{
		Code:    0,
		Message: "ok",
		Data:    data,
	})
}

func Created(c *gin.Context, data any) {
	c.JSON(http.StatusCreated, APIResponse{
		Code:    0,
		Message: "ok",
		Data:    data,
	})
}

func Error(c *gin.Context, httpStatus int, message string) {
	c.JSON(httpStatus, APIResponse{
		Code:    -1,
		Message: message,
	})
}

type Alert struct {
	ID                int64              `json:"id"`
	FundCode          string             `json:"fund_code"`
	StrategyID        int64              `json:"strategy_id"`
	Status            string             `json:"status"`
	Severity          string             `json:"severity"`
	DataDate          time.Time          `json:"data_date"`
	TriggeredAt       time.Time          `json:"triggered_at"`
	RecoveredAt       *time.Time         `json:"recovered_at"`
	ConfirmedAt       *time.Time         `json:"confirmed_at"`
	IndicatorSnapshot map[string]float64 `json:"indicator_snapshot"`
	ConditionSnapshot json.RawMessage    `json:"condition_snapshot"`
	Message           string             `json:"message"`
	CreatedAt         time.Time          `json:"created_at"`
	UpdatedAt         time.Time          `json:"updated_at"`
}

type Fund struct {
	Code             string     `json:"code"`
	Name             string     `json:"name"`
	FundType         string     `json:"fund_type"`
	PinyinAbbr       string     `json:"pinyin_abbr"`
	PinyinFull       string     `json:"pinyin_full"`
	Company          string     `json:"company"`
	Manager          string     `json:"manager"`
	Size             *float64   `json:"size"`
	SizeDate         *time.Time `json:"size_date"`
	EstablishDate    *time.Time `json:"establish_date"`
	CustodianBank    string     `json:"custodian_bank"`
	ManagementFee    *float64   `json:"management_fee"`
	CustodianFee     *float64   `json:"custodian_fee"`
	Benchmark        string     `json:"benchmark"`
	Status           int        `json:"status"`
	SubscribedAt     *time.Time `json:"subscribed_at"`
	UnsubscribedAt   *time.Time `json:"unsubscribed_at"`
	InitialFetchDone bool       `json:"initial_fetch_done"`
	LastNAVDate      *time.Time `json:"last_nav_date"`
	LastFetchAt      *time.Time `json:"last_fetch_at"`
	CustomBenchmark  string     `json:"custom_benchmark"`
	CreatedAt        time.Time  `json:"created_at"`
	UpdatedAt        time.Time  `json:"updated_at"`
}

type Dividend struct {
	ID              int64     `json:"id"`
	FundCode        string    `json:"fund_code"`
	FundName        string    `json:"fund_name"`
	RecordDate      string    `json:"record_date"`
	ExDate          string    `json:"ex_date"`
	DividendPerUnit float64   `json:"dividend_per_unit"`
	PayDate         string    `json:"pay_date"`
	FetchedAt       time.Time `json:"fetched_at"`
}

type Split struct {
	ID         int64     `json:"id"`
	FundCode   string    `json:"fund_code"`
	FundName   string    `json:"fund_name"`
	SplitDate  string    `json:"split_date"`
	SplitType  string    `json:"split_type"`
	SplitRatio float64   `json:"split_ratio"`
	FetchedAt  time.Time `json:"fetched_at"`
}

type ManagerChange struct {
	ID              int64     `json:"id"`
	FundCode        string    `json:"fund_code"`
	DetectedAt      time.Time `json:"detected_at"`
	PreviousManager string    `json:"previous_manager"`
	CurrentManager  string    `json:"current_manager"`
	ChangeDate      string    `json:"change_date"`
}

type StockHolding struct {
	ID         int64     `json:"id"`
	FundCode   string    `json:"fund_code"`
	ReportDate string    `json:"report_date"`
	StockCode  string    `json:"stock_code"`
	StockName  string    `json:"stock_name"`
	HoldRatio  float64   `json:"hold_ratio"`
	HoldShares float64   `json:"hold_shares"`
	HoldValue  float64   `json:"hold_value"`
	FetchedAt  time.Time `json:"fetched_at"`
}

type BondHolding struct {
	ID         int64     `json:"id"`
	FundCode   string    `json:"fund_code"`
	ReportDate string    `json:"report_date"`
	BondCode   string    `json:"bond_code"`
	BondName   string    `json:"bond_name"`
	HoldRatio  float64   `json:"hold_ratio"`
	HoldValue  float64   `json:"hold_value"`
	FetchedAt  time.Time `json:"fetched_at"`
}

type NAV struct {
	ID          int64     `json:"id"`
	FundCode    string    `json:"fund_code"`
	Date        time.Time `json:"date"`
	UnitNAV     float64   `json:"unit_nav"`
	AccNAV      float64   `json:"acc_nav"`
	DailyReturn float64   `json:"daily_return"`
	FetchedAt   time.Time `json:"fetched_at"`
}

type MoneyFundNAV struct {
	ID                   int64     `json:"id"`
	FundCode             string    `json:"fund_code"`
	Date                 time.Time `json:"date"`
	IncomePerTenThousand float64   `json:"income_per_ten_thousand"`
	SevenDayYield        float64   `json:"seven_day_yield"`
	FetchedAt            time.Time `json:"fetched_at"`
}

type TradeDate struct {
	Date         time.Time `json:"date"`
	IsTradingDay bool      `json:"is_trading_day"`
}

type BenchmarkIndex struct {
	ID                  int64     `json:"id"`
	IndexCode           string    `json:"index_code"`
	IndexName           string    `json:"index_name"`
	ApplicableFundTypes []string  `json:"applicable_fund_types"`
	IsDefault           bool      `json:"is_default"`
	CreatedAt           time.Time `json:"created_at"`
}

type BenchmarkDaily struct {
	ID          int64     `json:"id"`
	IndexCode   string    `json:"index_code"`
	TradeDate   time.Time `json:"trade_date"`
	ClosePrice  float64   `json:"close_price"`
	DailyReturn float64   `json:"daily_return"`
	FetchedAt   time.Time `json:"fetched_at"`
}

type PriceBar struct {
	Date  time.Time `json:"date"`
	Close float64   `json:"close"`
}

type Condition struct {
	Indicator string  `json:"indicator"`
	Operator  string  `json:"operator"`
	Threshold float64 `json:"threshold"`
}

type StrategyTemplate struct {
	ID           int64       `json:"id"`
	Name         string      `json:"name"`
	Description  string      `json:"description"`
	Severity     string      `json:"severity"`
	Logic        string      `json:"logic"`
	Conditions   []Condition `json:"conditions"`
	CooldownDays int         `json:"cooldown_days"`
	IsEnabled    bool        `json:"is_enabled"`
	IsPreset     bool        `json:"is_preset"`
	CreatedAt    time.Time   `json:"created_at"`
	UpdatedAt    time.Time   `json:"updated_at"`
}

type StrategyBinding struct {
	ID         int64     `json:"id"`
	StrategyID int64     `json:"strategy_id"`
	FundCode   string    `json:"fund_code"`
	IsEnabled  bool      `json:"is_enabled"`
	CreatedAt  time.Time `json:"created_at"`
}
