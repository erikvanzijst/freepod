package main

import (
	"context"
	"crypto/subtle"
	"errors"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"golang.org/x/oauth2"
)

const (
	flowTTL    = 10 * time.Minute
	consentTTL = 10 * time.Minute
)

// flow is the broker's state for one sign-in while the browser is away at
// Keycloak. It is sealed into a cookie on the login host named after the OIDC
// state, so two tabs signing in at once do not overwrite each other.
type flow struct {
	Host      string `json:"host"`
	RD        string `json:"rd"`
	NonceHash string `json:"n"` // digest of the app host's login cookie
	State     string `json:"state"`
	OIDCNonce string `json:"nonce"`
	Verifier  string `json:"pkce"`
}

// pendingConsent carries an authenticated identity across the consent page.
// CSRF is the token the form must echo back; the cookie is SameSite=Lax, so a
// cross-site POST does not carry it in the first place.
type pendingConsent struct {
	Host         string `json:"host"`
	RD           string `json:"rd"`
	NonceHash    string `json:"n"`
	DeploymentID string `json:"d"`
	Sub          string `json:"sub"`
	Email        string `json:"email"`
	Name         string `json:"name"`
	CSRF         string `json:"csrf"`
}

type identity struct {
	Sub   string
	Email string
	Name  string
}

// authenticator is the Keycloak leg. Tests substitute a stub provider through
// the same interface the real one satisfies.
type authenticator interface {
	authURL(state, nonce, verifier string) (string, error)
	exchange(ctx context.Context, code, verifier, nonce string) (identity, error)
}

var errEmailUnverified = errors.New("email not verified")

type broker struct {
	chrome chrome
	keys   *keyring
	store  store
	auth   authenticator
	now    func() time.Time
	log    *slog.Logger
}

func (b *broker) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /start", b.start)
	mux.HandleFunc("GET /callback", b.callback)
	mux.HandleFunc("POST /consent", b.consent)
	mux.Handle("GET /assets/", assetHandler())
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok\n")) })
	return mux
}

var nonceHashPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)

