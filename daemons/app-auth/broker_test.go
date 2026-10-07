package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

// fakeAuth stands in for Keycloak in the handler tests; the real exchange is
// covered against a stub provider in oidc_test.go.
type fakeAuth struct {
	id          identity
	err         error
	endSessions int
}

func (f *fakeAuth) authURL(state, nonce, verifier string) (string, error) {
	return "https://keycloak.example/auth?" + url.Values{"state": {state}}.Encode(), nil
}

func (f *fakeAuth) endSessionURL(state, postLogoutRedirect string) (string, error) {
	f.endSessions++
	return "https://keycloak.example/logout?" + url.Values{"state": {state}, "post_logout_redirect_uri": {postLogoutRedirect}}.Encode(), nil
}

func (f *fakeAuth) exchange(context.Context, string, string, string) (identity, error) {
	return f.id, f.err
}

type brokerRig struct {
	t     *testing.T
	b     *broker
	st    *memStore
	auth  *fakeAuth
	clock *clock
	jar   map[string]string // the login host's cookies in the browser
	nonce string            // the app host's login cookie
}

func newBrokerRig(t *testing.T) *brokerRig {
	t.Helper()
	c := &clock{t: t0}
	st := newMemStore(c.now)
	st.hosts[milk] = "dep-milk"
	auth := &fakeAuth{id: identity{Sub: "3f2a", Email: "alice@example.com", Name: "Alice"}}
	return &brokerRig{
		t: t, st: st, auth: auth, clock: c, jar: map[string]string{}, nonce: "app-host-nonce",
		b: &broker{loginURL: login, keys: mustKeyring(t, "k1:"+testKey('a')), store: st, auth: auth, now: c.now, log: quiet},
	}
}

func (g *brokerRig) do(method, target string, form url.Values) *httptest.ResponseRecorder {
	var r *http.Request
	if form != nil {
		r = httptest.NewRequest(method, target, strings.NewReader(form.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	} else {
		r = httptest.NewRequest(method, target, nil)
	}
	var pairs []string
	for k, v := range g.jar {
		pairs = append(pairs, k+"="+v)
	}
	if len(pairs) > 0 {
		r.Header.Set("Cookie", strings.Join(pairs, "; "))
	}
	w := httptest.NewRecorder()
	g.b.routes().ServeHTTP(w, r)
	for _, c := range w.Result().Cookies() {
		if c.MaxAge < 0 {
			delete(g.jar, c.Name)
		} else {
			g.jar[c.Name] = c.Value
		}
	}
	return w
}

func (g *brokerRig) start(host string) *httptest.ResponseRecorder {
	q := url.Values{"host": {host}, "rd": {"/lists"}, "n": {hashToken(g.nonce)}}
	return g.do("GET", "/start?"+q.Encode(), nil)
}

// returnFromIdP follows the broker's redirect to the IdP and comes back with
// the state it was given.
func (g *brokerRig) returnFromIdP(start *httptest.ResponseRecorder) *httptest.ResponseRecorder {
	loc, _ := url.Parse(start.Header().Get("Location"))
	return g.do("GET", "/callback?"+url.Values{"code": {"idp-code"}, "state": {loc.Query().Get("state")}}.Encode(), nil)
}

func formValue(t *testing.T, body, name string) string {
	t.Helper()
	i := strings.Index(body, `name="`+name+`" value="`)
	if i < 0 {
		t.Fatalf("no %s field in page", name)
	}
	rest := body[i+len(`name="`+name+`" value="`):]
	return rest[:strings.Index(rest, `"`)]
}

// redeemable checks a broker redirect points at the app host's callback with
// a code bound to that host, the return target, and the login cookie.
func (g *brokerRig) redeemable(w *httptest.ResponseRecorder, host string) {
	g.t.Helper()
	if w.Code != http.StatusFound {
		g.t.Fatalf("status %d: %s", w.Code, w.Body)
	}
	loc, _ := url.Parse(w.Header().Get("Location"))
	if loc.Scheme != "https" || loc.Host != host || loc.Path != reservedPrefix+"callback" {
		g.t.Fatalf("Location %s", loc)
	}
	code := loc.Query().Get("code")
	if len(code) < 43 {
		g.t.Fatalf("code %q is shorter than 256 random bits encode to", code)
	}
	rec, fresh, found, _ := g.st.redeemCode(context.Background(), sha256Bytes(code))
	if !found || !fresh || rec.Host != host || rec.ReturnPath != "/lists" || string(rec.NonceHash) != string(sha256Bytes(g.nonce)) || rec.Subject != "3f2a" {
		g.t.Fatalf("code record %+v (found=%v fresh=%v)", rec, found, fresh)
	}
}

func TestBrokerFirstVisitAsksForConsent(t *testing.T) {
	g := newBrokerRig(t)
	start := g.start(milk)
	if start.Code != http.StatusFound || !strings.HasPrefix(start.Header().Get("Location"), "https://keycloak.example/") {
		t.Fatalf("start: %d %s", start.Code, start.Header().Get("Location"))
	}
	page := g.returnFromIdP(start)
	if page.Code != 200 {
		t.Fatalf("callback: %d", page.Code)
	}
	body := page.Body.String()
	for _, want := range []string{milk, "run by a Freepod user, not by Freepod", "Your name", "Alice", "Your email address", "alice@example.com", "permanent account identifier"} {
		if !strings.Contains(body, want) {
			t.Errorf("consent page lacks %q", want)
		}
	}
	if len(g.st.codes) != 0 {
		t.Fatal("a code was issued before consent")
	}

	w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, body, "csrf")}, "decision": {"allow"}})
	g.redeemable(w, milk)
	if ok, _ := g.st.hasConsent(context.Background(), "3f2a", "dep-milk", disclosedClaims); !ok {
		t.Fatal("consent not recorded")
	}
}

