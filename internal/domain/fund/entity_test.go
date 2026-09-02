package fund

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestFundCode_Validate(t *testing.T) {
	tests := []struct {
		name    string
		code    FundCode
		wantErr bool
	}{
		{name: "valid 6-digit code", code: "110011", wantErr: false},
		{name: "valid all zeros", code: "000000", wantErr: false},
		{name: "too short", code: "12345", wantErr: true},
		{name: "too long", code: "1234567", wantErr: true},
		{name: "contains letters", code: "12ab56", wantErr: true},
		{name: "empty string", code: "", wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.code.Validate()
			if tt.wantErr {
				assert.Error(t, err)
			} else {
				assert.NoError(t, err)
			}
		})
	}
}

func TestFund_Subscribe(t *testing.T) {
	tests := []struct {
		name    string
		fund    Fund
		wantErr error
	}{
		{
			name:    "from zero value",
			fund:    Fund{},
			wantErr: nil,
		},
		{
			name:    "from Unsubscribed (re-subscribe)",
			fund:    Fund{Status: Unsubscribed},
			wantErr: nil,
		},
		{
			name:    "already subscribed returns error",
			fund:    Fund{Status: Subscribed},
			wantErr: ErrAlreadySubscribed,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			f := tt.fund
			err := f.Subscribe()

			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, Subscribed, f.Status)
			assert.NotNil(t, f.SubscribedAt)
		})
	}
}

func TestFund_Unsubscribe(t *testing.T) {
	tests := []struct {
		name    string
		fund    Fund
		wantErr error
	}{
		{
			name:    "from Subscribed",
			fund:    Fund{Status: Subscribed},
			wantErr: nil,
		},
		{
			name:    "not subscribed returns error",
			fund:    Fund{Status: Unsubscribed},
			wantErr: ErrNotSubscribed,
		},
		{
			name:    "zero value returns error",
			fund:    Fund{},
			wantErr: ErrNotSubscribed,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			f := tt.fund
			err := f.Unsubscribe()

			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, Unsubscribed, f.Status)
			assert.NotNil(t, f.UnsubscribedAt)
		})
	}
}

func TestFund_CanResubscribe(t *testing.T) {
	tests := []struct {
		name string
		fund Fund
		want bool
	}{
		{name: "true when Unsubscribed", fund: Fund{Status: Unsubscribed}, want: true},
		{name: "false when Subscribed", fund: Fund{Status: Subscribed}, want: false},
		{name: "false when zero value", fund: Fund{}, want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, tt.fund.CanResubscribe())
		})
	}
}
