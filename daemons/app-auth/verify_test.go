package main

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

const (
	milk  = "milk-erik.freepod.app"
	notes = "notes-erik.freepod.app"
	login = "https://login.freepod.eu"
)

var quiet = slog.New(slog.NewTextHandler(io.Discard, nil))

type clock struct{ t time.Time }

func (c *clock) now() time.Time { return c.t }

func newTestVerifier(t *testing.T) (*verifier, *memStore, *clock) {
	t.Helper()
	c := &clock{t: t0}
	st := newMemStore(c.now)
	return &verifier{
		keys: mustKeyring(t, "k1:"+testKey('a')), store: st, loginURL: login,
		now: c.now, log: quiet, patterns: newPatternCache(quiet), allowed: newAllowCache(quiet),
	}, st, c
}

var alice = session{Sub: "3f2a", Email: "alice@example.com", Name: "Alice Ångström"}

func (v *verifier) sessionFor(t *testing.T, s session, host string) string {
	t.Helper()
	s.Host = host
	tok, err := v.keys.seal("session", s, sessionTTL, v.now())
	if err != nil {
		t.Fatal(err)
	}
	return tok
}

func publicParam(patterns ...string) string {
	b, _ := json.Marshal(patterns)
	return base64.RawURLEncoding.EncodeToString(b)
}

// fwd is one forward-auth request as Traefik sends it. `edge` is the rest of
// the middleware's own query string (allowed accounts, application name).
type fwd struct {
	host, method, uri, public string
	edge                      url.Values
	header                    http.Header
}

func (v *verifier) do(f fwd) *httptest.ResponseRecorder {
	q := url.Values{}
	for k, vs := range f.edge {
		q[k] = vs
	}
	if f.public != "" {
		q.Set("p", f.public)
	}
	target := "/verify"
	if len(q) > 0 {
		target += "?" + q.Encode()
	}
	r := httptest.NewRequest("GET", target, nil)
	if f.method == "" {
		f.method = "GET"
	}
	r.Header.Set("X-Forwarded-Host", f.host)
	r.Header.Set("X-Forwarded-Method", f.method)
	r.Header.Set("X-Forwarded-Proto", "https")
	r.Header.Set("X-Forwarded-Uri", f.uri)
	for k, vs := range f.header {
		for _, val := range vs {
			r.Header.Add(k, val)
		}
	}
	w := httptest.NewRecorder()
	v.ServeHTTP(w, r)
	return w
}

func cookieHeader(pairs ...string) http.Header {
	return http.Header{"Cookie": {strings.Join(pairs, "; ")}}
}

func navigate(h http.Header) http.Header {
	if h == nil {
		h = http.Header{}
	}
	h.Set("Sec-Fetch-Mode", "navigate")
	return h
}

func TestSignedInRequestCarriesIdentity(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	w := v.do(fwd{host: milk, uri: "/lists", header: cookieHeader(sessionCookie+"="+v.sessionFor(t, alice, milk), "theme=dark")})

	if w.Code != 200 {
		t.Fatalf("status %d", w.Code)
	}
	want := map[string]string{
		"X-Freepod-User":    "3f2a",
		"Remote-User":       "3f2a",
		"X-Forwarded-User":  "3f2a",
		"X-Freepod-Email":   "alice@example.com",
		"X-Forwarded-Email": "alice@example.com",
		"X-Freepod-Name":    "Alice%20%C3%85ngstr%C3%B6m",
		"Cookie":            "theme=dark",
	}
	for k, val := range want {
		if got := w.Header().Get(k); got != val {
			t.Errorf("%s = %q, want %q", k, got, val)
		}
	}
	if w.Header().Get("X-Freepod-Jwt") != "" {
		t.Error("X-Freepod-Jwt is reserved, not shipped")
	}
}