func TestBrokerReturningVisitSkipsConsent(t *testing.T) {
	g := newBrokerRig(t)
	g.st.recordConsent(context.Background(), "3f2a", "dep-milk", disclosedClaims)
	g.redeemable(g.returnFromIdP(g.start(milk)), milk)
}

func TestBrokerDecline(t *testing.T) {
	g := newBrokerRig(t)
	body := g.returnFromIdP(g.start(milk)).Body.String()
	w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, body, "csrf")}, "decision": {"deny"}})
	if w.Code != 200 || !strings.Contains(w.Body.String(), "did not receive") {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	if len(g.st.consents) != 0 || len(g.st.codes) != 0 {
		t.Fatal("declining recorded consent or issued a code")
	}
}

func TestBrokerConsentCSRF(t *testing.T) {
	g := newBrokerRig(t)
	g.returnFromIdP(g.start(milk))
	w := g.do("POST", "/consent", url.Values{"csrf": {"forged"}, "decision": {"allow"}})
	if w.Code != http.StatusBadRequest || len(g.st.consents) != 0 {
		t.Fatalf("%d, consents=%d", w.Code, len(g.st.consents))
	}

	g2 := newBrokerRig(t)
	body := g2.returnFromIdP(g2.start(milk)).Body.String()
	delete(g2.jar, consentCookie) // a cross-site POST carries no Lax cookie
	w = g2.do("POST", "/consent", url.Values{"csrf": {formValue(t, body, "csrf")}, "decision": {"allow"}})
	if w.Code != http.StatusBadRequest || len(g2.st.consents) != 0 {
		t.Fatalf("%d, consents=%d", w.Code, len(g2.st.consents))
	}
}

func TestBrokerRecreatedDeploymentAsksAgain(t *testing.T) {
	g := newBrokerRig(t)
	g.st.recordConsent(context.Background(), "3f2a", "dep-milk", disclosedClaims)
	g.st.hosts[milk] = "dep-milk-2"
	w := g.returnFromIdP(g.start(milk))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "Continue to") {
		t.Fatalf("%d", w.Code)
	}
}

func TestBrokerDeploymentReplacedWhileDeciding(t *testing.T) {
	g := newBrokerRig(t)
	body := g.returnFromIdP(g.start(milk)).Body.String()
	g.st.hosts[milk] = "dep-milk-2"
	w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, body, "csrf")}, "decision": {"allow"}})
	if w.Code != http.StatusConflict || len(g.st.consents) != 0 || len(g.st.codes) != 0 {
		t.Fatalf("%d consents=%d codes=%d", w.Code, len(g.st.consents), len(g.st.codes))
	}
}

