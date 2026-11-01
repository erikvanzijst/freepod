package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

// logoutToken signs a Keycloak logout token for session sid with the stub's
// key, or with key when it is set; claims overrides or, set to nil, removes.
func (p *stubIdP) logoutToken(t *testing.T, key *rsa.PrivateKey, claims map[string]any) string {
	t.Helper()
	if key == nil {
		key = p.key
	}
	full := map[string]any{
		"iss": p.srv.URL, "aud": "freepod-apps-dev", "sub": "3f2a", "sid": "kc-session-1",
		"iat": time.Now().Unix(), "jti": randomToken(), "typ": "Logout",
		"events": map[string]any{backchannelLogoutEvent: map[string]any{}},
	}
	for k, v := range claims {
		if v == nil {
			delete(full, k)
		} else {
			full[k] = v
		}
	}
	signer, _ := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: key}, (&jose.SignerOptions{}).WithType("logout+jwt").WithHeader("kid", "k"))
	tok, err := jwt.Signed(signer).Claims(full).Serialize()
	if err != nil {
		t.Fatal(err)
	}
	return tok
}

// stubApps is every tenant app at once: one TLS server that answers each path
// with the handler a test set, and records what it was sent.
type stubApps struct {
	srv *httptest.Server
	mu  sync.Mutex
	got map[string][]string // host+path -> logout tokens received
	by  map[string]http.HandlerFunc
}

func newStubApps(t *testing.T) *stubApps {
	a := &stubApps{got: map[string][]string{}, by: map[string]http.HandlerFunc{}}
	a.srv = httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		a.mu.Lock()
		a.got[r.Host+r.URL.Path] = append(a.got[r.Host+r.URL.Path], r.PostForm.Get("logout_token"))
		h := a.by[r.Host+r.URL.Path]
		a.mu.Unlock()
		if h != nil {
			h(w, r)
		}
	}))
	t.Cleanup(a.srv.Close)
	return a
}

// client reaches every hostname at the stub, as the edge would route it.
func (a *stubApps) client(timeout time.Duration) *http.Client {
	c := newLogoutClient()
	c.Timeout = timeout
	addr := a.srv.Listener.Addr().String()
	c.Transport = &http.Transport{
		DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, network, addr)
		},
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	return c
}

func (a *stubApps) received(hostPath string) []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]string(nil), a.got[hostPath]...)
}

type signOutRig struct {
	t    *testing.T
	b    *broker
	st   *memStore
	idp  *stubIdP
	apps *stubApps
	logs *syncBuffer
}

type syncBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

const (
	wikiLogout  = "/api/oauth/backchannel-logout"
	notesLogout = "/backchannel"
)

func newSignOutRig(t *testing.T) *signOutRig {
	idp := newStubIdP(t)
	apps := newStubApps(t)
	st := newMemStore(time.Now)
	logs := &syncBuffer{}
	g := &signOutRig{t: t, st: st, idp: idp, apps: apps, logs: logs, b: &broker{
		loginURL: login, keys: mustKeyring(t, "k1:"+testKey('a')), store: st, auth: idp.auth(), now: time.Now,
		log: slog.New(slog.NewTextHandler(logs, nil)), logoutClient: apps.client(2 * time.Second),
		oidc: &provider{clientKeys: mustKeyring(t, clientKeys), signer: mustSigner(t, pkcs1PEM(rsaKeys()[0]))},
	}}
	st.clients[depWiki] = memClient{host: wiki, paths: `["/oidc/callback"]`, logout: wikiLogout}
	st.clients[depOther] = memClient{host: other, paths: `["/oidc/callback"]`, logout: notesLogout}
	return g
}

// signedIn records an OIDC sign-in from Keycloak session ksid, as issuing a
// code does, and returns the sid the app was given.
func (g *signOutRig) signedIn(ksid, dep string) string {
	g.t.Helper()
	sid := g.b.keys.appSID(dep, ksid)
	if err := g.st.insertOIDCCode(context.Background(), sha256Bytes(randomToken()), oidcCode{DeploymentID: dep, Subject: "3f2a", SID: sid}, ksid); err != nil {
		g.t.Fatal(err)
	}
	return sid
}