func TestOnlyTheSessionCookieLeavesNoCookieHeader(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	w := v.do(fwd{host: milk, uri: "/", header: cookieHeader(sessionCookie + "=" + v.sessionFor(t, alice, milk))})
	if w.Code != 200 {
		t.Fatalf("status %d", w.Code)
	}
	if _, ok := w.Header()["Cookie"]; ok {
		t.Fatalf("Cookie = %q, want none so Traefik drops the header", w.Header().Get("Cookie"))
	}
}

func TestSessionValidity(t *testing.T) {
	v, _, c := newTestVerifier(t)
	valid := v.sessionFor(t, alice, milk)
	tampered := []byte(valid)
	tampered[len(tampered)-3] ^= 1

	cases := map[string]struct {
		host   string
		cookie string
		later  time.Duration
	}{
		"replayed on another app":        {notes, valid, 0},
		"expired after seven days":       {milk, valid, sessionTTL + time.Minute},
		"tampered":                       {milk, string(tampered), 0},
		"other environment's keys":       {milk, mustOtherEnvSession(t), 0},
		"flow cookie presented as login": {milk, mustFlowToken(t, v), 0},
	}
	for name, cs := range cases {
		t.Run(name, func(t *testing.T) {
			c.t = t0.Add(cs.later)
			defer func() { c.t = t0 }()
			w := v.do(fwd{host: cs.host, uri: "/api/items", header: cookieHeader(sessionCookie + "=" + cs.cookie)})
			if w.Code != http.StatusUnauthorized {
				t.Fatalf("status %d, want 401", w.Code)
			}
		})
	}
}

func mustOtherEnvSession(t *testing.T) string {
	other := mustKeyring(t, "k1:"+testKey('z'))
	tok, _ := other.seal("session", session{Sub: "3f2a", Host: milk}, sessionTTL, t0)
	return tok
}

func mustFlowToken(t *testing.T, v *verifier) string {
	tok, _ := v.keys.seal("flow", session{Sub: "3f2a", Host: milk}, sessionTTL, t0)
	return tok
}

func TestPublicPaths(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	sess := sessionCookie + "=" + v.sessionFor(t, alice, milk)

	cases := []struct {
		name     string
		public   []string
		uri      string
		cookie   string
		spoof    bool
		wantCode int
		wantUser string
	}{
		{"anonymous landing page", []string{"^/$"}, "/", "", false, 200, ""},
		{"landing page when signed in", []string{"^/$"}, "/", sess, false, 200, "3f2a"},
		{"query cannot make a path public", []string{"^/static/"}, "/admin?x=/static/", "", false, 401, ""},
		{"invalid pattern fails closed", []string{"(?=x)", "^/$"}, "/other", "", false, 401, ""},
		{"valid pattern beside invalid one", []string{"(?=x)", "^/$"}, "/", "", false, 200, ""},
		{"unanchored pattern", []string{"/static/"}, "/app/static/x.css", "", false, 200, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := http.Header{"Sec-Fetch-Mode": {"cors"}}
			if c.cookie != "" {
				h.Set("Cookie", c.cookie)
			}
			w := v.do(fwd{host: milk, uri: c.uri, public: publicParam(c.public...), header: h})
			if w.Code != c.wantCode {
				t.Fatalf("status %d, want %d", w.Code, c.wantCode)
			}
			if got := w.Header().Get("X-Freepod-User"); got != c.wantUser {
				t.Fatalf("X-Freepod-User = %q, want %q", got, c.wantUser)
			}
		})
	}
}

