package retry

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var errRetry = errors.New("retry error")

func fastConfig() Config {
	return Config{
		MaxAttempts:  3,
		InitialDelay: 10 * time.Millisecond,
		MaxDelay:     50 * time.Millisecond,
		Multiplier:   2.0,
		Jitter:       false,
	}
}

func TestDo_Success(t *testing.T) {
	tests := []struct {
		name string
	}{
		{name: "succeeds on first try"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			calls := 0
			err := Do(context.Background(), fastConfig(), func() error {
				calls++
				return nil
			})
			require.NoError(t, err)
			assert.Equal(t, 1, calls)
		})
	}
}

func TestDo_RetryThenSuccess(t *testing.T) {
	tests := []struct {
		name          string
		failCount     int
		maxAttempts   int
		wantCalls     int
	}{
		{name: "fail once then succeed", failCount: 1, maxAttempts: 3, wantCalls: 2},
		{name: "fail twice then succeed", failCount: 2, maxAttempts: 3, wantCalls: 3},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := fastConfig()
			cfg.MaxAttempts = tt.maxAttempts

			calls := 0
			err := Do(context.Background(), cfg, func() error {
				calls++
				if calls <= tt.failCount {
					return errRetry
				}
				return nil
			})
			require.NoError(t, err)
			assert.Equal(t, tt.wantCalls, calls)
		})
	}
}

func TestDo_ExhaustedRetries(t *testing.T) {
	tests := []struct {
		name        string
		maxAttempts int
	}{
		{name: "3 attempts all fail", maxAttempts: 3},
		{name: "1 attempt fails", maxAttempts: 1},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := fastConfig()
			cfg.MaxAttempts = tt.maxAttempts

			calls := 0
			err := Do(context.Background(), cfg, func() error {
				calls++
				return errRetry
			})
			require.Error(t, err)
			assert.ErrorIs(t, err, errRetry)
			assert.Equal(t, tt.maxAttempts, calls)
		})
	}
}

func TestDo_ContextCanceled(t *testing.T) {
	tests := []struct {
		name string
	}{
		{name: "context cancelled mid-retry"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := fastConfig()
			cfg.InitialDelay = 500 * time.Millisecond // long delay so cancellation wins
			cfg.MaxAttempts = 3

			ctx, cancel := context.WithCancel(context.Background())

			calls := 0
			go func() {
				// Cancel after the first attempt has time to fail
				time.Sleep(30 * time.Millisecond)
				cancel()
			}()

			err := Do(ctx, cfg, func() error {
				calls++
				return errRetry
			})
			require.Error(t, err)
			assert.ErrorIs(t, err, context.Canceled)
		})
	}
}

func TestDo_RetryIf(t *testing.T) {
	errRetryable := errors.New("retryable error")
	errNonRetryable := errors.New("non-retryable error")

	tests := []struct {
		name      string
		errs      []error
		wantCalls int
		wantErr   error
	}{
		{
			name:      "retryable error is retried",
			errs:      []error{errRetryable, errRetryable, nil},
			wantCalls: 3,
			wantErr:   nil,
		},
		{
			name:      "non-retryable error stops immediately",
			errs:      []error{errNonRetryable},
			wantCalls: 1,
			wantErr:   errNonRetryable,
		},
		{
			name:      "retryable then non-retryable stops at non-retryable",
			errs:      []error{errRetryable, errNonRetryable},
			wantCalls: 2,
			wantErr:   errNonRetryable,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := fastConfig()
			cfg.MaxAttempts = 5
			cfg.RetryIf = func(err error) bool {
				return errors.Is(err, errRetryable)
			}

			calls := 0
			err := Do(context.Background(), cfg, func() error {
				idx := calls
				calls++
				if idx < len(tt.errs) {
					return tt.errs[idx]
				}
				return nil
			})

			assert.Equal(t, tt.wantCalls, calls)
			if tt.wantErr != nil {
				require.Error(t, err)
				assert.ErrorIs(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestDoWithResult(t *testing.T) {
	tests := []struct {
		name      string
		failCount int
		wantVal   string
		wantErr   bool
	}{
		{
			name:      "succeeds on first try returns value",
			failCount: 0,
			wantVal:   "ok",
			wantErr:   false,
		},
		{
			name:      "fails then succeeds returns value",
			failCount: 1,
			wantVal:   "ok",
			wantErr:   false,
		},
		{
			name:      "all attempts fail returns error",
			failCount: 3,
			wantVal:   "",
			wantErr:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := fastConfig()

			calls := 0
			val, err := DoWithResult(context.Background(), cfg, func() (string, error) {
				calls++
				if calls <= tt.failCount {
					return "", errRetry
				}
				return "ok", nil
			})

			if tt.wantErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, errRetry)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.wantVal, val)
			}
		})
	}
}
