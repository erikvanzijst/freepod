package main

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// listener wakes the sender: on a notification raised by the outbox's trigger,
// and at least every pollInterval, since notifications sent while it was not
// listening are not kept.
type listener struct {
	dsn            string
	sender         *sender
	pollInterval   time.Duration
	reconnectDelay time.Duration
}

func (l *listener) run(ctx context.Context) {
	for ctx.Err() == nil {
		err := l.listen(ctx)
		if ctx.Err() != nil {
			return
		}
		l.sender.log.Warn("listening for notifications; reconnecting", "err", err, "in", l.reconnectDelay)
		select {
		case <-ctx.Done():
		case <-time.After(l.reconnectDelay):
		}
	}
}

// listen holds one dedicated connection, not a pooled one. LISTEN comes before
// the first sweep, so a row committed during that sweep is either found by it
// or has already queued a wake-up.
func (l *listener) listen(ctx context.Context) error {
	conn, err := pgx.Connect(ctx, l.dsn)
	if err != nil {
		return err
	}
	defer conn.Close(context.WithoutCancel(ctx))
	if _, err := conn.Exec(ctx, "LISTEN "+channel); err != nil {
		return err
	}
	l.sender.log.Info("listening", "channel", channel)
	for {
		if err := l.sender.sweep(ctx); err != nil && ctx.Err() == nil {
			l.sender.log.Warn("sweeping the outbox", "err", err)
		}
		wait, cancel := context.WithTimeout(ctx, l.pollInterval)
		_, err := conn.WaitForNotification(wait)
		cancel()
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err != nil && !errors.Is(err, context.DeadlineExceeded) {
			return err
		}
	}
}
