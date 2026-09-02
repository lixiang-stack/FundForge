package collector

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/lixiang/fundforge/internal/domain/marketdata"
	"github.com/lixiang/fundforge/internal/domain/nav"
	"github.com/lixiang/fundforge/internal/infra/circuitbreaker"
	"github.com/lixiang/fundforge/internal/infra/retry"
	"go.uber.org/zap"
)

// Client implements marketdata interface by calling the Python collector service.
// Every HTTP call is wrapped with Retry (outer) + Circuit Breaker (inner).
type Client struct {
	baseURL    string
	httpClient *http.Client
	breaker    *circuitbreaker.Breaker
	retryCfg   retry.Config
	logger     *zap.SugaredLogger
}

// NewClient creates a new collector client with default resilience settings.
func NewClient(baseURL string, logger *zap.SugaredLogger) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 120 * time.Second},
		breaker: circuitbreaker.New("collector",
			circuitbreaker.WithMaxFailures(5),
			circuitbreaker.WithResetTimeout(120*time.Second),
		),
		retryCfg: retry.Config{
			MaxAttempts:  3,
			InitialDelay: 2 * time.Second,
			MaxDelay:     15 * time.Second,
			Multiplier:   2.0,
			Jitter:       true,
		},
		logger: logger,
	}
}

// doGet performs an HTTP GET with Retry + Circuit Breaker.
func (c *Client) doGet(ctx context.Context, path string) ([]byte, error) {
	var body []byte
	err := retry.Do(ctx, c.retryCfg, func() error {
		return c.breaker.Execute(func() error {
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
			if err != nil {
				return fmt.Errorf("build request %s: %w", path, err)
			}
			resp, err := c.httpClient.Do(req)
			if err != nil {
				return fmt.Errorf("GET %s: %w", path, err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				b, _ := io.ReadAll(resp.Body)
				return fmt.Errorf("collector %s returned %d: %s", path, resp.StatusCode, string(b))
			}
			body, err = io.ReadAll(resp.Body)
			return err
		})
	})
	return body, err
}

// --- interface implementation ---

func (c *Client) FetchFundNAV(ctx context.Context, code, indicator, period string) ([]nav.NAV, error) {
	path := fmt.Sprintf("/api/funds/%s/nav?indicator=%s&period=%s",
		url.PathEscape(code), url.QueryEscape(indicator), url.QueryEscape(period))
	body, err := c.doGet(ctx, path)
	if err != nil {
		return nil, fmt.Errorf("FetchFundNAV(%s): %w", code, err)
	}
	var raw []navItemJSON
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("FetchFundNAV(%s): unmarshal: %w", code, err)
	}
	return convertNAVs(raw, code), nil
}

func (c *Client) FetchTradeCalendar(ctx context.Context) ([]time.Time, error) {
	body, err := c.doGet(ctx, "/api/trade-calendar")
	if err != nil {
		return nil, fmt.Errorf("FetchTradeCalendar: %w", err)
	}
	var raw []tradeCalendarJSON
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("FetchTradeCalendar: unmarshal: %w", err)
	}
	return convertCalendar(raw), nil
}

func (c *Client) FetchFundDetail(ctx context.Context, code string) (*marketdata.FundDetail, error) {
	path := fmt.Sprintf("/api/funds/%s/detail", url.PathEscape(code))
	body, err := c.doGet(ctx, path)
	if err != nil {
		return nil, fmt.Errorf("FetchFundDetail(%s): %w", code, err)
	}
	var raw []fundDetailJSON
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("FetchFundDetail(%s): unmarshal: %w", code, err)
	}
	detail := convertFundDetail(raw)
	if detail == nil {
		return nil, fmt.Errorf("FetchFundDetail(%s): empty response", code)
	}
	return detail, nil
}

func (c *Client) FetchDividends(ctx context.Context) ([]marketdata.DividendRaw, error) {
	body, err := c.doGet(ctx, "/api/funds/dividends")
	if err != nil {
		return nil, fmt.Errorf("FetchDividends: %w", err)
	}
	var raw []dividendJSON
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("FetchDividends: unmarshal: %w", err)
	}
	return convertDividends(raw), nil
}

func (c *Client) FetchSplits(ctx context.Context) ([]marketdata.SplitRaw, error) {
	body, err := c.doGet(ctx, "/api/funds/splits")
	if err != nil {
		return nil, fmt.Errorf("FetchSplits: %w", err)
	}
	var raw []splitJSON
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("FetchSplits: unmarshal: %w", err)
	}
	return convertSplits(raw), nil
}

var _ marketdata.FundProvider = (*Client)(nil)
var _ marketdata.TradeCalendarProvider = (*Client)(nil)
var _ marketdata.CorporateActionProvider = (*Client)(nil)
