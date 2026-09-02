package postgres

import (
	"context"
	"fmt"
	"strings"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/pgx/v5"
	_ "github.com/golang-migrate/migrate/v4/source/file"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.uber.org/zap"
)

// DB wraps a pgxpool.Pool and provides lifecycle helpers.
type DB struct {
	Pool   *pgxpool.Pool
	logger *zap.SugaredLogger
}

// New creates a connection pool and verifies connectivity.
func New(ctx context.Context, databaseURL string, logger *zap.SugaredLogger, maxConns, minConns int32) (*DB, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("postgres.New: parse config: %w", err)
	}
	cfg.MaxConns = maxConns
	cfg.MinConns = minConns

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("postgres.New: create pool: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres.New: ping: %w", err)
	}

	logger.Infow("database connected", "max_conns", cfg.MaxConns)
	return &DB{Pool: pool, logger: logger}, nil
}

// RunMigrations applies all pending up-migrations.
// migrationsPath should be like "file://migrations".
func (db *DB) RunMigrations(databaseURL, migrationsPath string) error {
	m, err := migrate.New(migrationsPath, toPgx5Scheme(databaseURL))
	if err != nil {
		return fmt.Errorf("postgres.RunMigrations: create migrator: %w", err)
	}
	defer m.Close()

	if err := m.Up(); err != nil && err != migrate.ErrNoChange {
		return fmt.Errorf("postgres.RunMigrations: %w", err)
	}
	db.logger.Info("database migrations applied")
	return nil
}

// Close shuts down the connection pool.
func (db *DB) Close() {
	db.Pool.Close()
	db.logger.Info("database connection closed")
}

// toPgx5Scheme converts postgres:// to pgx5:// for golang-migrate's pgx/v5 driver.
func toPgx5Scheme(dsn string) string {
	if strings.HasPrefix(dsn, "postgres://") {
		return "pgx5://" + dsn[len("postgres://"):]
	}
	if strings.HasPrefix(dsn, "postgresql://") {
		return "pgx5://" + dsn[len("postgresql://"):]
	}
	return dsn
}
