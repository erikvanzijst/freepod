package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
)

// Signing a browser out of the apps it used when its Keycloak session ends
// (app-sign-out): Keycloak posts a logout token here, app-auth records the
// session as ended -- which the verifier applies to header apps -- and sends
// each OIDC app the browser signed in to a logout token of its own.

const (
	// logoutTokenAge is how old a token from Keycloak may be, as Immich and
	// most relying parties also allow; logoutSkew is how far its clock may
	// run ahead of ours.
	logoutTokenAge = 2 * time.Minute
	logoutSkew     = 5 * time.Second
	// logoutTimeout bounds one delivery to one app, lookup included.
	logoutTimeout = 10 * time.Second
	// maxLogoutDeliveries is how many apps one ended session reaches at once.
	maxLogoutDeliveries = 8
)

// newLogoutClient never follows a redirect: a logout token goes to the path
// the template declares, and nowhere an app might bounce it.
func newLogoutClient() *http.Client {
	return &http.Client{
		Timeout:       logoutTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

// backchannelLogout answers Keycloak once the session is recorded as ended,
// and contacts the apps afterwards: Keycloak waits on this answer while the
// user waits on Keycloak.
func (b *broker) backchannelLogout(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	r.Body = http.MaxBytesReader(w, r.Body, 16384)
	if err := r.ParseForm(); err != nil {
		http.Error(w, "unreadable request", http.StatusBadRequest)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	sid, err := b.auth.verifyLogout(ctx, r.PostForm.Get("logout_token"), b.now())
	if err != nil {
		b.log.Warn("refused a logout token", "err", err)
		http.Error(w, "invalid logout token", http.StatusBadRequest)
		return
	}
	ended, err := b.store.endSession(ctx, sid)
	if err != nil {
		b.log.Error("recording an ended session", "err", err)
		http.Error(w, "temporarily unavailable", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusOK)
	b.log.Info("a Keycloak session ended", "apps", len(ended))
	if len(ended) == 0 {
		return
	}
	b.signOuts.Add(1)
	go func() {
		defer b.signOuts.Done()
		b.deliverLogouts(ended)
	}()
}

// deliverLogouts sends every app in ended its logout token, a few at a time.
// Each is sent once; a failure is logged and never retried (D7).
func (b *broker) deliverLogouts(ended []signIn) {
	sem := make(chan struct{}, maxLogoutDeliveries)
	var wg sync.WaitGroup
	for _, s := range ended {
		wg.Add(1)
		sem <- struct{}{}
		go func(s signIn) {
			defer wg.Done()
			defer func() { <-sem }()
			b.deliverLogout(s)
		}(s)
	}
	wg.Wait()
}

func (b *broker) deliverLogout(s signIn) {
	log := b.log.With("deployment", s.DeploymentID)
	ctx, cancel := context.WithTimeout(context.Background(), logoutTimeout)
	defer cancel()
	client, ok, err := b.store.ssoClient(ctx, s.DeploymentID)
	switch {
	case err != nil:
		log.Warn("sign-out not sent: looking up the app", "err", err)
		return
	case !ok || client.LogoutURI == "":
		log.Info("sign-out not sent: the app takes no logout tokens")
		return
	case b.oidc == nil:
		log.Warn("sign-out not sent: the OpenID Provider is disabled")
		return
	}
	tok, err := b.oidc.signer.logoutToken(b.loginURL, s.DeploymentID, s.Subject, s.SID, b.now())
	if err != nil {
		log.Error("sign-out not sent: signing the logout token", "err", err)
		return
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, client.LogoutURI,
		strings.NewReader(url.Values{"logout_token": {tok}}.Encode()))
	if err != nil {
		log.Error("sign-out not sent", "err", err)
		return
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := b.logoutClient.Do(req)
	if err != nil {
		log.Warn("sign-out not delivered", "uri", client.LogoutURI, "err", err)
		return
	}
	io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		log.Warn("sign-out refused by the app", "uri", client.LogoutURI, "status", resp.StatusCode)
		return
	}
	log.Info("signed a browser out of an app", "uri", client.LogoutURI)
}

// verifyLogout checks a logout token from Keycloak (D2) and returns the
// session it ends. Logout tokens need not carry exp, so their age is judged by
// iat instead; requiring the event and refusing a nonce keeps an ID token from
// ever passing for one.
func (a *oidcAuth) verifyLogout(ctx context.Context, raw string, now time.Time) (string, error) {
	if raw == "" {
		return "", errors.New("no logout_token")
	}
	if _, _, err := a.config(ctx); err != nil {
		return "", err
	}
	a.mu.Lock()
	v := a.provider.Verifier(&oidc.Config{ClientID: a.clientID, SkipExpiryCheck: true})
	a.mu.Unlock()
	tok, err := v.Verify(ctx, raw)
	if err != nil {
		return "", err
	}
	if tok.IssuedAt.IsZero() || now.Sub(tok.IssuedAt) > logoutTokenAge+logoutSkew || tok.IssuedAt.Sub(now) > logoutSkew {
		return "", errors.New("logout token issued too long ago, or in the future")
	}
	var c struct {
		SID    string                     `json:"sid"`
		Events map[string]json.RawMessage `json:"events"`
		Nonce  *string                    `json:"nonce"`
	}
	if err := tok.Claims(&c); err != nil {
		return "", err
	}
	if _, ok := c.Events[backchannelLogoutEvent]; !ok {
		return "", errors.New("not a back-channel logout event")
	}
	if c.Nonce != nil {
		return "", errors.New("logout token carries a nonce")
	}
	if c.SID == "" {
		return "", errors.New("logout token names no session")
	}
	return c.SID, nil
}