func TestBrokerEligibility(t *testing.T) {
	for name, host := range map[string]string{
		"host without authentication": "plain.erik.freepod.eu",
		"arbitrary host":              "evil.example",
	} {
		t.Run(name, func(t *testing.T) {
			g := newBrokerRig(t)
			w := g.start(host)
			if w.Code != http.StatusNotFound || w.Header().Get("Location") != "" {
				t.Fatalf("%d Location=%q", w.Code, w.Header().Get("Location"))
			}
		})
	}

	t.Run("custom domain", func(t *testing.T) {
		g := newBrokerRig(t)
		g.st.hosts["shop.example.com"] = "dep-shop"
		g.st.recordConsent(context.Background(), "3f2a", "dep-shop", disclosedClaims)
		g.redeemable(g.returnFromIdP(g.start("shop.example.com")), "shop.example.com")
	})

	t.Run("authentication disabled mid-flow", func(t *testing.T) {
		g := newBrokerRig(t)
		g.st.recordConsent(context.Background(), "3f2a", "dep-milk", disclosedClaims)
		start := g.start(milk)
		delete(g.st.hosts, milk)
		w := g.returnFromIdP(start)
		if w.Code != http.StatusNotFound || len(g.st.codes) != 0 {
			t.Fatalf("%d codes=%d", w.Code, len(g.st.codes))
		}
	})
}

func TestBrokerCallbackRejects(t *testing.T) {
	t.Run("state without its flow cookie", func(t *testing.T) {
		g := newBrokerRig(t)
		start := g.start(milk)
		g.jar = map[string]string{} // another browser
		if w := g.returnFromIdP(start); w.Code != http.StatusBadRequest {
			t.Fatalf("%d", w.Code)
		}
	})
	t.Run("forged state", func(t *testing.T) {
		g := newBrokerRig(t)
		g.start(milk)
		w := g.do("GET", "/callback?code=c&state=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", nil)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("%d", w.Code)
		}
	})
	t.Run("unverified email", func(t *testing.T) {
		g := newBrokerRig(t)
		g.auth.err = errEmailUnverified
		w := g.returnFromIdP(g.start(milk))
		if w.Code != http.StatusForbidden || !strings.Contains(w.Body.String(), "verified") || len(g.st.codes) != 0 {
			t.Fatalf("%d", w.Code)
		}
	})
	t.Run("user cancelled at the identity provider", func(t *testing.T) {
		g := newBrokerRig(t)
		loc, _ := url.Parse(g.start(milk).Header().Get("Location"))
		w := g.do("GET", "/callback?error=access_denied&state="+loc.Query().Get("state"), nil)
		if w.Code != http.StatusBadRequest || len(g.st.codes) != 0 {
			t.Fatalf("%d", w.Code)
		}
	})
	t.Run("malformed start", func(t *testing.T) {
		g := newBrokerRig(t)
		if w := g.do("GET", "/start?host="+milk+"&n=short", nil); w.Code != http.StatusBadRequest {
			t.Fatalf("%d", w.Code)
		}
	})
}

func TestBrokerPagesAreHardened(t *testing.T) {
	g := newBrokerRig(t)
	w := g.returnFromIdP(g.start(milk))
	for _, h := range []string{"Content-Security-Policy", "X-Frame-Options", "Cache-Control"} {
		if w.Header().Get(h) == "" {
			t.Errorf("consent page without %s", h)
		}
	}
	if !strings.Contains(w.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'") {
		t.Error("consent page can be framed (clickjacking)")
	}
}

func TestAssets(t *testing.T) {
	g := newBrokerRig(t)
	for path, ctype := range map[string]string{
		"/assets/app-auth.css": "text/css",
		"/assets/logo.svg":     "image/svg+xml",
		"/assets/fonts/schibsted-grotesk-wght-normal.woff2": "font/woff2",
	} {
		w := g.do("GET", path, nil)
		if w.Code != 200 || !strings.HasPrefix(w.Header().Get("Content-Type"), ctype) {
			t.Errorf("%s: %d %q", path, w.Code, w.Header().Get("Content-Type"))
		}
		// The verifier's page loads these from an app's host.
		if w.Header().Get("Access-Control-Allow-Origin") != "*" {
			t.Errorf("%s without CORS", path)
		}
	}
	for _, path := range []string{"/assets/", "/assets/fonts/", "/assets/../broker.go"} {
		if w := g.do("GET", path, nil); w.Code == 200 {
			t.Errorf("%s served: %d", path, w.Code)
		}
	}
}

