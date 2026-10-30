package main

import (
	"context"
	"testing"
)

func TestAdmit(t *testing.T) {
	l := accessList{OwnerEmail: "Owner@Example.com", Entries: []accessEntry{
		{ID: "e-ana", Email: "ana@example.com", Subject: "s-ana"},
		{ID: "e-jules", Email: "jules@example.org"},
	}}
	for name, c := range map[string]struct {
		sub, email string
		ok         bool
		bind       string
	}{
		"owner":                       {"s-owner", "owner@example.com", true, ""},
		"owner in another case":       {"s-owner", "OWNER@example.COM", true, ""},
		"bound subject":               {"s-ana", "ana@example.com", true, ""},
		"bound subject, new address":  {"s-ana", "ana@elsewhere.example", true, ""},
		"unbound email":               {"s-jules", "Jules@Example.org", true, "e-jules"},
		"email bound to someone else": {"s-impostor", "ana@example.com", false, ""},
		"stranger":                    {"s-bob", "bob@example.com", false, ""},
		"no identity":                 {"", "", false, ""},
	} {
		t.Run(name, func(t *testing.T) {
			ok, bind := l.admit(c.sub, c.email)
			if ok != c.ok || bind != c.bind {
				t.Fatalf("admit = %v, %q; want %v, %q", ok, bind, c.ok, c.bind)
			}
		})
	}
}

func TestAdmittedBinds(t *testing.T) {
	ctx := context.Background()
	st := newMemStore(nil)
	st.owners["dep"] = "owner@example.com"
	st.list("dep", "e-jules", "jules@example.org", "")
	jules := identity{Sub: "s-jules", Email: "jules@example.org", Name: "Jules"}

	if ok, _ := admitted(ctx, st, "dep", jules, false); !ok || st.entry("dep", "e-jules").Subject != "" {
		t.Fatal("a check without bind bound the entry, or refused")
	}
	if ok, _ := admitted(ctx, st, "dep", jules, true); !ok || st.entry("dep", "e-jules").Subject != "s-jules" || st.names["e-jules"] != "Jules" {
		t.Fatalf("not bound: %+v", st.entry("dep", "e-jules"))
	}
	impostor := identity{Sub: "s-other", Email: "jules@example.org"}
	if ok, _ := admitted(ctx, st, "dep", impostor, true); ok {
		t.Fatal("a second subject with the bound email was admitted")
	}
}

// lostRace reads the entry unbound the first time and finds it bound to
// winner afterwards, as a sign-in does that loses its bind to another.
type lostRace struct {
	*memStore
	winner string
	reads  int
}

func (r *lostRace) accessList(ctx context.Context, dep string) (accessList, error) {
	r.reads++
	sub := ""
	if r.reads > 1 {
		sub = r.winner
	}
	return accessList{Entries: []accessEntry{{ID: "e-jules", Email: "jules@example.org", Subject: sub}}}, nil
}

func (r *lostRace) bindEntry(context.Context, string, string, string) (bool, error) {
	return false, nil
}

func TestBindLostToAConcurrentSignIn(t *testing.T) {
	ctx := context.Background()
	jules := identity{Sub: "s-jules", Email: "jules@example.org"}
	if ok, _ := admitted(ctx, &lostRace{memStore: newMemStore(nil), winner: "s-jules"}, "dep", jules, true); !ok {
		t.Fatal("refused after the same subject bound the entry in another browser")
	}
	if ok, _ := admitted(ctx, &lostRace{memStore: newMemStore(nil), winner: "s-other"}, "dep", jules, true); ok {
		t.Fatal("admitted after another subject bound the entry")
	}
}
