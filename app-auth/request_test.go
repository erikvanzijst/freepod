package main

import (
	"net/http"
	"testing"
)

func TestSafeReturnPath(t *testing.T) {
	cases := map[string]string{
		"/lists/7?sort=name": "/lists/7?sort=name",
		"/":                  "/",
		"":                   "/",
		"//evil.example/":    "/",
		"/\\evil.example":    "/",
		"\\\\evil.example":   "/",
		"https://evil/":      "/",
		"evil":               "/",
		"/a\r\nSet-Cookie:x": "/",
		"/a\\b":              "/",
		"/%2F%2Fevil":        "/%2F%2Fevil", // stays a path on this host
	}
	for in, want := range cases {
		if got := safeReturnPath(in); got != want {
			t.Errorf("safeReturnPath(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFilterCookies(t *testing.T) {
	cases := []struct {
		name  string
		lines []string
		want  string
	}{
		{"session among app cookies", []string{"__Host-freepod_session=abc; theme=dark"}, "theme=dark"},
		{"only the session", []string{"__Host-freepod_session=abc"}, ""},
		{"split across lines", []string{"theme=dark", "__Host-freepod_session=abc"}, "theme=dark"},
		{"every platform cookie", []string{"__Host-freepod_login=n; a=1; __Host-freepod_session=s; b=2"}, "a=1; b=2"},
		{"values kept verbatim", []string{`x="quoted value"; y=a=b`}, `x="quoted value"; y=a=b`},
		{"none", nil, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := http.Header{}
			for _, l := range c.lines {
				h.Add("Cookie", l)
			}
			if got := filterCookies(h); got != c.want {
				t.Fatalf("got %q, want %q", got, c.want)
			}
		})
	}
}

func TestIsNavigation(t *testing.T) {
	cases := []struct {
		method, mode, accept string
		want                 bool
	}{
		{"GET", "navigate", "", true},
		{"HEAD", "navigate", "", true},
		{"GET", "cors", "text/html", false},
		{"GET", "", "text/html,application/xhtml+xml", true},
		{"GET", "", "application/json", false},
		{"POST", "navigate", "text/html", false},
	}
	for _, c := range cases {
		h := http.Header{}
		if c.mode != "" {
			h.Set("Sec-Fetch-Mode", c.mode)
		}
		if c.accept != "" {
			h.Set("Accept", c.accept)
		}
		if got := isNavigation(c.method, h); got != c.want {
			t.Errorf("%s mode=%q accept=%q: got %v", c.method, c.mode, c.accept, got)
		}
	}
}

func TestNormalizeHost(t *testing.T) {
	for in, want := range map[string]string{"Milk.Erik.Freepod.EU": "milk.erik.freepod.eu", "milk.example:443": "milk.example", " a.b ": "a.b"} {
		if got := normalizeHost(in); got != want {
			t.Errorf("normalizeHost(%q) = %q", in, got)
		}
	}
}
