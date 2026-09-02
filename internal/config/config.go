package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	ServerPort string
	GinMode    string

	DatabaseURL string
	DBMaxConns  int32
	DBMinConns  int32

	CollectorBaseURL string

	FetchIntervalMs  int
	MigrationsPath   string
}

func Load() *Config {
	return &Config{
		ServerPort:       getEnv("SERVER_PORT", "8080"),
		GinMode:          getEnv("GIN_MODE", "debug"),
		DatabaseURL:      getEnv("DATABASE_URL", "postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable"),
		DBMaxConns:       int32(getEnvInt("DB_MAX_CONNS", 10)),
		DBMinConns:       int32(getEnvInt("DB_MIN_CONNS", 2)),
		CollectorBaseURL: getEnv("COLLECTOR_BASE_URL", "http://localhost:8000"),
		FetchIntervalMs:  getEnvInt("FETCH_INTERVAL_MS", 500),
		MigrationsPath:   getEnv("MIGRATIONS_PATH", "file://migrations"),
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); strings.TrimSpace(val) != "" {
		return val
	}
	return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
	val := os.Getenv(key)
	if val == "" {
		return defaultVal
	}
	result, err := strconv.Atoi(strings.TrimSpace(val))
	if err != nil {
		return defaultVal
	}
	return result
}
