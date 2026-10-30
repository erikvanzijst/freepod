package main

import (
	"context"
	"encoding/json"
	"slices"
	"sync"
	"time"
)

// memStore is the store contract in memory, for handler tests. The SQL behind
// the same contract is exercised against the real schema in store_test.go.
type memStore struct {
	mu      sync.Mutex
	now     func() time.Time
	hosts   map[string]string // host -> deployment id, auth-enabled only
	listed  map[string]bool   // deployment id -> `auth.access: listed`
	owners  map[string]string // deployment id -> owner's email
	entries map[string][]accessEntry
	names   map[string]string // entry id -> name it was bound with
	// accessErr fails every accessList read, as a database outage does.
	accessErr error
	// accessReads counts accessList calls.
	accessReads int
	consents    map[[2]string][]string
	codes       map[string]memCode
	// clients are SSO-enabled deployments by ID, as their template declares them.
	clients   map[string]memClient
	oidcCodes map[string]memOIDCCode
}

type memClient struct {
	host           string
	paths, natives string // JSON, as the template's system values hold them
	pkceOptOut     bool
	listed         bool
}

type memOIDCCode struct {
	rec     oidcCode
	expires time.Time
}

type memCode struct {
	rec     codeRecord
	expires time.Time
}

func newMemStore(now func() time.Time) *memStore {
	return &memStore{now: now, hosts: map[string]string{}, consents: map[[2]string][]string{}, codes: map[string]memCode{},
		clients: map[string]memClient{}, oidcCodes: map[string]memOIDCCode{},
		listed: map[string]bool{}, owners: map[string]string{}, entries: map[string][]accessEntry{}, names: map[string]string{}}
}

func (m *memStore) eligible(_ context.Context, host string) (headerApp, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.hosts[host]
	if !ok {
		return headerApp{}, false, nil
	}
	return headerApp{ID: id, Listed: m.listed[id]}, true, nil
}

func (m *memStore) accessList(_ context.Context, dep string) (accessList, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.accessReads++
	if m.accessErr != nil {
		return accessList{}, m.accessErr
	}
	return accessList{OwnerEmail: m.owners[dep], Entries: slices.Clone(m.entries[dep])}, nil
}

func (m *memStore) bindEntry(_ context.Context, entryID, sub, name string) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for dep, es := range m.entries {
		for i, e := range es {
			if e.ID == entryID && e.Subject == "" {
				es[i].Subject = sub
				m.entries[dep] = es
				m.names[entryID] = name
				return true, nil
			}
		}
	}
	return false, nil
}

// list puts an entry on a deployment's list, bound when sub is set.
func (m *memStore) list(dep, id, email, sub string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.entries[dep] = append(m.entries[dep], accessEntry{ID: id, Email: email, Subject: sub})
}

// unlist removes an entry, as the owner does through the API.
func (m *memStore) unlist(dep, id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.entries[dep] = slices.DeleteFunc(m.entries[dep], func(e accessEntry) bool { return e.ID == id })
}

func (m *memStore) entry(dep, id string) accessEntry {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range m.entries[dep] {
		if e.ID == id {
			return e
		}
	}
	return accessEntry{}
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

func (m *memStore) ssoClient(_ context.Context, id string) (ssoClient, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	mc, ok := m.clients[id]
	if !ok {
		return ssoClient{}, false, nil
	}
	c, ok := newSSOClient(id, mc.host, json.RawMessage(mc.paths), json.RawMessage(mc.natives), !mc.pkceOptOut)
	c.Listed = mc.listed
	return c, ok, nil
}

func (m *memStore) insertOIDCCode(_ context.Context, h []byte, c oidcCode) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.oidcCodes[string(h)] = memOIDCCode{rec: c, expires: m.now().Add(codeTTL)}
	return nil
}

func (m *memStore) redeemOIDCCode(_ context.Context, h []byte) (oidcCode, bool, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	c, ok := m.oidcCodes[string(h)]
	if !ok {
		return oidcCode{}, false, false, nil
	}
	delete(m.oidcCodes, string(h))
	return c.rec, m.now().Before(c.expires), true, nil
}
