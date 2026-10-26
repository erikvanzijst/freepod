package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	jose "github.com/go-jose/go-jose/v4"
)

const (
	depWiki  = "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a01"
	depOther = "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a02"
	depOpen  = "0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a03" // its template opts out of PKCE
	other    = "notes-bob.freepod.app"

	wikiCallback = "https://" + wiki + "/oidc/callback"
	immichNative = "app.immich:///oauth-callback"
	// The verifier is fixed so tests can name its challenge.
	pkceVerifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)

var pkceChallenge = func() string {
	sum := sha256.Sum256([]byte(pkceVerifier))
	return base64.RawURLEncoding.EncodeToString(sum[:])
}()

// RSA key generation is slow, so the run shares a few keys.
var rsaKeys = sync.OnceValue(func() []*rsa.PrivateKey {
	var keys []*rsa.PrivateKey
	for i := 0; i < 3; i++ {
		k, err := rsa.GenerateKey(rand.Reader, 2048)
		if err != nil {
			panic(err)
		}
		keys = append(keys, k)
	}
	return keys
})

func pkcs1PEM(k *rsa.PrivateKey) string {
	return string(pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)}))
}

func pkcs8PEM(t *testing.T, k any) string {
	der, err := x509.MarshalPKCS8PrivateKey(k)
	if err != nil {
		t.Fatal(err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
}

func mustSigner(t *testing.T, spec string) *signer {
	t.Helper()
	s, err := parseSigningKeys(spec)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

const clientKeys = "c1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

type providerRig struct {
	*brokerRig
}

func newProviderRig(t *testing.T) *providerRig {
	t.Helper()
	g := &providerRig{newBrokerRig(t)}
	g.b.oidc = &provider{clientKeys: mustKeyring(t, clientKeys), signer: mustSigner(t, pkcs1PEM(rsaKeys()[0]))}
	g.st.clients[depWiki] = memClient{host: wiki, paths: `["/oidc/callback"]`, natives: `["app.immich:///oauth-callback"]`}
	g.st.clients[depOther] = memClient{host: other, paths: `["/oidc/callback"]`}
	g.st.clients[depOpen] = memClient{host: "open-carol.freepod.app", paths: `["/cb"]`, natives: `["app.immich:///oauth-callback"]`, pkceOptOut: true}
	g.auth.id.AuthTime = t0.Add(-time.Hour)
	return g
}

func authorizeQuery(clientID, redirectURI string, extra ...string) url.Values {
	q := url.Values{
		"client_id": {clientID}, "redirect_uri": {redirectURI}, "response_type": {"code"},
		"scope": {"openid email profile"}, "state": {"app-state"}, "nonce": {"app-nonce"},
		"code_challenge": {pkceChallenge}, "code_challenge_method": {"S256"},
	}
	for i := 0; i+1 < len(extra); i += 2 {
		if extra[i+1] == "" {
			q.Del(extra[i])
		} else {
			q.Set(extra[i], extra[i+1])
		}
	}
	return q
}

func (g *providerRig) authorize(q url.Values) *httptest.ResponseRecorder {
	return g.do("GET", "/oidc/authorize?"+q.Encode(), nil)
}

// signIn runs authorize, Keycloak, and consent when asked for, and returns
// the response that should carry the code back to the app.
func (g *providerRig) signIn(q url.Values) *httptest.ResponseRecorder {
	g.t.Helper()
	start := g.authorize(q)
	if start.Code != http.StatusFound || !strings.HasPrefix(start.Header().Get("Location"), "https://keycloak.example/") {
		g.t.Fatalf("authorize: %d %s %s", start.Code, start.Header().Get("Location"), start.Body)
	}
	w := g.returnFromIdP(start)
	if w.Code == http.StatusOK && strings.Contains(w.Body.String(), "Continue to") {
		w = g.do("POST", "/consent", url.Values{"csrf": {formValue(g.t, w.Body.String(), "csrf")}, "decision": {"allow"}})
	}
	return w
}

// codeFrom checks a redirect to redirectURI with the app's state, and returns the code.
func (g *providerRig) codeFrom(w *httptest.ResponseRecorder, redirectURI string) string {
	g.t.Helper()
	if w.Code != http.StatusFound {
		g.t.Fatalf("status %d: %s", w.Code, w.Body)
	}
	loc := w.Header().Get("Location")
	base, query, _ := strings.Cut(loc, "?")
	q, _ := url.ParseQuery(query)
	if base != redirectURI || q.Get("state") != "app-state" || q.Get("error") != "" || len(q.Get("code")) < 43 {
		g.t.Fatalf("Location %s", loc)
	}
	return q.Get("code")
}

// oauthError checks a redirect to redirectURI carrying an OAuth error.
func oauthError(t *testing.T, w *httptest.ResponseRecorder, redirectURI, code, state string) {
	t.Helper()
	loc := w.Header().Get("Location")
	base, query, _ := strings.Cut(loc, "?")
	q, _ := url.ParseQuery(query)
	if w.Code != http.StatusFound || base != redirectURI || q.Get("error") != code || q.Get("state") != state || q.Has("code") {
		t.Fatalf("want error=%s to %s with state %q; got %d %s", code, redirectURI, state, w.Code, loc)
	}
}

func errorPageWithoutRedirect(t *testing.T, w *httptest.ResponseRecorder) {
	t.Helper()
	if w.Code < 400 || w.Header().Get("Location") != "" || !strings.Contains(w.Header().Get("Content-Type"), "text/html") {
		t.Fatalf("want an error page; got %d Location=%q", w.Code, w.Header().Get("Location"))
	}
}

func TestSigningKeys(t *testing.T) {
	keys := rsaKeys()

	t.Run("kid is the RFC 7638 thumbprint", func(t *testing.T) {
		s := mustSigner(t, pkcs1PEM(keys[0]))
		pub := keys[0].PublicKey
		e := base64.RawURLEncoding.EncodeToString([]byte{1, 0, 1})
		n := base64.RawURLEncoding.EncodeToString(pub.N.Bytes())
		sum := sha256.Sum256([]byte(`{"e":"` + e + `","kty":"RSA","n":"` + n + `"}`))
		if want := base64.RawURLEncoding.EncodeToString(sum[:]); s.keys[0].kid != want {
			t.Fatalf("kid %s, want %s", s.keys[0].kid, want)
		}
	})

	t.Run("PKCS#8 and rotation", func(t *testing.T) {
		s := mustSigner(t, pkcs8PEM(t, keys[1])+pkcs1PEM(keys[0]))
		if len(s.jwks.Keys) != 2 || s.jwks.Keys[0].KeyID != s.keys[0].kid {
			t.Fatalf("%+v", s.jwks.Keys)
		}
		tok, err := s.sign(map[string]any{"x": "y"})
		if err != nil {
			t.Fatal(err)
		}
		parsed, err := jose.ParseSigned(tok, []jose.SignatureAlgorithm{jose.RS256})
		if err != nil || parsed.Signatures[0].Header.KeyID != s.keys[0].kid {
			t.Fatalf("not signed with the first key: %v", err)
		}
		if _, err := parsed.Verify(&keys[1].PublicKey); err != nil {
			t.Fatal(err)
		}
	})

	small, _ := rsa.GenerateKey(rand.Reader, 1024)
	ec, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	for name, spec := range map[string]string{
		"empty":          "",
		"not PEM":        "hello",
		"short key":      pkcs1PEM(small),
		"not RSA":        pkcs8PEM(t, ec),
		"same key twice": pkcs1PEM(keys[0]) + pkcs8PEM(t, keys[0]),
		"public key":     string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: x509.MarshalPKCS1PublicKey(&keys[0].PublicKey)})),
	} {
		if _, err := parseSigningKeys(spec); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestLoadProvider(t *testing.T) {
	cfg := config{loginURL: login}
	if p, err := loadProvider(cfg, quiet); p != nil || err != nil {
		t.Fatal("provider enabled without keys")
	}
	cfg.providerClientKeys = clientKeys
	if p, err := loadProvider(cfg, quiet); p != nil || err != nil {
		t.Fatal("provider enabled without a signing key")
	}
	cfg.providerSigningKeys = pkcs1PEM(rsaKeys()[0])
	if p, err := loadProvider(cfg, quiet); p == nil || err != nil {
		t.Fatalf("provider not enabled: %v", err)
	}
	cfg.providerSigningKeys = "garbage"
	if _, err := loadProvider(cfg, quiet); err == nil {
		t.Fatal("started with an unreadable signing key")
	}

	g := newBrokerRig(t)
	for _, path := range []string{"/.well-known/openid-configuration", "/oidc/jwks", "/oidc/authorize"} {
		if w := g.do("GET", path, nil); w.Code != http.StatusNotFound {
			t.Errorf("%s served without the provider: %d", path, w.Code)
		}
	}
}

// serve puts the broker behind a real listener, with the issuer it serves.
func (g *providerRig) serve() *httptest.Server {
	srv := httptest.NewServer(g.b.routes())
	g.t.Cleanup(srv.Close)
	g.b.loginURL = srv.URL
	return srv
}

func TestDiscovery(t *testing.T) {
	g := newProviderRig(t)
	srv := g.serve()
	p, err := oidc.NewProvider(context.Background(), srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	var meta map[string]any
	if err := p.Claims(&meta); err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri", "end_session_endpoint"} {
		if v, _ := meta[k].(string); !strings.HasPrefix(v, srv.URL+"/") {
			t.Errorf("%s = %v, not on the issuer's host", k, meta[k])
		}
	}
	for k, want := range map[string]string{
		"response_types_supported":              `["code"]`,
		"subject_types_supported":               `["public"]`,
		"id_token_signing_alg_values_supported": `["RS256"]`,
		"token_endpoint_auth_methods_supported": `["client_secret_basic","client_secret_post"]`,
		"code_challenge_methods_supported":      `["S256"]`,
	} {
		if got, _ := json.Marshal(meta[k]); string(got) != want {
			t.Errorf("%s = %s, want %s", k, got, want)
		}
	}

	g2 := newProviderRig(t)
	g2.b.loginURL = "https://login.freepod.eu"
	w := g2.do("GET", "/.well-known/openid-configuration", nil)
	json.Unmarshal(w.Body.Bytes(), &meta)
	if meta["issuer"] != "https://login.freepod.eu" || meta["token_endpoint"] != "https://login.freepod.eu/oidc/token" {
		t.Fatalf("metadata %v", meta)
	}
}

func TestAuthorizeRefusesWithoutRedirect(t *testing.T) {
	g := newProviderRig(t)
	g.st.clients["0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a09"] = memClient{host: "nopaths-dan.freepod.app", paths: `[]`}
	for name, q := range map[string]url.Values{
		"unknown client":             authorizeQuery("0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9aff", wikiCallback),
		"no client":                  authorizeQuery("", wikiCallback),
		"template declares no paths": authorizeQuery("0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9a09", "https://nopaths-dan.freepod.app/"),
		"another path on the host":   authorizeQuery(depWiki, "https://"+wiki+"/shared/page"),
		"extra query":                authorizeQuery(depWiki, wikiCallback+"?code=ATTACKER"),
		"another host":               authorizeQuery(depWiki, "https://evil.example/oidc/callback"),
		"plain http":                 authorizeQuery(depWiki, "http://"+wiki+"/oidc/callback"),
		"another client's callback":  authorizeQuery(depWiki, "https://"+other+"/oidc/callback"),
		"userinfo trick":             authorizeQuery(depWiki, "https://"+wiki+"@evil.example/cb"),
		"native URI not declared":    authorizeQuery(depWiki, "app.evil:///steal"),
		"no redirect URI":            authorizeQuery(depWiki, ""),
		"repeated redirect URI":      {"client_id": {depWiki}, "redirect_uri": {wikiCallback, "https://evil.example/"}},
		// Errors that would go to the redirect URI need a valid one first.
		"invalid request, invalid redirect": authorizeQuery(depWiki, "https://evil.example/", "response_type", "token"),
	} {
		t.Run(name, func(t *testing.T) {
			w := g.authorize(q)
			errorPageWithoutRedirect(t, w)
			if len(w.Result().Cookies()) != 0 {
				t.Fatal("set a cookie")
			}
		})
	}
}

func TestAuthorizeErrorsGoBackToTheApp(t *testing.T) {
	g := newProviderRig(t)
	long := strings.Repeat("s", 513)
	for name, c := range map[string]struct {
		q     url.Values
		code  string
		state string
	}{
		"unsupported response type": {authorizeQuery(depWiki, wikiCallback, "response_type", "token"), "unsupported_response_type", "app-state"},
		"missing response type":     {authorizeQuery(depWiki, wikiCallback, "response_type", ""), "invalid_request", "app-state"},
		"no openid scope":           {authorizeQuery(depWiki, wikiCallback, "scope", "email"), "invalid_scope", "app-state"},
		"oversized state":           {authorizeQuery(depWiki, wikiCallback, "state", long), "invalid_request", ""},
		"oversized nonce":           {authorizeQuery(depWiki, wikiCallback, "nonce", strings.Repeat("n", 257)), "invalid_request", "app-state"},
		"short challenge":           {authorizeQuery(depWiki, wikiCallback, "code_challenge", "abc"), "invalid_request", "app-state"},
		"long challenge":            {authorizeQuery(depWiki, wikiCallback, "code_challenge", pkceChallenge+"x"), "invalid_request", "app-state"},
		"missing challenge":         {authorizeQuery(depWiki, wikiCallback, "code_challenge", "", "code_challenge_method", ""), "invalid_request", "app-state"},
		"plain challenge":           {authorizeQuery(depWiki, wikiCallback, "code_challenge_method", "plain"), "invalid_request", "app-state"},
		"challenge without method":  {authorizeQuery(depWiki, wikiCallback, "code_challenge_method", ""), "invalid_request", "app-state"},
		"method without challenge":  {authorizeQuery(depOpen, "https://open-carol.freepod.app/cb", "code_challenge", ""), "invalid_request", "app-state"},
		"native redirect without PKCE under the opt-out": {
			authorizeQuery(depOpen, immichNative, "code_challenge", "", "code_challenge_method", ""), "invalid_request", "app-state"},
		"prompt=none combined":   {authorizeQuery(depWiki, wikiCallback, "prompt", "none login"), "invalid_request", "app-state"},
		"unknown prompt":         {authorizeQuery(depWiki, wikiCallback, "prompt", "create"), "invalid_request", "app-state"},
		"negative max_age":       {authorizeQuery(depWiki, wikiCallback, "max_age", "-1"), "invalid_request", "app-state"},
		"fragment response mode": {authorizeQuery(depWiki, wikiCallback, "response_mode", "fragment"), "invalid_request", "app-state"},
		"request object":         {authorizeQuery(depWiki, wikiCallback, "request", "eyJ..."), "request_not_supported", "app-state"},
		"repeated parameter":     {func() url.Values { q := authorizeQuery(depWiki, wikiCallback); q.Add("scope", "openid"); return q }(), "invalid_request", "app-state"},
	} {
		t.Run(name, func(t *testing.T) {
			redirectURI := c.q.Get("redirect_uri")
			w := g.authorize(c.q)
			oauthError(t, w, redirectURI, c.code, c.state)
			if len(w.Result().Cookies()) != 0 {
				t.Fatal("set a cookie")
			}
		})
	}
}

func TestAuthorizationCodeFlow(t *testing.T) {
	t.Run("first sign-in asks for consent naming the hostname", func(t *testing.T) {
		g := newProviderRig(t)
		page := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback)))
		if page.Code != 200 || !strings.Contains(page.Body.String(), "Continue to <span class=\"host\">"+wiki) {
			t.Fatalf("%d %s", page.Code, page.Body)
		}
		if strings.Contains(page.Body.String(), "/oidc/callback") {
			t.Fatal("the consent page shows the redirect URI")
		}
		if len(g.st.oidcCodes) != 0 {
			t.Fatal("a code was issued before consent")
		}
		w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, page.Body.String(), "csrf")}, "decision": {"allow"}})
		code := g.codeFrom(w, wikiCallback)
		if ok, _ := g.st.hasConsent(context.Background(), "3f2a", depWiki, disclosedClaims); !ok {
			t.Fatal("consent not recorded")
		}
		rec, fresh, found, _ := g.st.redeemOIDCCode(context.Background(), sha256Bytes(code))
		want := oidcCode{DeploymentID: depWiki, RedirectURI: wikiCallback, Subject: "3f2a", Email: "alice@example.com",
			Name: "Alice", Nonce: "app-nonce", CodeChallenge: pkceChallenge, AuthTime: t0.Add(-time.Hour)}
		if !found || !fresh || !rec.AuthTime.Equal(want.AuthTime) {
			t.Fatalf("code %+v found=%v fresh=%v", rec, found, fresh)
		}
		rec.AuthTime = want.AuthTime
		if rec != want {
			t.Fatalf("code %+v", rec)
		}
		if _, _, found, _ := g.st.redeemCode(context.Background(), sha256Bytes(code)); found {
			t.Fatal("an OIDC code redeems as a sign-in code")
		}
	})

	t.Run("consent given through header authentication counts", func(t *testing.T) {
		g := newProviderRig(t)
		g.st.recordConsent(context.Background(), "3f2a", depWiki, disclosedClaims)
		g.codeFrom(g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback))), wikiCallback)
	})

	t.Run("prompt=consent asks again", func(t *testing.T) {
		g := newProviderRig(t)
		g.st.recordConsent(context.Background(), "3f2a", depWiki, disclosedClaims)
		w := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback, "prompt", "consent")))
		if w.Code != 200 || !strings.Contains(w.Body.String(), "Continue to") {
			t.Fatalf("%d", w.Code)
		}
		if g.auth.params.prompt != "" {
			t.Fatalf("prompt %q reached Keycloak", g.auth.params.prompt)
		}
	})

	t.Run("silent sign-in without consent", func(t *testing.T) {
		g := newProviderRig(t)
		w := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback, "prompt", "none")))
		oauthError(t, w, wikiCallback, "consent_required", "app-state")
		if g.auth.params.prompt != "none" {
			t.Fatalf("prompt %q", g.auth.params.prompt)
		}
	})

	t.Run("silent sign-in with consent", func(t *testing.T) {
		g := newProviderRig(t)
		g.st.recordConsent(context.Background(), "3f2a", depWiki, disclosedClaims)
		g.codeFrom(g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback, "prompt", "none"))), wikiCallback)
	})

	t.Run("prompt and max_age reach Keycloak", func(t *testing.T) {
		g := newProviderRig(t)
		g.authorize(authorizeQuery(depWiki, wikiCallback, "prompt", "login select_account", "max_age", "300"))
		if g.auth.params != (authParams{prompt: "login select_account", maxAge: "300"}) {
			t.Fatalf("%+v", g.auth.params)
		}
	})

	t.Run("Keycloak's errors go back to the app", func(t *testing.T) {
		for kc, want := range map[string]string{"login_required": "login_required", "access_denied": "access_denied", "something_odd": "server_error"} {
			g := newProviderRig(t)
			loc, _ := url.Parse(g.authorize(authorizeQuery(depWiki, wikiCallback, "prompt", "none")).Header().Get("Location"))
			w := g.do("GET", "/callback?"+url.Values{"error": {kc}, "state": {loc.Query().Get("state")}}.Encode(), nil)
			oauthError(t, w, wikiCallback, want, "app-state")
		}
	})

	t.Run("declining", func(t *testing.T) {
		g := newProviderRig(t)
		page := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback)))
		w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, page.Body.String(), "csrf")}, "decision": {"deny"}})
		oauthError(t, w, wikiCallback, "access_denied", "app-state")
		if len(g.st.consents) != 0 || len(g.st.oidcCodes) != 0 {
			t.Fatal("declining recorded consent or issued a code")
		}
	})

	t.Run("unverified email", func(t *testing.T) {
		g := newProviderRig(t)
		g.auth.err = errEmailUnverified
		w := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback)))
		if w.Code != http.StatusForbidden || len(g.st.oidcCodes) != 0 {
			t.Fatalf("%d", w.Code)
		}
	})

	t.Run("SSO turned off mid-flow", func(t *testing.T) {
		g := newProviderRig(t)
		start := g.authorize(authorizeQuery(depWiki, wikiCallback))
		delete(g.st.clients, depWiki)
		errorPageWithoutRedirect(t, g.returnFromIdP(start))
	})

	t.Run("SSO turned off on the consent page", func(t *testing.T) {
		g := newProviderRig(t)
		page := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback)))
		delete(g.st.clients, depWiki)
		w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, page.Body.String(), "csrf")}, "decision": {"allow"}})
		errorPageWithoutRedirect(t, w)
		if len(g.st.consents) != 0 || len(g.st.oidcCodes) != 0 {
			t.Fatal("consent recorded or code issued")
		}
	})

	t.Run("without nonce or state", func(t *testing.T) {
		g := newProviderRig(t)
		w := g.signIn(authorizeQuery(depWiki, wikiCallback, "nonce", "", "state", ""))
		loc, _ := url.Parse(w.Header().Get("Location"))
		if loc.Query().Has("state") || loc.Query().Get("code") == "" {
			t.Fatalf("Location %s", loc)
		}
	})

	t.Run("PKCE opt-out", func(t *testing.T) {
		g := newProviderRig(t)
		w := g.signIn(authorizeQuery(depOpen, "https://open-carol.freepod.app/cb", "code_challenge", "", "code_challenge_method", ""))
		code := g.codeFrom(w, "https://open-carol.freepod.app/cb")
		if rec := g.st.oidcCodes[string(sha256Bytes(code))].rec; rec.CodeChallenge != "" {
			t.Fatalf("%+v", rec)
		}
	})

	t.Run("header sign-in flows still work beside OIDC", func(t *testing.T) {
		g := newProviderRig(t)
		g.st.recordConsent(context.Background(), "3f2a", "dep-milk", disclosedClaims)
		g.redeemable(g.returnFromIdP(g.start(milk)), milk)
		if len(g.st.oidcCodes) != 0 {
			t.Fatal("header sign-in issued an OIDC code")
		}
	})
}