func TestUnauthenticatedProtectedPaths(t *testing.T) {
	v, _, _ := newTestVerifier(t)

	t.Run("browser navigation starts sign-in", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/lists/7?sort=name", header: navigate(nil)})
		if w.Code != http.StatusFound {
			t.Fatalf("status %d", w.Code)
		}
		loc, _ := url.Parse(w.Header().Get("Location"))
		if loc.Scheme != "https" || loc.Host != "login.freepod.eu" || loc.Path != "/start" {
			t.Fatalf("Location %s", loc)
		}
		q := loc.Query()
		if q.Get("host") != milk || q.Get("rd") != "/lists/7?sort=name" {
			t.Fatalf("query %v", q)
		}
		nonce := setCookieValue(t, w, loginCookie)
		if q.Get("n") != hashToken(nonce) {
			t.Fatal("the URL must carry the digest of the login cookie, and only that")
		}
	})

	for name, f := range map[string]fwd{
		"background fetch":           {host: milk, uri: "/api/items", header: http.Header{"Sec-Fetch-Mode": {"cors"}}},
		"form post after expiry":     {host: milk, method: "POST", uri: "/lists", header: navigate(nil)},
		"no fetch metadata, no html": {host: milk, uri: "/api/items", header: http.Header{"Accept": {"application/json"}}},
	} {
		t.Run(name, func(t *testing.T) {
			w := v.do(f)
			if w.Code != http.StatusUnauthorized {
				t.Fatalf("status %d, want 401", w.Code)
			}
			if _, ok := w.Header()["Cookie"]; ok {
				t.Fatal("a refusal must not carry a Cookie header")
			}
		})
	}
}

func setCookieValue(t *testing.T, w *httptest.ResponseRecorder, name string) string {
	t.Helper()
	for _, c := range w.Result().Cookies() {
		if c.Name == name {
			if !c.Secure || !c.HttpOnly || c.SameSite != http.SameSiteLaxMode || c.Path != "/" || c.Domain != "" {
				t.Fatalf("cookie %s has attributes %+v", name, c)
			}
			return c.Value
		}
	}
	t.Fatalf("no Set-Cookie for %s in %v", name, w.Header()["Set-Cookie"])
	return ""
}

func TestReservedPaths(t *testing.T) {
	v, _, _ := newTestVerifier(t)

	t.Run("login honours a same-host return target", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: reservedPrefix + "login?rd=/lists"})
		loc, _ := url.Parse(w.Header().Get("Location"))
		if w.Code != 302 || loc.Query().Get("rd") != "/lists" {
			t.Fatalf("%d %s", w.Code, loc)
		}
	})
	t.Run("open redirect attempt", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: reservedPrefix + "login?rd=//evil.example/"})
		loc, _ := url.Parse(w.Header().Get("Location"))
		if loc.Query().Get("rd") != "/" {
			t.Fatalf("rd = %q", loc.Query().Get("rd"))
		}
	})
	t.Run("logout clears only the session and hands off to the broker", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: reservedPrefix + "logout?rd=/bye"})
		want := login + "/logout?" + url.Values{"host": {milk}, "rd": {"/bye"}}.Encode()
		if w.Code != 302 || w.Header().Get("Location") != want {
			t.Fatalf("%d %s", w.Code, w.Header().Get("Location"))
		}
		cookies := w.Result().Cookies()
		if len(cookies) != 1 || cookies[0].Name != sessionCookie || cookies[0].MaxAge >= 0 {
			t.Fatalf("Set-Cookie %v", w.Header()["Set-Cookie"])
		}
	})
	t.Run("logout open redirect attempt", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: reservedPrefix + "logout?rd=//evil.example/"})
		loc, _ := url.Parse(w.Header().Get("Location"))
		if loc.Query().Get("rd") != "/" || loc.Query().Get("host") != milk {
			t.Fatalf("Location %s", loc)
		}
	})
	t.Run("unknown reserved path", func(t *testing.T) {
		if w := v.do(fwd{host: milk, uri: reservedPrefix + "whatever"}); w.Code != 404 {
			t.Fatalf("status %d", w.Code)
		}
	})
	t.Run("reserved even with a valid session", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: reservedPrefix + "nope", header: cookieHeader(sessionCookie + "=" + v.sessionFor(t, alice, milk))})
		if w.Code != 404 {
			t.Fatalf("status %d; a reserved path must never reach the app", w.Code)
		}
	})
}

