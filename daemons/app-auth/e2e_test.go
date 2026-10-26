package main

import (
	"context"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"golang.org/x/oauth2"
)

// TestOIDCClientEndToEnd drives a stock x/oauth2 + go-oidc relying party
// through authorize, Keycloak (the stub provider), consent, token and
// userinfo, with the broker on a real TLS listener so its __Host- cookies
// travel as they would in a browser.
func TestOIDCClientEndToEnd(t *testing.T) {
	idp := newStubIdP(t)
	st := newMemStore(time.Now)
	b := &broker{
		keys: mustKeyring(t, "k1:"+testKey('a')), store: st, auth: idp.auth(), now: time.Now, log: quiet,
		oidc: &provider{clientKeys: mustKeyring(t, clientKeys), signer: mustSigner(t, pkcs1PEM(rsaKeys()[0]))},
	}
	srv := httptest.NewTLSServer(b.routes())
	t.Cleanup(srv.Close)
	b.loginURL = srv.URL
	b.chrome = newChrome(srv.URL)
	st.clients[depWiki] = memClient{host: wiki, paths: `["/oidc/callback"]`}

	ctx := oidc.ClientContext(context.Background(), srv.Client())
	op, err := oidc.NewProvider(ctx, srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	app := oauth2.Config{
		ClientID: depWiki, ClientSecret: b.oidc.clientKeys.clientSecret(depWiki),
		Endpoint: op.Endpoint(), RedirectURL: wikiCallback,
		Scopes: []string{oidc.ScopeOpenID, "email", "profile"},
	}
	verifier := oauth2.GenerateVerifier()
	authURL := app.AuthCodeURL("app-state", oidc.Nonce("app-nonce"), oauth2.S256ChallengeOption(verifier))

	jar, _ := cookiejar.New(nil)
	browser := srv.Client()
	browser.Jar = jar
	browser.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	get := func(u string) *http.Response {
		t.Helper()
		resp, err := browser.Get(u)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { resp.Body.Close() })
		return resp
	}

	toKeycloak := get(authURL)
	if toKeycloak.StatusCode != http.StatusFound {
		t.Fatalf("authorize: %d", toKeycloak.StatusCode)
	}
	kcLoc, _ := url.Parse(toKeycloak.Header.Get("Location"))
	authTime := time.Now().Add(-time.Minute).Truncate(time.Second)
	kcCode := idp.authorize(t, kcLoc.String(), map[string]any{
		"email": "alice@example.com", "email_verified": true, "name": "Alice", "auth_time": authTime.Unix(),
	})
	consentPage := get(srv.URL + "/callback?" + url.Values{"code": {kcCode}, "state": {kcLoc.Query().Get("state")}}.Encode())
	raw, _ := io.ReadAll(consentPage.Body)
	page := string(raw)
	if consentPage.StatusCode != 200 || !strings.Contains(page, wiki) {
		t.Fatalf("consent page: %d", consentPage.StatusCode)
	}
	back, err := browser.PostForm(srv.URL+"/consent", url.Values{"csrf": {formValue(t, page, "csrf")}, "decision": {"allow"}})
	if err != nil {
		t.Fatal(err)
	}
	back.Body.Close()
	cb, _ := url.Parse(back.Header.Get("Location"))
	if back.StatusCode != http.StatusFound || cb.Scheme+"://"+cb.Host+cb.Path != wikiCallback || cb.Query().Get("state") != "app-state" {
		t.Fatalf("back to the app: %d %s", back.StatusCode, cb)
	}

	tok, err := app.Exchange(ctx, cb.Query().Get("code"), oauth2.VerifierOption(verifier))
	if err != nil {
		t.Fatal(err)
	}
	if tok.RefreshToken != "" {
		t.Fatal("issued a refresh token")
	}
	rawID, _ := tok.Extra("id_token").(string)
	idt, err := op.Verifier(&oidc.Config{ClientID: depWiki}).Verify(ctx, rawID)
	if err != nil {
		t.Fatal(err)
	}
	var claims struct {
		Email         string `json:"email"`
		EmailVerified bool   `json:"email_verified"`
		Name          string `json:"name"`
		AuthTime      int64  `json:"auth_time"`
	}
	idt.Claims(&claims)
	if idt.Subject != "3f2a" || idt.Nonce != "app-nonce" || claims.Email != "alice@example.com" || !claims.EmailVerified ||
		claims.Name != "Alice" || claims.AuthTime != authTime.Unix() {
		t.Fatalf("ID token %+v %+v", idt, claims)
	}

	ui, err := op.UserInfo(ctx, oauth2.StaticTokenSource(tok))
	if err != nil {
		t.Fatal(err)
	}
	if ui.Subject != "3f2a" || ui.Email != "alice@example.com" || !ui.EmailVerified {
		t.Fatalf("userinfo %+v", ui)
	}

	if _, err := app.Exchange(ctx, cb.Query().Get("code"), oauth2.VerifierOption(verifier)); err == nil {
		t.Fatal("the code redeemed twice")
	}
}
