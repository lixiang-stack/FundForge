package logger

import (
	"os"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// New creates a structured logger.
//   - mode "release" → JSON output, InfoLevel.
//   - anything else  → coloured console output, DebugLevel.
func New(mode string) *zap.SugaredLogger {
	var core zapcore.Core
	if mode == "release" {
		enc := zapcore.NewJSONEncoder(zap.NewProductionEncoderConfig())
		core = zapcore.NewCore(enc, zapcore.AddSync(os.Stdout), zap.InfoLevel)
	} else {
		cfg := zap.NewDevelopmentEncoderConfig()
		cfg.EncodeLevel = zapcore.CapitalColorLevelEncoder
		enc := zapcore.NewConsoleEncoder(cfg)
		core = zapcore.NewCore(enc, zapcore.AddSync(os.Stderr), zap.DebugLevel)
	}
	return zap.New(core, zap.AddCaller(), zap.AddStacktrace(zap.ErrorLevel)).Sugar()
}

// NewNop returns a no-op logger for tests.
func NewNop() *zap.SugaredLogger {
	return zap.NewNop().Sugar()
}
