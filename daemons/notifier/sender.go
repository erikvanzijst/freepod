package main

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	maxAttempts = 3
	channel     = "notification_outbox"
)

// deliverer is the transport; the relay in production.
type deliverer interface {
	deliver(id, to string, m message) error
}

type sender struct {
	pool *pgxpool.Pool
	// nil means this environment delivers nothing: rows become suppressed.
	transport  deliverer
	retryPause time.Duration
	log        *slog.Logger
}

// The timestamp columns are naive UTC, as everywhere in the platform schema.
const nowUTC = `(now() AT TIME ZONE 'utc')`

// sweep delivers pending notifications, oldest first, until none is left or
// ctx ends. Each row is claimed, delivered and recorded in its own
// transaction, holding the row's lock throughout, so concurrent senders never
// take the same row and a crash leaves it pending.
func (s *sender) sweep(ctx context.Context) error {
	for ctx.Err() == nil {
		done, err := s.next(ctx)
		if err != nil || done {
			return err
		}
	}
	return nil
}

// next handles one pending row, and reports whether there was none.
func (s *sender) next(ctx context.Context) (bool, error) {
	// The claim's own work is not cut short by shutdown: a delivery that has
	// started is recorded, so it is not repeated.
	work := context.WithoutCancel(ctx)
	tx, err := s.pool.Begin(work)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(work)

	var id, to string
	var m message
	err = tx.QueryRow(work, `
		SELECT o.id::text, coalesce(o.recipient_email, u.email, ''), o.subject, coalesce(o.heading, ''),
		       o.body, coalesce(o.action_label, ''), coalesce(o.action_url, ''), o.reason
		  FROM notification_outbox o
		  LEFT JOIN "user" u ON u.id = o.recipient_user_id
		 WHERE o.state = 'pending'
		 ORDER BY o.created_at
		 LIMIT 1
		   FOR UPDATE OF o SKIP LOCKED`,
	).Scan(&id, &to, &m.Subject, &m.Heading, &m.Body, &m.ActionLabel, &m.ActionURL, &m.Reason)
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil
	}
	if err != nil {
		return false, err
	}

	switch {
	case s.transport == nil:
		_, err = tx.Exec(work, `UPDATE notification_outbox SET state = 'suppressed' WHERE id = $1::uuid`, id)
		s.log.Info("suppressed: no relay configured", "id", id)
	case to == "":
		_, err = tx.Exec(work, `
			UPDATE notification_outbox SET state = 'failed', error = 'the recipient user has no email address'
			 WHERE id = $1::uuid`, id)
		s.log.Warn("failed: no address", "id", id)
	default:
		attempts, sendErr := s.attempt(ctx, id, to, m)
		if attempts == 0 {
			return false, ctx.Err()
		}
		if sendErr == nil {
			_, err = tx.Exec(work, `
				UPDATE notification_outbox
				   SET state = 'sent', attempts = attempts + $2, last_attempt_at = `+nowUTC+`,
				       sent_at = `+nowUTC+`, error = NULL
				 WHERE id = $1::uuid`, id, attempts)
			s.log.Info("sent", "id", id, "attempts", attempts)
		} else {
			_, err = tx.Exec(work, `
				UPDATE notification_outbox
				   SET state = 'failed', attempts = attempts + $2, last_attempt_at = `+nowUTC+`, error = $3
				 WHERE id = $1::uuid`, id, attempts, sendErr.Error())
			s.log.Warn("failed", "id", id, "attempts", attempts, "err", sendErr)
		}
	}
	if err != nil {
		return false, err
	}
	return false, tx.Commit(work)
}

// attempt tries up to maxAttempts times, a pause apart. It returns how many
// attempts it made and the last error, or zero attempts when shutdown came
// first: the row then stays pending for the next sender.
func (s *sender) attempt(ctx context.Context, id, to string, m message) (int, error) {
	var err error
	for n := 1; n <= maxAttempts; n++ {
		if ctx.Err() != nil {
			return 0, nil
		}
		if err = s.transport.deliver(id, to, m); err == nil {
			return n, nil
		}
		if n < maxAttempts {
			select {
			case <-ctx.Done():
				return 0, nil
			case <-time.After(s.retryPause):
			}
		}
	}
	return maxAttempts, err
}