func TestConsentToANativeApp(t *testing.T) {
	g := newProviderRig(t)
	page := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, immichNative)))
	csp := page.Header().Get("Content-Security-Policy")
	if !strings.Contains(csp, "form-action 'self' https: app.immich:;") {
		t.Fatalf("CSP %q", csp)
	}
	w := g.do("POST", "/consent", url.Values{"csrf": {formValue(t, page.Body.String(), "csrf")}, "decision": {"allow"}})
	g.codeFrom(w, immichNative)

	// Only the validated scheme, and only on that page.
	g2 := newProviderRig(t)
	web := g2.returnFromIdP(g2.authorize(authorizeQuery(depWiki, wikiCallback)))
	if csp := web.Header().Get("Content-Security-Policy"); !strings.Contains(csp, "form-action 'self' https:;") {
		t.Fatalf("CSP %q", csp)
	}
}

func basicAuth(id, secret string) string {
	return "Basic " + base64.StdEncoding.EncodeToString([]byte(url.QueryEscape(id)+":"+url.QueryEscape(secret)))
}

func (g *providerRig) secret(clientID string) string {
	return g.b.oidc.clientKeys.clientSecret(clientID)
}

// tokenRequest posts to the token endpoint, authenticating with the form
// unless basic is set.
func (g *providerRig) tokenRequest(form url.Values, basic string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "/oidc/token", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	if basic != "" {
		r.Header.Set("Authorization", basic)
	}
	w := httptest.NewRecorder()
	g.b.routes().ServeHTTP(w, r)
	return w
}

