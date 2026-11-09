// Command notifier delivers the notifications platform services queue in the
// notification_outbox table: it wakes on the table's LISTEN channel, sweeps on
// a timer for wake-ups it missed, renders each body into Freepod's mail layout
// and sends it through the shared SMTP relay. See README.md and the
// notification-outbox design doc.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/mail"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	if err := run(log); err != nil {
		log.Error("exiting", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	dsn := os.Getenv("NOTIFIER_DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("missing configuration: NOTIFIER_DATABASE_URL")
	}
	transport, err := relayFromEnv()
	if err != nil {
		return err
	}
	if transport == nil {
		log.Warn("no relay configured (NOTIFIER_SMTP_HOST, NOTIFIER_SMTP_FROM): every notification will be suppressed")
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pool, err := openPool(ctx, dsn)
	if err != nil {
		return err
	}
	defer pool.Close()

	s := &sender{pool: pool, retryPause: 2 * time.Second, log: log}
	if transport != nil {
		s.transport = transport
	}
	l := &listener{dsn: dsn, sender: s, pollInterval: time.Minute, reconnectDelay: 5 * time.Second}
	l.run(ctx)
	log.Info("stopped")
	return nil
}

func relayFromEnv() (*relay, error) {
	host, from := os.Getenv("NOTIFIER_SMTP_HOST"), os.Getenv("NOTIFIER_SMTP_FROM")
	if host == "" || from == "" {
		return nil, nil
	}
	if _, err := mail.ParseAddress(from); err != nil {
		return nil, fmt.Errorf("NOTIFIER_SMTP_FROM: %w", err)
	}
	port := os.Getenv("NOTIFIER_SMTP_PORT")
	if port == "" {
		port = "25"
	}
	helo, err := os.Hostname()
	if err != nil {
		helo = "localhost"
	}
	return &relay{addr: net.JoinHostPort(host, port), from: from, helo: helo, clock: time.Now}, nil
}

func openPool(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("database url: %w", err)
	}
	cfg.MaxConns = 2
	cfg.ConnConfig.RuntimeParams["application_name"] = "notifier"
	return pgxpool.NewWithConfig(ctx, cfg)
}
