package alert

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func newTriggered() *Alert {
	return &Alert{Status: Triggered, TriggeredAt: time.Now()}
}

func TestAlert_Confirm(t *testing.T) {
	tests := []struct {
		name    string
		alert   *Alert
		wantErr bool
	}{
		{
			name:    "from triggered sets ConfirmedAt",
			alert:   newTriggered(),
			wantErr: false,
		},
		{
			name:    "from confirmed returns error",
			alert:   &Alert{Status: Confirmed},
			wantErr: true,
		},
		{
			name:    "from ignored returns error",
			alert:   &Alert{Status: Ignored},
			wantErr: true,
		},
		{
			name:    "from recovered returns error",
			alert:   &Alert{Status: Recovered},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.alert.Confirm()
			if tt.wantErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrInvalidTransition)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, Confirmed, tt.alert.Status)
			assert.NotNil(t, tt.alert.ConfirmedAt)
		})
	}
}

func TestAlert_Ignore(t *testing.T) {
	tests := []struct {
		name    string
		alert   *Alert
		wantErr bool
	}{
		{
			name:    "from triggered",
			alert:   newTriggered(),
			wantErr: false,
		},
		{
			name:    "from confirmed returns error",
			alert:   &Alert{Status: Confirmed},
			wantErr: true,
		},
		{
			name:    "from ignored returns error",
			alert:   &Alert{Status: Ignored},
			wantErr: true,
		},
		{
			name:    "from recovered returns error",
			alert:   &Alert{Status: Recovered},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.alert.Ignore()
			if tt.wantErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrInvalidTransition)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, Ignored, tt.alert.Status)
		})
	}
}

func TestAlert_Recover(t *testing.T) {
	tests := []struct {
		name    string
		alert   *Alert
		wantErr bool
	}{
		{
			name:    "from triggered",
			alert:   newTriggered(),
			wantErr: false,
		},
		{
			name:    "from confirmed",
			alert:   &Alert{Status: Confirmed},
			wantErr: false,
		},
		{
			name:    "from ignored returns error",
			alert:   &Alert{Status: Ignored},
			wantErr: true,
		},
		{
			name:    "from recovered returns error",
			alert:   &Alert{Status: Recovered},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.alert.Recover()
			if tt.wantErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrInvalidTransition)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, Recovered, tt.alert.Status)
			assert.NotNil(t, tt.alert.RecoveredAt)
		})
	}
}

func TestAlert_CanTransitionTo(t *testing.T) {
	tests := []struct {
		name   string
		from   Status
		to     Status
		expect bool
	}{
		// Valid transitions from Triggered
		{name: "triggered->confirmed", from: Triggered, to: Confirmed, expect: true},
		{name: "triggered->ignored", from: Triggered, to: Ignored, expect: true},
		{name: "triggered->recovered", from: Triggered, to: Recovered, expect: true},
		// Valid transition from Confirmed
		{name: "confirmed->recovered", from: Confirmed, to: Recovered, expect: true},
		// Invalid transitions
		{name: "confirmed->ignored", from: Confirmed, to: Ignored, expect: false},
		{name: "confirmed->triggered", from: Confirmed, to: Triggered, expect: false},
		{name: "ignored->recovered", from: Ignored, to: Recovered, expect: false},
		{name: "ignored->confirmed", from: Ignored, to: Confirmed, expect: false},
		{name: "recovered->triggered", from: Recovered, to: Triggered, expect: false},
		{name: "recovered->confirmed", from: Recovered, to: Confirmed, expect: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			a := &Alert{Status: tt.from}
			assert.Equal(t, tt.expect, a.CanTransitionTo(tt.to))
		})
	}
}
