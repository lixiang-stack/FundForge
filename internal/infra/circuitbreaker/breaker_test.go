package circuitbreaker

import (
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var errTest = errors.New("test error")

func TestBreaker_ClosedState(t *testing.T) {
	tests := []struct {
		name       string
		successes  int
		wantState  State
	}{
		{name: "single success stays closed", successes: 1, wantState: Closed},
		{name: "multiple successes stay closed", successes: 5, wantState: Closed},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(3), WithResetTimeout(50*time.Millisecond))
			for range tt.successes {
				err := b.Execute(func() error { return nil })
				require.NoError(t, err)
			}
			assert.Equal(t, tt.wantState, b.State())
		})
	}
}

func TestBreaker_OpenAfterFailures(t *testing.T) {
	tests := []struct {
		name        string
		maxFailures int
	}{
		{name: "3 failures opens circuit", maxFailures: 3},
		{name: "5 failures opens circuit", maxFailures: 5},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(tt.maxFailures), WithResetTimeout(100*time.Millisecond))

			// Drive to Open state
			for range tt.maxFailures {
				_ = b.Execute(func() error { return errTest })
			}
			assert.Equal(t, Open, b.State())

			// Subsequent calls should return ErrCircuitOpen
			err := b.Execute(func() error { return nil })
			require.Error(t, err)
			assert.ErrorIs(t, err, ErrCircuitOpen)
		})
	}
}

func TestBreaker_HalfOpenAfterTimeout(t *testing.T) {
	tests := []struct {
		name         string
		resetTimeout time.Duration
	}{
		{name: "50ms timeout", resetTimeout: 50 * time.Millisecond},
		{name: "80ms timeout", resetTimeout: 80 * time.Millisecond},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(2), WithResetTimeout(tt.resetTimeout))

			// Open the circuit
			for range 2 {
				_ = b.Execute(func() error { return errTest })
			}
			assert.Equal(t, Open, b.State())

			// Wait for resetTimeout to elapse
			time.Sleep(tt.resetTimeout + 20*time.Millisecond)

			assert.Equal(t, HalfOpen, b.State())
		})
	}
}

func TestBreaker_HalfOpenToClosedOnSuccess(t *testing.T) {
	tests := []struct {
		name string
	}{
		{name: "success in HalfOpen transitions to Closed"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(2), WithResetTimeout(50*time.Millisecond))

			// Open the circuit
			for range 2 {
				_ = b.Execute(func() error { return errTest })
			}

			// Wait for HalfOpen
			time.Sleep(70 * time.Millisecond)
			assert.Equal(t, HalfOpen, b.State())

			// Success should transition to Closed
			err := b.Execute(func() error { return nil })
			require.NoError(t, err)
			assert.Equal(t, Closed, b.State())
		})
	}
}

func TestBreaker_HalfOpenToOpenOnFailure(t *testing.T) {
	tests := []struct {
		name string
	}{
		{name: "failure in HalfOpen transitions to Open"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(2), WithResetTimeout(50*time.Millisecond))

			// Open the circuit
			for range 2 {
				_ = b.Execute(func() error { return errTest })
			}

			// Wait for HalfOpen
			time.Sleep(70 * time.Millisecond)
			assert.Equal(t, HalfOpen, b.State())

			// Failure should transition back to Open
			err := b.Execute(func() error { return errTest })
			require.Error(t, err)
			assert.Equal(t, Open, b.State())
		})
	}
}

func TestBreaker_Reset(t *testing.T) {
	tests := []struct {
		name       string
		fromState  string
	}{
		{name: "reset from Open to Closed", fromState: "open"},
		{name: "reset from Closed stays Closed", fromState: "closed"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New("test", WithMaxFailures(2), WithResetTimeout(100*time.Millisecond))

			if tt.fromState == "open" {
				for range 2 {
					_ = b.Execute(func() error { return errTest })
				}
				assert.Equal(t, Open, b.State())
			}

			b.Reset()
			assert.Equal(t, Closed, b.State())

			// Should accept calls after reset
			err := b.Execute(func() error { return nil })
			require.NoError(t, err)
		})
	}
}
