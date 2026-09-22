package benchmark

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSymbol(t *testing.T) {
	assert.Equal(t, "sh000905", Symbol("000905"))
	assert.Equal(t, "sh000300", Symbol("000300"))
	assert.Equal(t, "sz399006", Symbol("399006"))
	// 已带前缀（agent 侧传 sh000905 之类）原样透传
	assert.Equal(t, "sh000905", Symbol("sh000905"))
	assert.Equal(t, "csi000905", Symbol("csi000905"))
}