func (g *providerRig) codeFor(clientID, redirectURI string, extra ...string) string {
	g.t.Helper()
	g.st.recordConsent(context.Background(), "3f2a", clientID, disclosedClaims)
	return g.codeFrom(g.signIn(authorizeQuery(clientID, redirectURI, extra...)), redirectURI)
}

func redeemForm(clientID, code, redirectURI string, withSecret string) url.Values {
	f := url.Values{"grant_type": {"authorization_code"}, "code": {code}, "redirect_uri": {redirectURI}, "code_verifier": {pkceVerifier}}
	if clientID != "" {
		f.Set("client_id", clientID)
	}
	if withSecret != "" {
		f.Set("client_secret", withSecret)
	}
	return f
}

func tokenErrorIs(t *testing.T, w *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	var body map[string]string
	json.Unmarshal(w.Body.Bytes(), &body)
	if w.Code != status || body["error"] != code || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("want %d %s; got %d %s (Cache-Control %q)", status, code, w.Code, w.Body, w.Header().Get("Cache-Control"))
	}
}

type tokenBody struct {
	AccessToken  string `json:"access_token"`
	TokenType    string `json:"token_type"`
	ExpiresIn    int    `json:"expires_in"`
	IDToken      string `json:"id_token"`
	RefreshToken string `json:"refresh_token"`
}