func TestPagesLoadOnlyFromTheLoginHost(t *testing.T) {
	g := newBrokerRig(t)
	g.b.chrome = newChrome("https://login.dev.freepod.eu")
	w := g.returnFromIdP(g.start(milk))
	body := w.Body.String()
	if !strings.Contains(body, `href="https://login.dev.freepod.eu/assets/app-auth.css?v=`+cssVersion+`"`) {
		t.Fatal("stylesheet not loaded from the login host")
	}
	if !strings.Contains(body, `href="https://dev.freepod.eu/legal/privacy"`) {
		t.Fatal("no privacy policy link")
	}
	csp := w.Header().Get("Content-Security-Policy")
	for _, want := range []string{"default-src 'none'", "style-src https://login.dev.freepod.eu", "font-src https://login.dev.freepod.eu", "frame-ancestors 'none'"} {
		if !strings.Contains(csp, want) {
			t.Errorf("CSP %q lacks %q", csp, want)
		}
	}
	if strings.Contains(csp, "unsafe-inline") {
		t.Error("inline styles allowed")
	}
}

// logout starts sign-out for host and returns the state Keycloak would hand back.
func (g *brokerRig) logout(host, rd string) (*httptest.ResponseRecorder, string) {
	w := g.do("GET", "/logout?"+url.Values{"host": {host}, "rd": {rd}}.Encode(), nil)
	loc, _ := url.Parse(w.Header().Get("Location"))
	return w, loc.Query().Get("state")
}

func TestBrokerLogout(t *testing.T) {
	t.Run("eligible host goes to the identity provider and back", func(t *testing.T) {
		g := newBrokerRig(t)
		w, state := g.logout(milk, "/lists")
		loc, _ := url.Parse(w.Header().Get("Location"))
		if w.Code != http.StatusFound || loc.Host != "keycloak.example" || state == "" ||
			loc.Query().Get("post_logout_redirect_uri") != login+"/signed-out" {
			t.Fatalf("%d %s", w.Code, loc)
		}
		back := g.do("GET", "/signed-out?"+url.Values{"state": {state}}.Encode(), nil)
		if back.Code != http.StatusFound || back.Header().Get("Location") != "https://"+milk+"/lists" {
			t.Fatalf("%d %s", back.Code, back.Header().Get("Location"))
		}
	})

	for name, host := range map[string]string{
		"host without authentication": "plain.erik.freepod.eu",
		"arbitrary host":              "evil.example",
		"no host":                     "",
	} {
		t.Run(name, func(t *testing.T) {
			g := newBrokerRig(t)
			w, _ := g.logout(host, "/")
			if w.Code < 400 || w.Header().Get("Location") != "" || g.auth.endSessions != 0 {
				t.Fatalf("%d Location=%q endSessions=%d", w.Code, w.Header().Get("Location"), g.auth.endSessions)
			}
		})
	}

	t.Run("return target is sanitized", func(t *testing.T) {
		g := newBrokerRig(t)
		_, state := g.logout(milk, "//evil.example/")
		back := g.do("GET", "/signed-out?"+url.Values{"state": {state}}.Encode(), nil)
		if back.Header().Get("Location") != "https://"+milk+"/" {
			t.Fatalf("Location %s", back.Header().Get("Location"))
		}
	})
}

func TestBrokerSignedOutRefusesUntrustedState(t *testing.T) {
	g := newBrokerRig(t)
	_, state := g.logout(milk, "/lists")
	flow, _ := g.b.keys.seal("flow", logoutState{Host: "evil.example", RD: "/"}, logoutTTL, g.clock.now())
	i := len(state) / 2
	tampered := state[:i] + map[bool]string{true: "B", false: "A"}[state[i] == 'A'] + state[i+1:]

	cases := map[string]func() string{
		"missing":       func() string { return "" },
		"tampered":      func() string { return tampered },
		"wrong purpose": func() string { return flow },
		"expired": func() string {
			g.clock.t = g.clock.t.Add(logoutTTL + time.Second)
			return state
		},
	}
	for _, name := range []string{"missing", "tampered", "wrong purpose", "expired"} {
		t.Run(name, func(t *testing.T) {
			w := g.do("GET", "/signed-out?"+url.Values{"state": {cases[name]()}}.Encode(), nil)
			if w.Code != http.StatusOK || w.Header().Get("Location") != "" || !strings.Contains(w.Body.String(), "signed out of Freepod") {
				t.Fatalf("%d Location=%q", w.Code, w.Header().Get("Location"))
			}
		})
	}
}
