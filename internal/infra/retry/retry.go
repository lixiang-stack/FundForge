package retry

import (
	"context"
	"math"
	"math/rand/v2"
	"time"
)

// Config controls retry behaviour.
type Config struct {
	MaxAttempts  int           // Total attempts (including the first call). Default: 3.
	InitialDelay time.Duration // Delay before the first retry. Default: 1s.
	MaxDelay     time.Duration // Upper bound on delay. Default: 30s.
	Multiplier   float64       // Exponential multiplier per attempt. Default: 2.0.
	Jitter       bool          // Add random jitter to delay. Default: true.
	RetryIf      func(error) bool // If set, only retry errors for which this returns true. Nil means retry all errors.
}

// DefaultConfig returns a sensible default configuration.
func DefaultConfig() Config {
	return Config{
		MaxAttempts:  3,
		InitialDelay: 1 * time.Second,
		MaxDelay:     30 * time.Second,
		Multiplier:   2.0,
		Jitter:       true,
	}
}

// Do retries fn until it succeeds or the maximum attempts are exhausted.
// The context can be used to abort early.
// If cfg.RetryIf is set, only errors for which RetryIf returns true will be retried;
// other errors are returned immediately.
func Do(ctx context.Context, cfg Config, fn func() error) error {
	var lastErr error
	for attempt := 0; attempt < cfg.MaxAttempts; attempt++ {
		if err := ctx.Err(); err != nil {
			return err
		}

		lastErr = fn()
		if lastErr == nil {
			return nil
		}

		// If RetryIf is configured and this error is not retryable, bail out.
		if cfg.RetryIf != nil && !cfg.RetryIf(lastErr) {
			return lastErr
		}

		// Don't sleep after the last attempt.
		if attempt < cfg.MaxAttempts-1 {
			delay := computeDelay(cfg, attempt)
			timer := time.NewTimer(delay)
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			}
		}
	}
	return lastErr
}

// DoWithResult is a generic version of Do that returns a value alongside the error.
func DoWithResult[T any](ctx context.Context, cfg Config, fn func() (T, error)) (T, error) {
	var (
		result  T
		lastErr error
	)
	for attempt := 0; attempt < cfg.MaxAttempts; attempt++ {
		if err := ctx.Err(); err != nil {
			return result, err
		}

		result, lastErr = fn()
		if lastErr == nil {
			return result, nil
		}

		// If RetryIf is configured and this error is not retryable, bail out.
		if cfg.RetryIf != nil && !cfg.RetryIf(lastErr) {
			return result, lastErr
		}

		if attempt < cfg.MaxAttempts-1 {
			delay := computeDelay(cfg, attempt)
			timer := time.NewTimer(delay)
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				return result, ctx.Err()
			}
		}
	}
	return result, lastErr
}

// computeDelay calculates the backoff delay for the given attempt.
// Formula: min(initialDelay * multiplier^attempt, maxDelay) ± jitter.
func computeDelay(cfg Config, attempt int) time.Duration {
	delay := float64(cfg.InitialDelay) * math.Pow(cfg.Multiplier, float64(attempt))
	if delay > float64(cfg.MaxDelay) {
		delay = float64(cfg.MaxDelay)
	}
	if cfg.Jitter {
		// ±25% jitter
		jitterRange := delay * 0.25
		delay = delay - jitterRange + rand.Float64()*2*jitterRange
	}
	if delay < 0 {
		delay = 0
	}
	return time.Duration(delay)
}
