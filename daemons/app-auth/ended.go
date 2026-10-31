package main

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

const (
	// endedRefresh is how often the verifier reads newly ended sessions, so a
	// sign-out reaches header apps within two of them (app-auth-verifier).
	endedRefresh = 5 * time.Second
	// endedLookback re-reads sessions that ended this long before the latest
	// one held. ended_at is the time its transaction began, so a slow commit
	// can land behind a row already read; the set absorbs the repeats.
	endedLookback = time.Minute
)

// endedCache is the verifier's copy of the Keycloak sessions that have ended
// (D8). A failed read keeps the copy it has; until one read has succeeded, it
// is not ready, and no signed-in request passes.
type endedCache struct {
	store store
	now   func() time.Time
	log   *slog.Logger

	mu     sync.RWMutex
	ids    map[string]time.Time // Keycloak session -> when it ended
	latest time.Time
	loaded bool
}

func newEndedCache(st store, now func() time.Time, log *slog.Logger) *endedCache {
	return &endedCache{store: st, now: now, log: log, ids: map[string]time.Time{}}
}

// status reports whether the Keycloak session ksid has ended, and whether the
// cache has ever been read. A session that names none never ends.
func (c *endedCache) status(ksid string) (ended, ready bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if !c.loaded {
		return false, false
	}
	_, ended = c.ids[ksid]
	return ended && ksid != "", true
}

// refresh reads the sessions that ended since the latest it holds, less the
// lookback, and forgets those past endedRetention: no session cookie issued
// from them is still valid.
func (c *endedCache) refresh(ctx context.Context) error {
	c.mu.RLock()
	since := time.Time{}
	if c.loaded {
		since = c.latest.Add(-endedLookback)
	}
	c.mu.RUnlock()
	rows, err := c.store.endedSessions(ctx, since)
	if err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, e := range rows {
		c.ids[e.ID] = e.At
		if e.At.After(c.latest) {
			c.latest = e.At
		}
	}
	cutoff := c.now().Add(-endedRetention)
	for id, at := range c.ids {
		if at.Before(cutoff) {
			delete(c.ids, id)
		}
	}
	c.loaded = true
	return nil
}

func (c *endedCache) run(ctx context.Context) {
	t := time.NewTicker(endedRefresh)
	defer t.Stop()
	for {
		rctx, cancel := context.WithTimeout(ctx, 3*time.Second)
		if err := c.refresh(rctx); err != nil {
			c.log.Warn("reading ended sessions; keeping the copy held", "err", err)
		}
		cancel()
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}
