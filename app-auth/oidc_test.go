package main

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"testing"
	"time"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

// stubIdP is a minimal OpenID provider: discovery, JWKS, and a token endpoint
// that enforces PKCE and signs an ID token with whatever claims a test set.
// Enough to run the real go-oidc path end to end without Keycloak.
type stubIdP struct {
	srv    *httptest.Server
	key    *rsa.PrivateKey
	mu     sync.Mutex
	grants map[string]grant // code -> what the token endpoint returns
}

type grant struct {
	challenge string
	claims    map[string]any
}

func newStubIdP(t *testing.T) *stubIdP {
	t.Helper()
	key, _ := rsa.GenerateKey(rand.Reader, 2048)
	p := &stubIdP{key: key, grants: map[string]grant{}}
	mux := http.NewServeMux()
	p.srv = httptest.NewServer(mux)
	t.Cleanup(p.srv.Close)
	iss := p.srv.URL

	mux.HandleFunc("/.well-known/openid-configuration", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{
			"issuer": iss, "authorization_endpoint": iss + "/auth", "token_endpoint": iss + "/token",
			"jwks_uri": iss + "/jwks", "id_token_signing_alg_values_supported": []string{"RS256"},
		})
	})
	mux.HandleFunc("/jwks", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(jose.JSONWebKeySet{Keys: []jose.JSONWebKey{{Key: &key.PublicKey, KeyID: "k", Algorithm: "RS256", Use: "sig"}}})
	})
	mux.HandleFunc("/token", func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		p.mu.Lock()
		g, ok := p.grants[r.PostForm.Get("code")]
		delete(p.grants, r.PostForm.Get("code"))
		p.mu.Unlock()
		sum := sha256.Sum256([]byte(r.PostForm.Get("code_verifier")))
		if !ok || base64.RawURLEncoding.EncodeToString(sum[:]) != g.challenge {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]string{"error": "invalid_grant"})
			return
		}
		signer, _ := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: key}, (&jose.SignerOptions{}).WithHeader("kid", "k"))
		idToken, _ := jwt.Signed(signer).Claims(g.claims).Serialize()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{"access_token": "at", "token_type": "Bearer", "expires_in": 60, "id_token": idToken})
	})
	return p
}

// authorize plays the browser at the authorization endpoint: it reads the
// challenge and nonce the broker put in the URL and mints a code for them.
func (p *stubIdP) authorize(t *testing.T, authURL string, claims map[string]any) string {
	t.Helper()
	u, err := url.Parse(authURL)
	if err != nil {
		t.Fatal(err)
	}
	q := u.Query()
	if q.Get("code_challenge_method") != "S256" || q.Get("code_challenge") == "" {
		t.Fatalf("authorization URL without S256 PKCE: %s", authURL)
	}
	full := map[string]any{
		"iss": p.srv.URL, "aud": "freepod-apps-dev", "sub": "3f2a",
		"iat": time.Now().Unix(), "exp": time.Now().Add(time.Minute).Unix(), "nonce": q.Get("nonce"),
	}
	for k, v := range claims {
		full[k] = v
	}
	code := randomToken()
	p.mu.Lock()
	p.grants[code] = grant{challenge: q.Get("code_challenge"), claims: full}
	p.mu.Unlock()
	return code
}

func (p *stubIdP) auth() *oidcAuth {
	return &oidcAuth{issuer: p.srv.URL, clientID: "freepod-apps-dev", clientSecret: "s", redirectURL: "https://login.example/callback"}
}

func TestOIDCExchange(t *testing.T) {
	p := newStubIdP(t)
	ctx := context.Background()
	verified := map[string]any{"email": "alice@example.com", "email_verified": true, "name": "Alice"}

	t.Run("success", func(t *testing.T) {
		a := p.auth()
		u, err := a.authURL("state", "nonce-1", "verifier-1-verifier-1-verifier-1-verifier-1")
		if err != nil {
			t.Fatal(err)
		}
		code := p.authorize(t, u, verified)
		id, err := a.exchange(ctx, code, "verifier-1-verifier-1-verifier-1-verifier-1", "nonce-1")
		if err != nil {
			t.Fatal(err)
		}
		if id != (identity{Sub: "3f2a", Email: "alice@example.com", Name: "Alice"}) {
			t.Fatalf("identity %+v", id)
		}
	})

	t.Run("unverified email", func(t *testing.T) {
		a := p.auth()
		u, _ := a.authURL("s", "n", "verifier-2-verifier-2-verifier-2-verifier-2")
		code := p.authorize(t, u, map[string]any{"email": "a@x", "email_verified": false})
		if _, err := a.exchange(ctx, code, "verifier-2-verifier-2-verifier-2-verifier-2", "n"); !errors.Is(err, errEmailUnverified) {
			t.Fatalf("got %v, want errEmailUnverified", err)
		}
	})

	t.Run("nonce mismatch", func(t *testing.T) {
		a := p.auth()
		u, _ := a.authURL("s", "real-nonce", "verifier-3-verifier-3-verifier-3-verifier-3")
		code := p.authorize(t, u, verified)
		if _, err := a.exchange(ctx, code, "verifier-3-verifier-3-verifier-3-verifier-3", "other-nonce"); err == nil {
			t.Fatal("accepted an ID token minted for another sign-in")
		}
	})

	t.Run("wrong PKCE verifier", func(t *testing.T) {
		a := p.auth()
		u, _ := a.authURL("s", "n", "verifier-4-verifier-4-verifier-4-verifier-4")
		code := p.authorize(t, u, verified)
		if _, err := a.exchange(ctx, code, "someone-elses-verifier-someone-elses-verifier", "n"); err == nil {
			t.Fatal("exchanged a code without its PKCE verifier")
		}
	})

	t.Run("token for another client", func(t *testing.T) {
		a := p.auth()
		u, _ := a.authURL("s", "n", "verifier-5-verifier-5-verifier-5-verifier-5")
		code := p.authorize(t, u, map[string]any{"aud": "freepod-prod", "email": "a@x", "email_verified": true})
		if _, err := a.exchange(ctx, code, "verifier-5-verifier-5-verifier-5-verifier-5", "n"); err == nil {
			t.Fatal("accepted an ID token for another audience")
		}
	})
}

func TestOIDCDiscoveryRecovers(t *testing.T) {
	a := &oidcAuth{issuer: "http://127.0.0.1:1", clientID: "c"}
	if _, err := a.authURL("s", "n", "v"); err == nil {
		t.Fatal("expected an error while the provider is unreachable")
	}
	p := newStubIdP(t)
	a.issuer = p.srv.URL
	if _, err := a.authURL("s", "n", "v"); err != nil {
		t.Fatalf("did not recover once the provider came back: %v", err)
	}
}