// issue plays the broker's part: a code bound to host and to the digest of a
// login cookie, as broker.issueCode stores it.
func issue(t *testing.T, st *memStore, host, nonce, rd string) string {
	t.Helper()
	code := randomToken()
	st.insertCode(t.Context(), sha256Bytes(code), codeRecord{
		Host: host, Subject: alice.Sub, Email: alice.Email, Name: alice.Name, ReturnPath: rd, NonceHash: sha256Bytes(nonce),
	})
	return code
}

func TestCallback(t *testing.T) {
	cb := func(code string) string { return reservedPrefix + "callback?code=" + url.QueryEscape(code) }

	t.Run("normal completion", func(t *testing.T) {
		v, st, _ := newTestVerifier(t)
		code := issue(t, st, milk, "nonce-1", "/lists")
		w := v.do(fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=nonce-1")})
		if w.Code != 302 || w.Header().Get("Location") != "https://"+milk+"/lists" {
			t.Fatalf("%d %s", w.Code, w.Header().Get("Location"))
		}
		tok := setCookieValue(t, w, sessionCookie)
		var s session
		if err := v.keys.open("session", tok, &s, v.now()); err != nil || s.Host != milk || s.Sub != alice.Sub {
			t.Fatalf("session %+v, %v", s, err)
		}
		for _, c := range w.Result().Cookies() {
			if c.Name == loginCookie && c.MaxAge >= 0 {
				t.Fatal("login cookie not cleared")
			}
		}
	})

	fails := map[string]func(v *verifier, st *memStore, c *clock) fwd{
		"replayed code": func(v *verifier, st *memStore, c *clock) fwd {
			code := issue(t, st, milk, "n", "/")
			v.do(fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=n")})
			return fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=n")}
		},
		"code for another host": func(v *verifier, st *memStore, c *clock) fwd {
			return fwd{host: notes, uri: cb(issue(t, st, milk, "n", "/")), header: cookieHeader(loginCookie + "=n")}
		},
		"login csrf: victim has no matching login cookie": func(v *verifier, st *memStore, c *clock) fwd {
			return fwd{host: milk, uri: cb(issue(t, st, milk, "attackers-nonce", "/")), header: cookieHeader(loginCookie + "=victims-nonce")}
		},
		"login csrf: no login cookie at all": func(v *verifier, st *memStore, c *clock) fwd {
			return fwd{host: milk, uri: cb(issue(t, st, milk, "n", "/"))}
		},
		"code 61 seconds old": func(v *verifier, st *memStore, c *clock) fwd {
			code := issue(t, st, milk, "n", "/")
			c.t = c.t.Add(61 * time.Second)
			return fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=n")}
		},
		"no code": func(v *verifier, st *memStore, c *clock) fwd {
			return fwd{host: milk, uri: reservedPrefix + "callback", header: cookieHeader(loginCookie + "=n")}
		},
	}
	for name, setup := range fails {
		t.Run(name, func(t *testing.T) {
			v, st, c := newTestVerifier(t)
			w := v.do(setup(v, st, c))
			if w.Code != http.StatusBadRequest {
				t.Fatalf("status %d", w.Code)
			}
			for _, ck := range w.Result().Cookies() {
				if ck.Name == sessionCookie {
					t.Fatal("a failed redemption set a session")
				}
			}
		})
	}

	t.Run("a rejected presentation still burns the code", func(t *testing.T) {
		v, st, _ := newTestVerifier(t)
		code := issue(t, st, milk, "n", "/")
		v.do(fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=wrong")})
		w := v.do(fwd{host: milk, uri: cb(code), header: cookieHeader(loginCookie + "=n")})
		if w.Code != http.StatusBadRequest {
			t.Fatalf("status %d", w.Code)
		}
	})
}

func TestNotAForwardAuthRequest(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	w := httptest.NewRecorder()
	v.ServeHTTP(w, httptest.NewRequest("GET", "/verify", nil))
	if w.Code != http.StatusBadRequest {
		t.Fatalf("status %d", w.Code)
	}
}

func TestSessionLastsSevenDays(t *testing.T) {
	v, _, c := newTestVerifier(t)
	cookie := sessionCookie + "=" + v.sessionFor(t, alice, milk)
	c.t = t0.Add(7*24*time.Hour - time.Minute)
	if w := v.do(fwd{host: milk, uri: "/api/items", header: cookieHeader(cookie)}); w.Code != 200 {
		t.Fatalf("status %d a minute before the week is up", w.Code)
	}
}

func allowedParam(emails ...string) string {
	b, _ := json.Marshal(emails)
	return base64.RawURLEncoding.EncodeToString(b)
}

func TestAllowedAccounts(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	aliceSession := sessionCookie + "=" + v.sessionFor(t, session{Sub: "3f2a", Email: "Alice@Example.com", Name: "Alice"}, milk)
	bobSession := sessionCookie + "=" + v.sessionFor(t, session{Sub: "9c1d", Email: "bob@example.com", Name: "Bob"}, milk)
	onlyAlice := url.Values{"a": {allowedParam("alice@example.com")}}

	t.Run("allowed account, matched case-insensitively", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/lists", edge: onlyAlice, header: cookieHeader(aliceSession)})
		if w.Code != 200 || w.Header().Get("X-Freepod-User") != "3f2a" {
			t.Fatalf("status %d user %q", w.Code, w.Header().Get("X-Freepod-User"))
		}
	})

	t.Run("other account, not a navigation", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/api/lists", edge: onlyAlice, header: cookieHeader(bobSession)})
		if w.Code != http.StatusForbidden || w.Header().Get("X-Freepod-User") != "" || strings.Contains(w.Body.String(), "<html") {
			t.Fatalf("status %d user %q body %q", w.Code, w.Header().Get("X-Freepod-User"), w.Body)
		}
	})

	t.Run("other account, navigation gets the named page", func(t *testing.T) {
		edge := url.Values{"a": onlyAlice["a"], "n": {"App Studio"}}
		w := v.do(fwd{host: milk, uri: "/lists", edge: edge, header: navigate(cookieHeader(bobSession))})
		body := w.Body.String()
		if w.Code != http.StatusForbidden || w.Header().Get("X-Freepod-User") != "" {
			t.Fatalf("status %d", w.Code)
		}
		for _, want := range []string{"You don't have access to App Studio", "App Studio at", "https://" + milk, "bob@example.com",
			"https://" + milk + reservedPrefix + "logout?rd=/"} {
			if !strings.Contains(body, want) {
				t.Errorf("page lacks %q", want)
			}
		}
		if csp := w.Header().Get("Content-Security-Policy"); !strings.Contains(csp, "default-src 'none'") || !strings.Contains(csp, "style-src 'sha256-") {
			t.Errorf("CSP %q", csp)
		}
	})

	t.Run("unnamed application shows its address once", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/", edge: onlyAlice, header: navigate(cookieHeader(bobSession))})
		body := w.Body.String()
		if w.Code != http.StatusForbidden || !strings.Contains(body, "have access to "+milk) || strings.Contains(body, milk+" at ") {
			t.Fatalf("status %d body %s", w.Code, body)
		}
	})

	t.Run("public path does not admit another account", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/", public: publicParam("^/$"), edge: onlyAlice, header: cookieHeader(bobSession)})
		if w.Code != http.StatusForbidden || w.Header().Get("X-Freepod-User") != "" {
			t.Fatalf("status %d user %q", w.Code, w.Header().Get("X-Freepod-User"))
		}
	})

	t.Run("anonymous public path still reaches the app", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/", public: publicParam("^/$"), edge: onlyAlice})
		if w.Code != 200 || w.Header().Get("X-Freepod-User") != "" {
			t.Fatalf("status %d user %q", w.Code, w.Header().Get("X-Freepod-User"))
		}
	})

	t.Run("anonymous protected path signs in as usual", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/lists", edge: onlyAlice, header: navigate(nil)})
		if w.Code != http.StatusFound || !strings.HasPrefix(w.Header().Get("Location"), login+"/start?") {
			t.Fatalf("status %d Location %q", w.Code, w.Header().Get("Location"))
		}
	})

	for name, key := range map[string]string{
		"corrupt list":   "not-base64!",
		"not a list":     base64.RawURLEncoding.EncodeToString([]byte(`{"alice@example.com":true}`)),
		"empty value":    "",
		"list of nobody": allowedParam(),
	} {
		t.Run(name+" admits nobody", func(t *testing.T) {
			w := v.do(fwd{host: milk, uri: "/lists", edge: url.Values{"a": {key}}, header: cookieHeader(aliceSession)})
			if w.Code != http.StatusForbidden {
				t.Fatalf("status %d", w.Code)
			}
		})
	}

	t.Run("no list admits every account", func(t *testing.T) {
		w := v.do(fwd{host: milk, uri: "/lists", header: cookieHeader(bobSession)})
		if w.Code != 200 || w.Header().Get("X-Freepod-User") != "9c1d" {
			t.Fatalf("status %d", w.Code)
		}
	})
}

