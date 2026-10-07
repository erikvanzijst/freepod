package main

import (
	"encoding/base64"
	"strings"
	"testing"
	"time"
)

func testKey(fill byte) string {
	return base64.StdEncoding.EncodeToString([]byte(strings.Repeat(string(rune(fill)), 32)))
}

func mustKeyring(t *testing.T, spec string) *keyring {
	t.Helper()
	kr, err := parseKeyring(spec)
	if err != nil {
		t.Fatal(err)
	}
	return kr
}

var t0 = time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC)

func TestSealRoundTrip(t *testing.T) {
	kr := mustKeyring(t, "k1:"+testKey('a'))
	tok, err := kr.seal("session", session{Sub: "3f2a", Host: "milk.example"}, time.Hour, t0)
	if err != nil {
		t.Fatal(err)
	}
	var s session
	if err := kr.open("session", tok, &s, t0.Add(59*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if s.Sub != "3f2a" || s.Host != "milk.example" {
		t.Fatalf("got %+v", s)
	}
}

func TestSealRejects(t *testing.T) {
	kr := mustKeyring(t, "k1:"+testKey('a'))
	tok, _ := kr.seal("session", session{Sub: "3f2a"}, 12*time.Hour, t0)

	tampered := []byte(tok)
	tampered[len(tampered)-5] ^= 1

	cases := map[string]struct {
		kr      *keyring
		purpose string
		tok     string
		at      time.Time
	}{
		"expired":       {kr, "session", tok, t0.Add(12*time.Hour + time.Minute)},
		"tampered":      {kr, "session", string(tampered), t0},
		"wrong purpose": {kr, "flow", tok, t0},
		"unknown key":   {mustKeyring(t, "k2:"+testKey('a')), "session", tok, t0},
		"other secret":  {mustKeyring(t, "k1:"+testKey('b')), "session", tok, t0},
		"garbage":       {kr, "session", "k1.!!!", t0},
		"no key id":     {kr, "session", "nodot", t0},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			var s session
			if err := c.kr.open(c.purpose, c.tok, &s, c.at); err == nil {
				t.Fatal("opened")
			}
		})
	}
}

func TestSealRotation(t *testing.T) {
	old := mustKeyring(t, "k1:"+testKey('a'))
	rotated := mustKeyring(t, "k2:"+testKey('b')+",k1:"+testKey('a'))

	tok, _ := old.seal("session", session{Sub: "x"}, time.Hour, t0)
	var s session
	if err := rotated.open("session", tok, &s, t0); err != nil {
		t.Fatalf("previous key no longer accepted: %v", err)
	}
	fresh, _ := rotated.seal("session", session{Sub: "y"}, time.Hour, t0)
	if !strings.HasPrefix(fresh, "k2.") {
		t.Fatalf("sealed with %q, want the current key", fresh[:3])
	}
}

func TestParseKeyring(t *testing.T) {
	for _, bad := range []string{"", "k1", "k1:" + base64.StdEncoding.EncodeToString([]byte("short")), "k1:" + testKey('a') + ",k1:" + testKey('b'), "k.1:" + testKey('a')} {
		if _, err := parseKeyring(bad); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
}
