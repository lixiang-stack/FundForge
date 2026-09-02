// Package shared holds the cross-aggregate value objects used across the FundForge
// bounded context. Types here are referenced by multiple domain modules
// (fund, alert, marketdata, strategy, ...) and must have stable, agreed
// semantics; changes here ripple across the entire domain.
package shared

import "fmt"

// FundCode is a 6-digit fund identifier assigned by the regulator at fund
// registration. It is globally unique across the market, immutable, and
// externally meaningful — the natural identity of a Fund within FundForge.
type FundCode string

// Validate checks that FundCode is exactly 6 ASCII digits.
func (c FundCode) Validate() error {
	if len(c) != 6 {
		return fmt.Errorf("fund code must be 6 digits, got %d characters", len(c))
	}
	for _, r := range c {
		if r < '0' || r > '9' {
			return fmt.Errorf("fund code must contain only digits, got %q", string(c))
		}
	}
	return nil
}

// String implements fmt.Stringer.
func (c FundCode) String() string { return string(c) }
