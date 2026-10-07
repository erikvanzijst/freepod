package main

import (
	"context"
	"slices"
	"sync"
	"time"
)

// memStore is the store contract in memory, for handler tests. The SQL behind
// the same contract is exercised against the real schema in store_test.go.
type memStore struct {
	mu       sync.Mutex
	now      func() time.Time
	hosts    map[string]string // host -> deployment id, auth-enabled only
	consents map[[2]string][]string
	codes    map[string]memCode
}

type memCode struct {
	rec     codeRecord
	expires time.Time
}

func newMemStore(now func() time.Time) *memStore {
	return &memStore{now: now, hosts: map[string]string{}, consents: map[[2]string][]string{}, codes: map[string]memCode{}}
}

func (m *memStore) eligible(_ context.Context, host string) (string, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.hosts[host]
	return id, ok, nil
}

func (m *memStore) hasConsent(_ context.Context, sub, dep string, claims []string) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	have, ok := m.consents[[2]string{sub, dep}]
	if !ok {
		return false, nil
	}
	for _, c := range claims {
		if !slices.Contains(have, c) {
			return false, nil
		}
	}
	return true, nil
}

func (m *memStore) recordConsent(_ context.Context, sub, dep string, claims []string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.consents[[2]string{sub, dep}] = slices.Clone(claims)
	return nil
}

func (m *memStore) insertCode(_ context.Context, h []byte, c codeRecord) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.codes[string(h)] = memCode{rec: c, expires: m.now().Add(codeTTL)}
	return nil
}

func (m *memStore) redeemCode(_ context.Context, h []byte) (codeRecord, bool, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	c, ok := m.codes[string(h)]
	if !ok {
		return codeRecord{}, false, false, nil
	}
	delete(m.codes, string(h))
	return c.rec, m.now().Before(c.expires), true, nil
}

func (m *memStore) purgeExpiredCodes(context.Context) (int64, error) { return 0, nil }