func (g *providerRig) redeem(clientID, redirectURI string) tokenBody {
	g.t.Helper()
	code := g.codeFor(clientID, redirectURI)
	w := g.tokenRequest(redeemForm(clientID, code, redirectURI, g.secret(clientID)), "")
	if w.Code != 200 {
		g.t.Fatalf("token: %d %s", w.Code, w.Body)
	}
	var tb tokenBody
	json.Unmarshal(w.Body.Bytes(), &tb)
	return tb
}

func TestTokenEndpoint(t *testing.T) {
	t.Run("redeems with the secret in the form", func(t *testing.T) {
		g := newProviderRig(t)
		code := g.codeFor(depWiki, wikiCallback)
		w := g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), "")
		if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
		var raw map[string]any
		json.Unmarshal(w.Body.Bytes(), &raw)
		if raw["token_type"] != "Bearer" || raw["expires_in"] != float64(600) || raw["id_token"] == "" || raw["access_token"] == "" {
			t.Fatalf("%v", raw)
		}
		if _, ok := raw["refresh_token"]; ok {
			t.Fatal("issued a refresh token")
		}
	})

	t.Run("redeems with HTTP Basic", func(t *testing.T) {
		g := newProviderRig(t)
		code := g.codeFor(depWiki, wikiCallback)
		w := g.tokenRequest(redeemForm("", code, wikiCallback, ""), basicAuth(depWiki, g.secret(depWiki)))
		if w.Code != 200 {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
	})

	t.Run("refuses both authentication methods at once", func(t *testing.T) {
		g := newProviderRig(t)
		code := g.codeFor(depWiki, wikiCallback)
		w := g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), basicAuth(depWiki, g.secret(depWiki)))
		tokenErrorIs(t, w, http.StatusBadRequest, "invalid_request")
	})

	clientFailures := map[string]func(g *providerRig, code string) *httptest.ResponseRecorder{
		"wrong secret": func(g *providerRig, code string) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, "nope"), "")
		},
		"another deployment's secret": func(g *providerRig, code string) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depOther)), "")
		},
		"another deployment's secret by Basic": func(g *providerRig, code string) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm("", code, wikiCallback, ""), basicAuth(depWiki, g.secret(depOther)))
		},
		"Basic for one client, form for another": func(g *providerRig, code string) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm(depOther, code, wikiCallback, ""), basicAuth(depWiki, g.secret(depWiki)))
		},
		"no credentials": func(g *providerRig, code string) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, ""), "")
		},
		"deleted deployment": func(g *providerRig, code string) *httptest.ResponseRecorder {
			delete(g.st.clients, depWiki)
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), "")
		},
		"client of another environment": func(g *providerRig, code string) *httptest.ResponseRecorder {
			prod := mustKeyring(t, "p1:"+testKey('p'))
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, prod.clientSecret(depWiki)), "")
		},
	}
	for name, try := range clientFailures {
		t.Run(name, func(t *testing.T) {
			g := newProviderRig(t)
			code := g.codeFor(depWiki, wikiCallback)
			tokenErrorIs(t, try(g, code), http.StatusUnauthorized, "invalid_client")
		})
	}

	grantFailures := map[string]func(g *providerRig) *httptest.ResponseRecorder{
		"replay": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), "")
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), "")
		},
		"code for another client": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			return g.tokenRequest(redeemForm(depOther, code, wikiCallback, g.secret(depOther)), "")
		},
		"another redirect URI": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			return g.tokenRequest(redeemForm(depWiki, code, immichNative, g.secret(depWiki)), "")
		},
		"missing verifier": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			f := redeemForm(depWiki, code, wikiCallback, g.secret(depWiki))
			f.Del("code_verifier")
			return g.tokenRequest(f, "")
		},
		"wrong verifier": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			f := redeemForm(depWiki, code, wikiCallback, g.secret(depWiki))
			f.Set("code_verifier", strings.Repeat("a", 43))
			return g.tokenRequest(f, "")
		},
		"the challenge as verifier": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			f := redeemForm(depWiki, code, wikiCallback, g.secret(depWiki))
			f.Set("code_verifier", pkceChallenge)
			return g.tokenRequest(f, "")
		},
		"PKCE downgrade": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depOpen, "https://open-carol.freepod.app/cb", "code_challenge", "", "code_challenge_method", "")
			return g.tokenRequest(redeemForm(depOpen, code, "https://open-carol.freepod.app/cb", g.secret(depOpen)), "")
		},
		"expired code": func(g *providerRig) *httptest.ResponseRecorder {
			code := g.codeFor(depWiki, wikiCallback)
			g.clock.t = g.clock.t.Add(codeTTL + time.Second)
			return g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), "")
		},
		"unknown code": func(g *providerRig) *httptest.ResponseRecorder {
			return g.tokenRequest(redeemForm(depWiki, randomToken(), wikiCallback, g.secret(depWiki)), "")
		},
	}
	for name, try := range grantFailures {
		t.Run(name, func(t *testing.T) {
			tokenErrorIs(t, try(newProviderRig(t)), http.StatusBadRequest, "invalid_grant")
		})
	}

	t.Run("a code for another client is burnt", func(t *testing.T) {
		g := newProviderRig(t)
		code := g.codeFor(depWiki, wikiCallback)
		g.tokenRequest(redeemForm(depOther, code, wikiCallback, g.secret(depOther)), "")
		tokenErrorIs(t, g.tokenRequest(redeemForm(depWiki, code, wikiCallback, g.secret(depWiki)), ""), http.StatusBadRequest, "invalid_grant")
	})

	t.Run("PKCE opt-out redeems without a verifier", func(t *testing.T) {
		g := newProviderRig(t)
		code := g.codeFor(depOpen, "https://open-carol.freepod.app/cb", "code_challenge", "", "code_challenge_method", "")
		f := redeemForm(depOpen, code, "https://open-carol.freepod.app/cb", g.secret(depOpen))
		f.Del("code_verifier")
		if w := g.tokenRequest(f, ""); w.Code != 200 {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
	})

	t.Run("unsupported grant type", func(t *testing.T) {
		g := newProviderRig(t)
		f := url.Values{"grant_type": {"refresh_token"}, "refresh_token": {"x"}, "client_id": {depWiki}, "client_secret": {g.secret(depWiki)}}
		tokenErrorIs(t, g.tokenRequest(f, ""), http.StatusBadRequest, "unsupported_grant_type")
	})
}

