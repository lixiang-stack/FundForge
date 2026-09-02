package circuitbreaker

import (
	"errors"
	"fmt"
	"sync"
	"time"
)

// State represents the circuit breaker's current state.
type State int

const (
	Closed   State = iota // Normal operation — requests pass through.
	Open                  // Fault detected — requests are rejected immediately.
	HalfOpen              // Probing — a limited number of requests are allowed through to test recovery.
)

func (s State) String() string {
	switch s {
	case Closed:
		return "CLOSED"
	case Open:
		return "OPEN"
	case HalfOpen:
		return "HALF_OPEN"
	default:
		return "UNKNOWN"
	}
}

// ErrCircuitOpen is returned when a call is attempted while the circuit is open.
var ErrCircuitOpen = errors.New("circuit breaker is open")

// Breaker implements the circuit breaker pattern.
//
// State transitions:
//
//	CLOSED  —(failures >= maxFailures)—→  OPEN
//	OPEN    —(after resetTimeout)——————→  HALF_OPEN
//	HALF_OPEN —(success)———————————————→  CLOSED
//	HALF_OPEN —(failure)———————————————→  OPEN
type Breaker struct {
	name             string
	maxFailures      int
	resetTimeout     time.Duration
	halfOpenMaxCalls int

	mu              sync.Mutex
	state           State
	failureCount    int
	lastFailureTime time.Time
	halfOpenCalls   int
}

// Option configures a Breaker.
type Option func(*Breaker)

// WithMaxFailures sets the number of consecutive failures before the circuit opens.
func WithMaxFailures(n int) Option {
	return func(b *Breaker) { b.maxFailures = n }
}

// WithResetTimeout sets the duration the circuit stays open before transitioning to half-open.
func WithResetTimeout(d time.Duration) Option {
	return func(b *Breaker) { b.resetTimeout = d }
}

// WithHalfOpenMaxCalls sets how many probe calls are allowed in the half-open state.
func WithHalfOpenMaxCalls(n int) Option {
	return func(b *Breaker) { b.halfOpenMaxCalls = n }
}

// New creates a Breaker with sensible defaults.
func New(name string, opts ...Option) *Breaker {
	b := &Breaker{
		name:             name,
		maxFailures:      5,
		resetTimeout:     60 * time.Second,
		halfOpenMaxCalls: 1,
		state:            Closed,
	}
	for _, o := range opts {
		o(b)
	}
	return b
}

// Execute runs fn through the circuit breaker.
//
// In Closed state, fn runs normally; consecutive failures are counted.
// In Open state, ErrCircuitOpen is returned immediately.
// In HalfOpen state, a limited number of probe calls are allowed.
func (b *Breaker) Execute(fn func() error) error {
	b.mu.Lock()
	state := b.currentStateLocked()
	switch state {
	case Open:
		b.mu.Unlock()
		return fmt.Errorf("%w: %s", ErrCircuitOpen, b.name)
	case HalfOpen:
		if b.halfOpenCalls >= b.halfOpenMaxCalls {
			b.mu.Unlock()
			return fmt.Errorf("%w: %s (half-open probe limit reached)", ErrCircuitOpen, b.name)
		}
		b.halfOpenCalls++
		b.mu.Unlock()
	default: // Closed
		b.mu.Unlock()
	}

	err := fn()

	b.mu.Lock()
	defer b.mu.Unlock()

	if err != nil {
		b.onFailureLocked()
		return err
	}
	b.onSuccessLocked()
	return nil
}

// State returns the breaker's current state (accounts for timeout-based transitions).
func (b *Breaker) State() State {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.currentStateLocked()
}

// Reset forces the breaker back to Closed.
func (b *Breaker) Reset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.state = Closed
	b.failureCount = 0
	b.halfOpenCalls = 0
}

// currentStateLocked evaluates whether the Open→HalfOpen timeout has elapsed.
// Must be called with b.mu held.
func (b *Breaker) currentStateLocked() State {
	if b.state == Open && time.Since(b.lastFailureTime) >= b.resetTimeout {
		b.state = HalfOpen
		b.halfOpenCalls = 0
	}
	return b.state
}

func (b *Breaker) onSuccessLocked() {
	b.failureCount = 0
	if b.state == HalfOpen {
		b.state = Closed
		b.halfOpenCalls = 0
	}
}

func (b *Breaker) onFailureLocked() {
	b.failureCount++
	b.lastFailureTime = time.Now()

	switch b.state {
	case HalfOpen:
		b.state = Open
	case Closed:
		if b.failureCount >= b.maxFailures {
			b.state = Open
		}
	}
}