func (g *signOutRig) post(token string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "/backchannel-logout", strings.NewReader(url.Values{"logout_token": {token}}.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	g.b.routes().ServeHTTP(w, r)
	return w
}

// appToken verifies a logout token an app received against the provider's
// JWKS, and returns its header type and claims.
func (g *signOutRig) appToken(raw string) (string, map[string]any) {
	g.t.Helper()
	tok, err := jwt.ParseSigned(raw, []jose.SignatureAlgorithm{jose.RS256})
	if err != nil {
		g.t.Fatal(err)
	}
	keys := g.b.oidc.signer.jwks.Key(tok.Headers[0].KeyID)
	if len(keys) != 1 {
		g.t.Fatalf("signed with an unpublished key %q", tok.Headers[0].KeyID)
	}
	var claims map[string]any
	if err := tok.Claims(keys[0].Key, &claims); err != nil {
		g.t.Fatal(err)
	}
	typ, _ := tok.Headers[0].ExtraHeaders["typ"].(string)
	return typ, claims
}

func TestBackchannelLogout(t *testing.T) {
	g := newSignOutRig(t)
	wikiSID := g.signedIn("kc-session-1", depWiki)
	notesSID := g.signedIn("kc-session-1", depOther)
	phoneSID := g.signedIn("kc-phone", depWiki)

	w := g.post(g.idp.logoutToken(t, nil, nil))
	if w.Code != http.StatusOK || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	g.b.signOuts.Wait()

	for hostPath, want := range map[string]string{wiki + wikiLogout: wikiSID, other + notesLogout: notesSID} {
		got := g.apps.received(hostPath)
		if len(got) != 1 {
			t.Fatalf("%s received %d logout tokens", hostPath, len(got))
		}
		typ, c := g.appToken(got[0])
		dep := depWiki
		if hostPath != wiki+wikiLogout {
			dep = depOther
		}
		events, _ := c["events"].(map[string]any)
		_, isLogout := events[backchannelLogoutEvent]
		if typ != "logout+jwt" || c["iss"] != login || c["aud"] != dep || c["sub"] != "3f2a" || c["sid"] != want ||
			!isLogout || c["jti"] == "" || c["nonce"] != nil {
			t.Errorf("%s: typ %q, claims %v", hostPath, typ, c)
		}
		if exp, iat := c["exp"].(float64), c["iat"].(float64); exp-iat > 120 || exp <= iat {
			t.Errorf("%s: lifetime %v", hostPath, exp-iat)
		}
	}
	if _, ok := g.st.ended["kc-session-1"]; !ok {
		t.Fatal("the session was not recorded as ended")
	}
	if _, ok := g.st.signIns[[2]string{"kc-phone", depWiki}]; !ok || phoneSID == wikiSID {
		t.Fatal("another browser's sign-in went with this session")
	}

	t.Run("a repeated logout sends nothing", func(t *testing.T) {
		if w := g.post(g.idp.logoutToken(t, nil, nil)); w.Code != http.StatusOK {
			t.Fatalf("%d", w.Code)
		}
		g.b.signOuts.Wait()
		if n := len(g.apps.received(wiki + wikiLogout)); n != 1 {
			t.Fatalf("%d deliveries", n)
		}
	})
}

func TestBackchannelLogoutRefuses(t *testing.T) {
	foreign, _ := rsa.GenerateKey(rand.Reader, 2048)
	for name, c := range map[string]struct {
		key    *rsa.PrivateKey
		claims map[string]any
	}{
		"forged signature":       {foreign, nil},
		"other environment":      {nil, map[string]any{"aud": "freepod-apps-prod"}},
		"another issuer":         {nil, map[string]any{"iss": "https://keycloak.example/realms/other"}},
		"no session":             {nil, map[string]any{"sid": nil}},
		"a nonce":                {nil, map[string]any{"nonce": "n"}},
		"three minutes old":      {nil, map[string]any{"iat": time.Now().Add(-3 * time.Minute).Unix()}},
		"issued in the future":   {nil, map[string]any{"iat": time.Now().Add(time.Minute).Unix()}},
		"no iat":                 {nil, map[string]any{"iat": nil}},
		"not a logout event":     {nil, map[string]any{"events": map[string]any{"urn:other": map[string]any{}}}},
		"an ID token, no events": {nil, map[string]any{"events": nil}},
	} {
		t.Run(name, func(t *testing.T) {
			g := newSignOutRig(t)
			g.signedIn("kc-session-1", depWiki)
			if w := g.post(g.idp.logoutToken(t, c.key, c.claims)); w.Code != http.StatusBadRequest {
				t.Fatalf("%d", w.Code)
			}
			g.b.signOuts.Wait()
			if len(g.st.ended) != 0 || len(g.st.signIns) != 1 || len(g.apps.received(wiki+wikiLogout)) != 0 {
				t.Fatal("a refused token ended something")
			}
		})
	}

	t.Run("no token", func(t *testing.T) {
		g := newSignOutRig(t)
		if w := g.post(""); w.Code != http.StatusBadRequest {
			t.Fatalf("%d", w.Code)
		}
	})

	t.Run("database error", func(t *testing.T) {
		g := newSignOutRig(t)
		g.st.signOutErr = errors.New("database down")
		if w := g.post(g.idp.logoutToken(t, nil, nil)); w.Code != http.StatusInternalServerError {
			t.Fatalf("%d", w.Code)
		}
	})
}

func TestLogoutDelivery(t *testing.T) {
	t.Run("failures are logged and not retried", func(t *testing.T) {
		g := newSignOutRig(t)
		g.apps.by[wiki+wikiLogout] = func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusInternalServerError) }
		g.apps.by[other+notesLogout] = func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, "https://"+other+"/elsewhere", http.StatusFound)
		}
		g.signedIn("kc-session-1", depWiki)
		g.signedIn("kc-session-1", depOther)
		if w := g.post(g.idp.logoutToken(t, nil, nil)); w.Code != http.StatusOK {
			t.Fatalf("%d", w.Code)
		}
		g.b.signOuts.Wait()
		if n := len(g.apps.received(wiki + wikiLogout)); n != 1 {
			t.Errorf("the failing app received %d tokens", n)
		}
		if n := len(g.apps.received(other + "/elsewhere")); n != 0 {
			t.Error("a redirect was followed")
		}
		logs := g.logs.String()
		for _, want := range []string{"status=500", "status=302", depWiki, depOther} {
			if !strings.Contains(logs, want) {
				t.Errorf("logs lack %q:\n%s", want, logs)
			}
		}
	})

	t.Run("the identity provider is answered before a slow app", func(t *testing.T) {
		g := newSignOutRig(t)
		g.b.logoutClient = g.apps.client(200 * time.Millisecond)
		release := make(chan struct{})
		g.apps.by[wiki+wikiLogout] = func(w http.ResponseWriter, r *http.Request) {
			select {
			case <-release:
			case <-r.Context().Done():
			}
		}
		g.signedIn("kc-session-1", depWiki)
		done := make(chan int)
		go func() { done <- g.post(g.idp.logoutToken(t, nil, nil)).Code }()
		select {
		case code := <-done:
			if code != http.StatusOK {
				t.Fatalf("%d", code)
			}
		case <-time.After(150 * time.Millisecond):
			t.Fatal("the endpoint waited on the app")
		}
		g.b.signOuts.Wait()
		close(release)
		if logs := g.logs.String(); !strings.Contains(logs, "sign-out not delivered") {
			t.Errorf("the timeout was not logged:\n%s", logs)
		}
	})

	t.Run("apps that take no logout tokens receive none", func(t *testing.T) {
		g := newSignOutRig(t)
		const header, invalid, gone = "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a04", "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a05", "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a06"
		g.st.clients[invalid] = memClient{host: "bad-carol.freepod.app", paths: `["/cb"]`, logout: "@evil.example/steal"}
		g.st.clients[gone] = memClient{host: "gone-carol.freepod.app", paths: `["/cb"]`, logout: "/logout"}
		g.st.clients[depOther] = memClient{host: other, paths: `["/oidc/callback"]`}
		for _, dep := range []string{header, invalid, gone, depOther} {
			g.signedIn("kc-session-1", dep)
		}
		delete(g.st.clients, gone)
		if w := g.post(g.idp.logoutToken(t, nil, nil)); w.Code != http.StatusOK {
			t.Fatalf("%d", w.Code)
		}
		g.b.signOuts.Wait()
		g.apps.mu.Lock()
		defer g.apps.mu.Unlock()
		if len(g.apps.got) != 0 {
			t.Fatalf("received %v", g.apps.got)
		}
		if len(g.st.signIns) != 0 {
			t.Fatal("sign-in records were kept")
		}
	})
}