func (b *broker) start(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	host := normalizeHost(q.Get("host"))
	nonceHash := q.Get("n")
	if host == "" || !nonceHashPattern.MatchString(nonceHash) {
		b.errorPage(w, http.StatusBadRequest, "This sign-in link is incomplete", "Part of the link is missing. Go back to the app and sign in again.")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	if _, ok := b.eligible(ctx, w, host); !ok {
		return
	}

	f := flow{
		Host:      host,
		RD:        safeReturnPath(q.Get("rd")),
		NonceHash: nonceHash,
		State:     randomToken(),
		OIDCNonce: randomToken(),
		Verifier:  oauth2.GenerateVerifier(),
	}
	sealed, err := b.keys.seal("flow", f, flowTTL, b.now())
	if err != nil {
		b.internal(w, "sealing flow", err)
		return
	}
	target, err := b.auth.authURL(f.State, f.OIDCNonce, f.Verifier)
	if err != nil {
		b.log.Error("identity provider unavailable", "err", err)
		b.errorPage(w, http.StatusServiceUnavailable, "Sign-in is temporarily unavailable", "Something on our side isn't answering. Please try again in a moment.")
		return
	}
	setCookie(w, flowCookie+f.State[:16], sealed, int(flowTTL.Seconds()))
	redirect(w, target)
}

func (b *broker) callback(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	state := q.Get("state")
	if len(state) < 16 {
		b.errorPage(w, http.StatusBadRequest, "This sign-in link is incomplete", "Part of the link is missing. Go back to the app and sign in again.")
		return
	}
	cookieName := flowCookie + state[:16]
	var f flow
	var opened bool
	for _, raw := range cookieValues(r.Header, cookieName) {
		if b.keys.open("flow", raw, &f, b.now()) == nil {
			opened = true
			break
		}
	}
	clearCookie(w, cookieName)
	if !opened || subtle.ConstantTimeCompare([]byte(f.State), []byte(state)) != 1 {
		b.errorPage(w, http.StatusBadRequest, "This sign-in expired", "It took too long, or it was started in another browser. Go back to the app and try again.")
		return
	}
	if errCode := q.Get("error"); errCode != "" {
		b.log.Info("identity provider returned an error", "error", errCode)
		renderPage(w, http.StatusBadRequest, page{chrome: b.chrome, Kind: "info", Title: "Sign-in canceled", Message: "Nothing was shared. You can close this page, or go back to the app to try again."})
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	id, err := b.auth.exchange(ctx, q.Get("code"), f.Verifier, f.OIDCNonce)
	if errors.Is(err, errEmailUnverified) {
		renderPage(w, http.StatusForbidden, page{chrome: b.chrome, Kind: "info", Title: "Verify your email first", Message: "Apps can only receive a verified email address. Open the verification email Freepod sent you, then sign in again."})
		return
	}
	if err != nil {
		b.log.Warn("code exchange failed", "err", err)
		b.errorPage(w, http.StatusBadRequest, "Sign-in couldn't be completed", "Go back to the app and try again.")
		return
	}

	deploymentID, ok := b.eligible(ctx, w, f.Host)
	if !ok {
		return
	}
	consented, err := b.store.hasConsent(ctx, id.Sub, deploymentID, disclosedClaims)
	if err != nil {
		b.internal(w, "reading consent", err)
		return
	}
	if consented {
		b.issueCode(ctx, w, f.Host, f.RD, f.NonceHash, id)
		return
	}

	pc := pendingConsent{
		Host: f.Host, RD: f.RD, NonceHash: f.NonceHash, DeploymentID: deploymentID,
		Sub: id.Sub, Email: id.Email, Name: id.Name, CSRF: randomToken(),
	}
	sealed, err := b.keys.seal("consent", pc, consentTTL, b.now())
	if err != nil {
		b.internal(w, "sealing consent", err)
		return
	}
	setCookie(w, consentCookie, sealed, int(consentTTL.Seconds()))
	renderConsent(w, consentView{chrome: b.chrome, Host: pc.Host, Email: pc.Email, Name: pc.Name, ShortSub: shortSub(pc.Sub), CSRF: pc.CSRF})
}

func (b *broker) consent(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4096)
	if err := r.ParseForm(); err != nil {
		b.errorPage(w, http.StatusBadRequest, "Something went wrong", "The form could not be read. Go back to the app and sign in again.")
		return
	}
	var pc pendingConsent
	var opened bool
	for _, raw := range cookieValues(r.Header, consentCookie) {
		if b.keys.open("consent", raw, &pc, b.now()) == nil {
			opened = true
			break
		}
	}
	clearCookie(w, consentCookie)
	if !opened || subtle.ConstantTimeCompare([]byte(pc.CSRF), []byte(r.PostForm.Get("csrf"))) != 1 {
		b.errorPage(w, http.StatusBadRequest, "This page expired", "Nothing was shared. Go back to the app and sign in again.")
		return
	}
	if r.PostForm.Get("decision") != "allow" {
		renderPage(w, http.StatusOK, page{chrome: b.chrome, Kind: "done", Title: "Nothing was shared",
			Message: pc.Host + " did not receive your name, email address or account identifier. You can close this page."})
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	deploymentID, ok := b.eligible(ctx, w, pc.Host)
	if !ok {
		return
	}
	// The app at this hostname may have been replaced while the page was open;
	// consent given to one deployment is never recorded against another.
	if deploymentID != pc.DeploymentID {
		b.errorPage(w, http.StatusConflict, "This app changed", "It was replaced while you were deciding, and nothing was shared. Go back to it and sign in again.")
		return
	}
	if err := b.store.recordConsent(ctx, pc.Sub, deploymentID, disclosedClaims); err != nil {
		b.internal(w, "recording consent", err)
		return
	}
	b.issueCode(ctx, w, pc.Host, pc.RD, pc.NonceHash, identity{Sub: pc.Sub, Email: pc.Email, Name: pc.Name})
}

// eligible checks the host against the platform's records and, when it is not
// an auth-enabled custom deployment, answers the browser itself -- never with a
// redirect, so the broker cannot be used to bounce anyone anywhere.
func (b *broker) eligible(ctx context.Context, w http.ResponseWriter, host string) (string, bool) {
	id, ok, err := b.store.eligible(ctx, host)
	if err != nil {
		b.internal(w, "checking eligibility", err)
		return "", false
	}
	if !ok {
		b.errorPage(w, http.StatusNotFound, "Sign-in isn't available here", host+" does not offer Sign in with Freepod.")
		return "", false
	}
	return id, true
}

func (b *broker) issueCode(ctx context.Context, w http.ResponseWriter, host, rd, nonceHash string, id identity) {
	nonceDigest, err := decodeNonceHash(nonceHash)
	if err != nil {
		b.errorPage(w, http.StatusBadRequest, "This sign-in link is incomplete", "Part of the link is missing. Go back to the app and sign in again.")
		return
	}
	code := randomToken()
	if err := b.store.insertCode(ctx, sha256Bytes(code), codeRecord{
		Host: host, Subject: id.Sub, Email: id.Email, Name: id.Name, ReturnPath: rd, NonceHash: nonceDigest,
	}); err != nil {
		b.internal(w, "storing code", err)
		return
	}
	redirect(w, "https://"+host+reservedPrefix+"callback?"+url.Values{"code": {code}}.Encode())
}

func (b *broker) errorPage(w http.ResponseWriter, status int, title, msg string) {
	renderPage(w, status, page{chrome: b.chrome, Title: title, Message: msg})
}

func (b *broker) internal(w http.ResponseWriter, what string, err error) {
	b.log.Error(what, "err", err)
	b.errorPage(w, http.StatusServiceUnavailable, "Sign-in is temporarily unavailable", "Something on our side isn't answering. Please try again in a moment.")
}

// oidcAuth is the real authenticator: Keycloak through go-oidc. Discovery is
// lazy and retried, so the broker starts even while Keycloak is down and
// recovers without a restart.
type oidcAuth struct {
	issuer, clientID, clientSecret, redirectURL string

	mu       sync.Mutex
	provider *oidc.Provider
}

func (a *oidcAuth) config(ctx context.Context) (*oauth2.Config, *oidc.IDTokenVerifier, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.provider == nil {
		p, err := oidc.NewProvider(ctx, a.issuer)
		if err != nil {
			return nil, nil, err
		}
		a.provider = p
	}
	cfg := &oauth2.Config{
		ClientID:     a.clientID,
		ClientSecret: a.clientSecret,
		Endpoint:     a.provider.Endpoint(),
		RedirectURL:  a.redirectURL,
		Scopes:       []string{oidc.ScopeOpenID, "email", "profile"},
	}
	return cfg, a.provider.Verifier(&oidc.Config{ClientID: a.clientID}), nil
}

func (a *oidcAuth) authURL(state, nonce, verifier string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cfg, _, err := a.config(ctx)
	if err != nil {
		return "", err
	}
	return cfg.AuthCodeURL(state, oidc.Nonce(nonce), oauth2.S256ChallengeOption(verifier)), nil
}

// exchange trades the code for tokens, verifies the ID token, and keeps only
// the three claims the consent page names. The tokens themselves go out of
// scope here: nothing stores them, and nothing sends them anywhere.
func (a *oidcAuth) exchange(ctx context.Context, code, verifier, nonce string) (identity, error) {
	cfg, idVerifier, err := a.config(ctx)
	if err != nil {
		return identity{}, err
	}
	tok, err := cfg.Exchange(ctx, code, oauth2.VerifierOption(verifier))
	if err != nil {
		return identity{}, err
	}
	rawID, _ := tok.Extra("id_token").(string)
	if rawID == "" {
		return identity{}, errors.New("no id_token in token response")
	}
	idt, err := idVerifier.Verify(ctx, rawID)
	if err != nil {
		return identity{}, err
	}
	if subtle.ConstantTimeCompare([]byte(idt.Nonce), []byte(nonce)) != 1 {
		return identity{}, errors.New("id_token nonce mismatch")
	}
	var claims struct {
		Email             string `json:"email"`
		EmailVerified     bool   `json:"email_verified"`
		Name              string `json:"name"`
		PreferredUsername string `json:"preferred_username"`
	}
	if err := idt.Claims(&claims); err != nil {
		return identity{}, err
	}
	if !claims.EmailVerified || claims.Email == "" {
		return identity{}, errEmailUnverified
	}
	name := strings.TrimSpace(claims.Name)
	if name == "" {
		name = claims.PreferredUsername
	}
	return identity{Sub: idt.Subject, Email: claims.Email, Name: name}, nil
}