func TestIDToken(t *testing.T) {
	g := newProviderRig(t)
	srv := g.serve()
	tb := g.redeem(depWiki, wikiCallback)

	ctx := oidc.ClientContext(context.Background(), srv.Client())
	p, err := oidc.NewProvider(ctx, srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	now := func() time.Time { return t0 }
	idt, err := p.Verifier(&oidc.Config{ClientID: depWiki, Now: now}).Verify(ctx, tb.IDToken)
	if err != nil {
		t.Fatal(err)
	}
	var claims map[string]any
	idt.Claims(&claims)
	want := map[string]any{
		"iss": srv.URL, "aud": depWiki, "azp": depWiki, "sub": "3f2a", "email": "alice@example.com",
		"email_verified": true, "name": "Alice", "nonce": "app-nonce",
		"iat": float64(t0.Unix()), "exp": float64(t0.Add(300 * time.Second).Unix()), "auth_time": float64(t0.Add(-time.Hour).Unix()),
	}
	if len(claims) != len(want) {
		t.Errorf("claims %v", claims)
	}
	for k, v := range want {
		if claims[k] != v {
			t.Errorf("%s = %v, want %v", k, claims[k], v)
		}
	}
	if _, ok := claims["preferred_username"]; ok {
		t.Error("ID token carries preferred_username")
	}

	parsed, _ := jose.ParseSigned(tb.IDToken, []jose.SignatureAlgorithm{jose.RS256})
	if h := parsed.Signatures[0].Header; h.ExtraHeaders["typ"] != "JWT" || h.KeyID != g.b.oidc.signer.keys[0].kid {
		t.Errorf("header %+v", h)
	}

	if _, err := p.Verifier(&oidc.Config{ClientID: depOther, Now: now}).Verify(ctx, tb.IDToken); err == nil {
		t.Error("an ID token for one deployment verified for another")
	}

	t.Run("signing key rotation", func(t *testing.T) {
		g.b.oidc.signer = mustSigner(t, pkcs1PEM(rsaKeys()[1])+pkcs1PEM(rsaKeys()[0]))
		p, err := oidc.NewProvider(ctx, srv.URL)
		if err != nil {
			t.Fatal(err)
		}
		v := p.Verifier(&oidc.Config{ClientID: depWiki, Now: now})
		if _, err := v.Verify(ctx, tb.IDToken); err != nil {
			t.Fatalf("token signed with the previous key: %v", err)
		}
		fresh := g.redeem(depWiki, wikiCallback)
		parsed, _ := jose.ParseSigned(fresh.IDToken, []jose.SignatureAlgorithm{jose.RS256})
		if parsed.Signatures[0].Header.KeyID != g.b.oidc.signer.keys[0].kid {
			t.Fatal("not signed with the new key")
		}
		if _, err := v.Verify(ctx, fresh.IDToken); err != nil {
			t.Fatal(err)
		}
	})
}

func (g *providerRig) userinfo(header, token string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("GET", "/oidc/userinfo", nil)
	if token != "" {
		r.Header.Set("Authorization", header+" "+token)
	}
	w := httptest.NewRecorder()
	g.b.routes().ServeHTTP(w, r)
	return w
}

func TestUserinfo(t *testing.T) {
	invalidToken := func(t *testing.T, w *httptest.ResponseRecorder) {
		t.Helper()
		if w.Code != http.StatusUnauthorized || w.Header().Get("WWW-Authenticate") != `Bearer error="invalid_token"` {
			t.Fatalf("%d %q", w.Code, w.Header().Get("WWW-Authenticate"))
		}
	}

	t.Run("answers the ID token's claims", func(t *testing.T) {
		g := newProviderRig(t)
		tb := g.redeem(depWiki, wikiCallback)
		w := g.userinfo("Bearer", tb.AccessToken)
		var got map[string]any
		json.Unmarshal(w.Body.Bytes(), &got)
		if w.Code != 200 || len(got) != 4 || got["sub"] != "3f2a" || got["email"] != "alice@example.com" ||
			got["email_verified"] != true || got["name"] != "Alice" || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("%d %s", w.Code, w.Body)
		}
	})

	t.Run("by POST", func(t *testing.T) {
		g := newProviderRig(t)
		tb := g.redeem(depWiki, wikiCallback)
		r := httptest.NewRequest("POST", "/oidc/userinfo", strings.NewReader(url.Values{"access_token": {tb.AccessToken}}.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		g.b.routes().ServeHTTP(w, r)
		if w.Code != 200 {
			t.Fatalf("%d", w.Code)
		}
	})

	t.Run("expired access token", func(t *testing.T) {
		g := newProviderRig(t)
		tb := g.redeem(depWiki, wikiCallback)
		g.clock.t = g.clock.t.Add(accessTokenTTL)
		invalidToken(t, g.userinfo("Bearer", tb.AccessToken))
	})

	t.Run("deployment turned SSO off", func(t *testing.T) {
		g := newProviderRig(t)
		tb := g.redeem(depWiki, wikiCallback)
		delete(g.st.clients, depWiki)
		invalidToken(t, g.userinfo("Bearer", tb.AccessToken))
	})

	t.Run("not an access token", func(t *testing.T) {
		g := newProviderRig(t)
		tb := g.redeem(depWiki, wikiCallback)
		flowSealed, _ := g.b.keys.seal("flow", accessGrant{ClientID: depWiki, Sub: "3f2a"}, time.Hour, g.clock.now())
		for _, tok := range []string{tb.IDToken, flowSealed, "garbage"} {
			invalidToken(t, g.userinfo("Bearer", tok))
		}
	})

	t.Run("no token", func(t *testing.T) {
		g := newProviderRig(t)
		if w := g.userinfo("", ""); w.Code != http.StatusUnauthorized || w.Header().Get("WWW-Authenticate") != "Bearer" {
			t.Fatalf("%d %q", w.Code, w.Header().Get("WWW-Authenticate"))
		}
	})
}

// logout calls the end-session endpoint and, as Keycloak would, comes back to
// /signed-out with the state the broker gave it.
func (g *providerRig) endSession(q url.Values) *httptest.ResponseRecorder {
	g.t.Helper()
	w := g.do("GET", "/oidc/logout?"+q.Encode(), nil)
	loc, _ := url.Parse(w.Header().Get("Location"))
	if w.Code != http.StatusFound || loc.Host != "keycloak.example" || loc.Query().Get("post_logout_redirect_uri") != g.b.loginURL+"/signed-out" {
		g.t.Fatalf("logout: %d %s", w.Code, loc)
	}
	return g.do("GET", "/signed-out?"+url.Values{"state": {loc.Query().Get("state")}}.Encode(), nil)
}

func signedOutPage(t *testing.T, w *httptest.ResponseRecorder) {
	t.Helper()
	if w.Code != http.StatusOK || w.Header().Get("Location") != "" || !strings.Contains(w.Body.String(), "signed out of Freepod") {
		t.Fatalf("%d Location=%q", w.Code, w.Header().Get("Location"))
	}
}

func TestEndSession(t *testing.T) {
	root := "https://" + wiki + "/"

	t.Run("returns to the app", func(t *testing.T) {
		g := newProviderRig(t)
		hint := g.redeem(depWiki, wikiCallback).IDToken
		g.clock.t = g.clock.t.Add(24 * time.Hour) // a hint's expiry does not matter
		w := g.endSession(url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {root}, "state": {"bye"}})
		if w.Code != http.StatusFound || w.Header().Get("Location") != root+"?state=bye" {
			t.Fatalf("%d %s", w.Code, w.Header().Get("Location"))
		}
		if g.auth.endSessions != 1 {
			t.Fatal("Keycloak's session was not ended")
		}
	})

	t.Run("by POST, to a declared redirect URI, without state", func(t *testing.T) {
		g := newProviderRig(t)
		hint := g.redeem(depWiki, wikiCallback).IDToken
		form := url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {wikiCallback}}
		w := g.do("POST", "/oidc/logout", form)
		loc, _ := url.Parse(w.Header().Get("Location"))
		back := g.do("GET", "/signed-out?"+url.Values{"state": {loc.Query().Get("state")}}.Encode(), nil)
		if back.Header().Get("Location") != wikiCallback {
			t.Fatalf("%d %s", back.Code, back.Header().Get("Location"))
		}
	})

	foreignKey := mustSigner(t, pkcs1PEM(rsaKeys()[2]))
	cases := map[string]func(g *providerRig, hint string) url.Values{
		"no hint": func(g *providerRig, hint string) url.Values {
			return url.Values{"client_id": {depWiki}, "post_logout_redirect_uri": {root}}
		},
		"hint for another deployment": func(g *providerRig, hint string) url.Values {
			return url.Values{"client_id": {depOther}, "id_token_hint": {hint}, "post_logout_redirect_uri": {"https://" + other + "/"}}
		},
		"no client_id": func(g *providerRig, hint string) url.Values {
			return url.Values{"id_token_hint": {hint}, "post_logout_redirect_uri": {root}}
		},
		"foreign redirect": func(g *providerRig, hint string) url.Values {
			return url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {"https://evil.example/"}}
		},
		"another path on the host": func(g *providerRig, hint string) url.Values {
			return url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {"https://" + wiki + "/shared/page"}}
		},
		"hint signed by someone else": func(g *providerRig, hint string) url.Values {
			forged, _ := foreignKey.idToken(g.b.loginURL, oidcCode{DeploymentID: depWiki, Subject: "3f2a"}, g.clock.now())
			return url.Values{"client_id": {depWiki}, "id_token_hint": {forged}, "post_logout_redirect_uri": {root}}
		},
		"hint from another issuer": func(g *providerRig, hint string) url.Values {
			forged, _ := g.b.oidc.signer.idToken("https://login.dev.freepod.eu", oidcCode{DeploymentID: depWiki, Subject: "3f2a"}, g.clock.now())
			return url.Values{"client_id": {depWiki}, "id_token_hint": {forged}, "post_logout_redirect_uri": {root}}
		},
		"deployment turned SSO off": func(g *providerRig, hint string) url.Values {
			delete(g.st.clients, depWiki)
			return url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {root}}
		},
		"oversized state": func(g *providerRig, hint string) url.Values {
			return url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {root}, "state": {strings.Repeat("s", 513)}}
		},
	}
	for name, params := range cases {
		t.Run(name, func(t *testing.T) {
			g := newProviderRig(t)
			hint := g.redeem(depWiki, wikiCallback).IDToken
			signedOutPage(t, g.endSession(params(g, hint)))
			if g.auth.endSessions != 1 {
				t.Fatal("Keycloak's session was not ended")
			}
		})
	}
}