func TestRequestsFromOtherOriginsAreNotIdentified(t *testing.T) {
	v, _, _ := newTestVerifier(t)
	sess := sessionCookie + "=" + v.sessionFor(t, alice, milk)

	cases := []struct {
		name     string
		method   string
		header   http.Header
		public   bool
		wantCode int
		wantUser string
	}{
		{"same-origin POST", "POST", http.Header{"Sec-Fetch-Site": {"same-origin"}}, false, 200, "3f2a"},
		{"non-browser POST", "POST", nil, false, 200, "3f2a"},
		{"same-site POST", "POST", http.Header{"Sec-Fetch-Site": {"same-site"}}, false, 401, ""},
		{"cross-site DELETE", "DELETE", http.Header{"Sec-Fetch-Site": {"cross-site"}}, false, 401, ""},
		{"other Origin without Sec-Fetch-Site", "PUT", http.Header{"Origin": {"https://" + notes}}, false, 401, ""},
		{"own Origin without Sec-Fetch-Site", "PUT", http.Header{"Origin": {"https://" + milk}}, false, 200, "3f2a"},
		{"same-site GET", "GET", http.Header{"Sec-Fetch-Site": {"same-site"}, "Sec-Fetch-Mode": {"cors"}}, false, 200, "3f2a"},
		{"same-site WebSocket", "GET", http.Header{"Sec-Fetch-Site": {"same-site"}, "Sec-Fetch-Mode": {"websocket"}, "Sec-WebSocket-Key": {"k"}}, false, 401, ""},
		{"WebSocket from another Origin", "GET", http.Header{"Origin": {"https://" + notes}, "Sec-WebSocket-Key": {"k"}}, false, 401, ""},
		{"same-origin WebSocket", "GET", http.Header{"Sec-Fetch-Site": {"same-origin"}, "Sec-WebSocket-Key": {"k"}}, false, 200, "3f2a"},
		{"same-site POST to a public path", "POST", http.Header{"Sec-Fetch-Site": {"same-site"}}, true, 200, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := http.Header{"Cookie": {sess}}
			for k, vs := range c.header {
				h[k] = vs
			}
			f := fwd{host: milk, method: c.method, uri: "/api/items", header: h}
			if c.public {
				f.public = publicParam("^/api/")
			}
			w := v.do(f)
			if w.Code != c.wantCode {
				t.Fatalf("status %d, want %d", w.Code, c.wantCode)
			}
			if got := w.Header().Get("X-Freepod-User"); got != c.wantUser {
				t.Fatalf("X-Freepod-User = %q, want %q", got, c.wantUser)
			}
		})
	}
}
