package main

import (
	"context"
	"log/slog"
	"strings"
	"sync"
	"time"
)

// admit is D3 against one copy of a deployment's access list: the owner by
// email, then an entry bound to sub, then an unbound entry with this email,
// which it returns for the caller to bind. An entry bound to another subject
// admits nobody else, whatever their email.
func (l accessList) admit(sub, email string) (ok bool, bindID string) {
	if email != "" && strings.EqualFold(email, l.OwnerEmail) {
		return true, ""
	}
	for _, e := range l.Entries {
		if sub != "" && e.Subject == sub {
			return true, ""
		}
	}
	for _, e := range l.Entries {
		if e.Subject == "" && email != "" && strings.EqualFold(e.Email, email) {
			return true, e.ID
		}
	}
	return false, ""
}

// admitted applies a listed deployment's access list to id. With bind, it ties
// the unbound entry id matched to id's subject, as only issuing a code may.
func admitted(ctx context.Context, st store, deploymentID string, id identity, bind bool) (bool, error) {
	l, err := st.accessList(ctx, deploymentID)
	if err != nil {
		return false, err
	}
	ok, entry := l.admit(id.Sub, id.Email)
	if !ok || !bind || entry == "" {
		return ok, nil
	}
	bound, err := st.bindEntry(ctx, entry, id.Sub, id.Name)
	if err != nil || bound {
		return bound, err
	}
	// Bound by someone else in the meantime: it still admits id only if that
	// someone was id, signing in twice at once.
	if l, err = st.accessList(ctx, deploymentID); err != nil {
		return false, err
	}
	ok, entry = l.admit(id.Sub, id.Email)
	return ok && entry == "", nil
}

const (
	// accessTTL bounds how stale a list may be while the database answers (D7).
	accessTTL = 30 * time.Second
	// accessRecheck is how old a list may be before a refusal reads it again,
	// so someone added a moment ago is not turned away.
	accessRecheck = 5 * time.Second
)

// accessCache holds each listed host's access list for the verifier, so a
// request reads the database at most every accessTTL per host. Keyed by the
// request host, so one load both resolves the host, preview aliases included,
// and reads its list. A failed read keeps the copy it has, however old; a
// host never read admits nobody (app-auth-verifier).
type accessCache struct {
	store        store
	tenantDomain string
	now          func() time.Time
	log          *slog.Logger

	mu     sync.Mutex
	byHost map[string]cachedAccess
}

type cachedAccess struct {
	list   accessList
	loaded time.Time
}

func newAccessCache(st store, tenantDomain string, now func() time.Time, log *slog.Logger) *accessCache {
	return &accessCache{store: st, tenantDomain: tenantDomain, now: now, log: log, byHost: map[string]cachedAccess{}}
}

func (c *accessCache) admits(ctx context.Context, host string, s session) bool {
	held, have := c.cached(host)
	read := false
	if !have || c.now().Sub(held.loaded) >= accessTTL {
		held, have = c.load(ctx, host)
		read = true
	}
	if ok, _ := held.list.admit(s.Sub, s.Email); have && ok {
		return true
	}
	if read || (have && c.now().Sub(held.loaded) <= accessRecheck) {
		return false
	}
	held, have = c.load(ctx, host)
	ok, _ := held.list.admit(s.Sub, s.Email)
	return have && ok
}

func (c *accessCache) cached(host string) (cachedAccess, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.byHost[host]
	return e, ok
}

// load reads host's list afresh, or returns the copy already held when the
// database does not answer. A host that is no longer a header app has an
// empty list and no owner, so it admits nobody.
func (c *accessCache) load(ctx context.Context, host string) (cachedAccess, bool) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	var list accessList
	app, ok, err := resolveHeaderApp(ctx, c.store, host, c.tenantDomain)
	if err == nil && ok {
		list, err = c.store.accessList(ctx, app.ID)
	}
	if err != nil {
		c.log.Warn("reading an access list; keeping the copy held", "host", host, "err", err)
		return c.cached(host)
	}
	e := cachedAccess{list: list, loaded: c.now()}
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.byHost) >= patternCacheLimit {
		c.byHost = map[string]cachedAccess{}
	}
	c.byHost[host] = e
	return e, true
}
