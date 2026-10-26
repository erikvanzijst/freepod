package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"golang.org/x/oauth2"
)

// The broker's third role: an OpenID Provider for SSO-enabled deployments, at
// the login host, authenticating users through the same Keycloak leg and
// consent as header authentication. See the app-oidc-provider design doc.
type provider struct {
	clientKeys *keyring
	signer     *signer
}

// D8: every authorization request is sealed into a cookie, so its size is
// capped before anything is set.
const (
	maxStateLen       = 512
	maxNonceLen       = 256
	maxRedirectURILen = 2048
)

var (
	challengePattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
	// RFC 7636 §4.1.
	verifierPattern = regexp.MustCompile(`^[A-Za-z0-9._~-]{43,128}$`)
)

// oidcRequest is a validated authorization request, carried through the
// Keycloak leg in the flow cookie and across the consent page.
type oidcRequest struct {
	ClientID     string `json:"cid"`
	RedirectURI  string `json:"ru"`
	State        string `json:"st,omitempty"`
	Nonce        string `json:"no,omitempty"`
	Challenge    string `json:"cc,omitempty"`
	PromptNone   bool   `json:"pn,omitempty"`
	ForceConsent bool   `json:"pc,omitempty"`
}

func (b *broker) providerRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /.well-known/openid-configuration", b.discovery)
	mux.HandleFunc("GET /oidc/jwks", b.jwks)
	mux.HandleFunc("GET /oidc/authorize", b.authorize)
	mux.HandleFunc("POST /oidc/token", b.token)
	mux.HandleFunc("GET /oidc/userinfo", b.userinfo)
	mux.HandleFunc("POST /oidc/userinfo", b.userinfo)
	mux.HandleFunc("GET /oidc/logout", b.oidcLogout)
	mux.HandleFunc("POST /oidc/logout", b.oidcLogout)
}

func (b *broker) discovery(w http.ResponseWriter, r *http.Request) {
	iss := b.loginURL
	publicJSON(w, map[string]any{
		"issuer":                                iss,
		"authorization_endpoint":                iss + "/oidc/authorize",
		"token_endpoint":                        iss + "/oidc/token",
		"userinfo_endpoint":                     iss + "/oidc/userinfo",
		"jwks_uri":                              iss + "/oidc/jwks",
		"end_session_endpoint":                  iss + "/oidc/logout",
		"scopes_supported":                      []string{"openid", "email", "profile"},
		"response_types_supported":              []string{"code"},
		"response_modes_supported":              []string{"query"},
		"grant_types_supported":                 []string{"authorization_code"},
		"subject_types_supported":               []string{"public"},
		"id_token_signing_alg_values_supported": []string{"RS256"},
		"token_endpoint_auth_methods_supported": []string{"client_secret_basic", "client_secret_post"},
		"code_challenge_methods_supported":      []string{"S256"},
		"claims_supported":                      []string{"iss", "aud", "azp", "sub", "email", "email_verified", "name", "iat", "exp", "auth_time", "nonce"},
		"prompt_values_supported":               []string{"none", "login", "consent", "select_account"},
		"claims_parameter_supported":            false,
		"request_parameter_supported":           false,
		"request_uri_parameter_supported":       false,
	})
}

func (b *broker) jwks(w http.ResponseWriter, r *http.Request) {
	publicJSON(w, b.oidc.signer.jwks)
}

// publicJSON serves metadata any app may fetch, from a server or a browser.
func publicJSON(w http.ResponseWriter, v any) {
	h := w.Header()
	h.Set("Content-Type", "application/json")
	h.Set("Access-Control-Allow-Origin", "*")
	h.Set("Cache-Control", "public, max-age=300")
	h.Set("X-Content-Type-Options", "nosniff")
	json.NewEncoder(w).Encode(v)
}

// oidcClient looks up a client and checks a redirect URI against it. Until
// both pass, every failure is a page on the login host, never a redirect (D4).
func (b *broker) oidcClient(ctx context.Context, w http.ResponseWriter, clientID, redirectURI string) (ssoClient, bool) {
	c, ok, err := b.store.ssoClient(ctx, clientID)
	if err != nil {
		b.internal(w, "looking up OIDC client", err)
		return ssoClient{}, false
	}
	if ok && len(c.Ignored) > 0 {
		b.log.Warn("ignoring template SSO entries that break the redirect rules", "deployment", c.ID, "entries", c.Ignored)
	}
	if !ok {
		b.errorPage(w, http.StatusBadRequest, "Sign-in isn't available here", "This app is not set up for Sign in with Freepod.")
		return ssoClient{}, false
	}
	if !c.allowsRedirect(redirectURI) {
		b.errorPage(w, http.StatusBadRequest, "This sign-in link isn't valid", "The app asked to return to an address it may not use. Nothing was shared.")
		return ssoClient{}, false
	}
	return c, true
}

// redirectError returns an OAuth 2.0 error to a validated redirect URI.
func redirectError(w http.ResponseWriter, redirectURI, code, description, state string) {
	v := url.Values{"error": {code}}
	if description != "" {
		v.Set("error_description", description)
	}
	if state != "" {
		v.Set("state", state)
	}
	redirect(w, withQuery(redirectURI, v))
}

var keycloakPrompts = map[string]bool{"none": true, "login": true, "select_account": true}

func (b *broker) authorize(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if len(q["client_id"]) > 1 || len(q["redirect_uri"]) > 1 {
		b.errorPage(w, http.StatusBadRequest, "This sign-in link isn't valid", "Go back to the app and sign in again.")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	redirectURI := q.Get("redirect_uri")
	client, ok := b.oidcClient(ctx, w, q.Get("client_id"), redirectURI)
	if !ok {
		return
	}

	state := q.Get("state")
	if len(state) > maxStateLen {
		state = ""
	}
	fail := func(code, description string) { redirectError(w, redirectURI, code, description, state) }
	for k, v := range q {
		if len(v) > 1 {
			fail("invalid_request", "repeated parameter "+k)
			return
		}
	}
	challenge, method := q.Get("code_challenge"), q.Get("code_challenge_method")
	switch {
	case len(q.Get("state")) > maxStateLen:
		fail("invalid_request", "state is too long")
		return
	case len(q.Get("nonce")) > maxNonceLen:
		fail("invalid_request", "nonce is too long")
		return
	case len(redirectURI) > maxRedirectURILen:
		fail("invalid_request", "redirect_uri is too long")
		return
	case challenge != "" && !challengePattern.MatchString(challenge):
		fail("invalid_request", "code_challenge must be an S256 challenge")
		return
	}

	switch rt := q.Get("response_type"); {
	case rt == "":
		fail("invalid_request", "response_type is required")
		return
	case rt != "code":
		fail("unsupported_response_type", "only the authorization code flow is supported")
		return
	}
	if rm := q.Get("response_mode"); rm != "" && rm != "query" {
		fail("invalid_request", "only response_mode=query is supported")
		return
	}
	if q.Has("request") {
		fail("request_not_supported", "")
		return
	}
	if q.Has("request_uri") {
		fail("request_uri_not_supported", "")
		return
	}
	if !slices.Contains(strings.Fields(q.Get("scope")), "openid") {
		fail("invalid_scope", "the openid scope is required")
		return
	}
	// D5: S256 only, required unless the template opts out, and always for a
	// native redirect URI.
	switch {
	case challenge == "" && method != "":
		fail("invalid_request", "code_challenge_method without code_challenge")
		return
	case challenge == "" && (client.PKCE || client.isNativeRedirect(redirectURI)):
		fail("invalid_request", "code_challenge is required")
		return
	case challenge != "" && method != "S256":
		fail("invalid_request", "code_challenge_method must be S256")
		return
	}

	prompts := strings.Fields(q.Get("prompt"))
	var kcPrompt []string
	for _, p := range prompts {
		if p != "consent" && !keycloakPrompts[p] {
			fail("invalid_request", "unsupported prompt value")
			return
		}
		if keycloakPrompts[p] {
			kcPrompt = append(kcPrompt, p)
		}
	}
	promptNone := slices.Contains(prompts, "none")
	if promptNone && len(prompts) > 1 {
		fail("invalid_request", "prompt=none cannot be combined")
		return
	}
	maxAge := q.Get("max_age")
	if maxAge != "" {
		if n, err := strconv.Atoi(maxAge); err != nil || n < 0 {
			fail("invalid_request", "max_age must be a non-negative integer")
			return
		}
	}

	f := flow{
		Host:      client.Hostname,
		State:     randomToken(),
		OIDCNonce: randomToken(),
		Verifier:  oauth2.GenerateVerifier(),
		OIDC: &oidcRequest{
			ClientID: client.ID, RedirectURI: redirectURI, State: state, Nonce: q.Get("nonce"),
			Challenge: challenge, PromptNone: promptNone, ForceConsent: slices.Contains(prompts, "consent"),
		},
	}
	sealed, err := b.keys.seal("flow", f, flowTTL, b.now())
	if err != nil {
		b.internal(w, "sealing flow", err)
		return
	}
	target, err := b.auth.authURL(f.State, f.OIDCNonce, f.Verifier, authParams{prompt: strings.Join(kcPrompt, " "), maxAge: maxAge})
	if err != nil {
		b.log.Error("identity provider unavailable", "err", err)
		fail("temporarily_unavailable", "")
		return
	}
	setCookie(w, flowCookie+f.State[:16], sealed, int(flowTTL.Seconds()))
	redirect(w, target)
}

// idpErrors are the Keycloak errors an app can act on; anything else reaches
// it as server_error.
var idpErrors = map[string]bool{
	"login_required": true, "interaction_required": true, "consent_required": true,
	"account_selection_required": true, "access_denied": true, "temporarily_unavailable": true,
}

// oidcCallback finishes the Keycloak leg of an OIDC sign-in.
func (b *broker) oidcCallback(w http.ResponseWriter, r *http.Request, f flow) {
	q := r.URL.Query()
	req := f.OIDC
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	client, ok := b.oidcClient(ctx, w, req.ClientID, req.RedirectURI)
	if !ok {
		return
	}
	if errCode := q.Get("error"); errCode != "" {
		b.log.Info("identity provider returned an error", "error", errCode)
		if !idpErrors[errCode] {
			errCode = "server_error"
		}
		redirectError(w, req.RedirectURI, errCode, "", req.State)
		return
	}
	id, ok := b.exchange(ctx, w, q.Get("code"), f)
	if !ok {
		return
	}
	consented, err := b.store.hasConsent(ctx, id.Sub, client.ID, disclosedClaims)
	if err != nil {
		b.internal(w, "reading consent", err)
		return
	}
	if consented && !req.ForceConsent {
		b.issueOIDCCode(ctx, w, req, id)
		return
	}
	if req.PromptNone {
		redirectError(w, req.RedirectURI, "consent_required", "", req.State)
		return
	}

	pc := pendingConsent{
		Host: client.Hostname, DeploymentID: client.ID,
		Sub: id.Sub, Email: id.Email, Name: id.Name, CSRF: randomToken(),
		OIDC: req, AuthTime: id.AuthTime.Unix(),
	}
	sealed, err := b.keys.seal("consent", pc, consentTTL, b.now())
	if err != nil {
		b.internal(w, "sealing consent", err)
		return
	}
	setCookie(w, consentCookie, sealed, int(consentTTL.Seconds()))
	v := consentView{chrome: b.chrome, Host: pc.Host, Email: pc.Email, Name: pc.Name, ShortSub: shortSub(pc.Sub), CSRF: pc.CSRF}
	// D7: browsers apply form-action to the redirect that answers the form, so
	// a native app's scheme must be allowed on this page, and only that one.
	if client.isNativeRedirect(req.RedirectURI) {
		scheme, _, _ := strings.Cut(req.RedirectURI, ":")
		v.FormAction = scheme + ":"
	}
	renderConsent(w, v)
}

// oidcConsent finishes an OIDC sign-in from the consent page.
func (b *broker) oidcConsent(w http.ResponseWriter, r *http.Request, pc pendingConsent) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	req := pc.OIDC
	client, ok := b.oidcClient(ctx, w, req.ClientID, req.RedirectURI)
	if !ok {
		return
	}
	if r.PostForm.Get("decision") != "allow" {
		redirectError(w, req.RedirectURI, "access_denied", "", req.State)
		return
	}
	if err := b.store.recordConsent(ctx, pc.Sub, client.ID, disclosedClaims); err != nil {
		b.internal(w, "recording consent", err)
		return
	}
	b.issueOIDCCode(ctx, w, req, identity{Sub: pc.Sub, Email: pc.Email, Name: pc.Name, AuthTime: time.Unix(pc.AuthTime, 0)})
}

func (b *broker) issueOIDCCode(ctx context.Context, w http.ResponseWriter, req *oidcRequest, id identity) {
	code := randomToken()
	if err := b.store.insertOIDCCode(ctx, sha256Bytes(code), oidcCode{
		DeploymentID: req.ClientID, RedirectURI: req.RedirectURI,
		Subject: id.Sub, Email: id.Email, Name: id.Name,
		Nonce: req.Nonce, CodeChallenge: req.Challenge, AuthTime: id.AuthTime,
	}); err != nil {
		b.internal(w, "storing OIDC code", err)
		return
	}
	v := url.Values{"code": {code}}
	if req.State != "" {
		v.Set("state", req.State)
	}
	redirect(w, withQuery(req.RedirectURI, v))
}

// tokenResponse writes a token endpoint answer, which no cache may keep.
func tokenResponse(w http.ResponseWriter, status int, v any) {
	h := w.Header()
	h.Set("Content-Type", "application/json")
	h.Set("Cache-Control", "no-store")
	h.Set("Pragma", "no-cache")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func tokenError(w http.ResponseWriter, status int, code, description string) {
	body := map[string]string{"error": code}
	if description != "" {
		body["error_description"] = description
	}
	tokenResponse(w, status, body)
}

func (b *broker) token(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 8192)
	if err := r.ParseForm(); err != nil {
		tokenError(w, http.StatusBadRequest, "invalid_request", "the request body could not be read")
		return
	}
	form := r.PostForm
	for k, v := range form {
		if len(v) > 1 {
			tokenError(w, http.StatusBadRequest, "invalid_request", "repeated parameter "+k)
			return
		}
	}

	basicID, basicSecret, hasBasic := r.BasicAuth()
	if hasBasic && form.Has("client_secret") {
		tokenError(w, http.StatusBadRequest, "invalid_request", "more than one client authentication method")
		return
	}
	clientID, secret := form.Get("client_id"), form.Get("client_secret")
	badClient := func() {
		if hasBasic {
			w.Header().Set("WWW-Authenticate", `Basic realm="`+b.loginURL+`"`)
		}
		tokenError(w, http.StatusUnauthorized, "invalid_client", "")
	}
	if hasBasic {
		// RFC 6749 §2.3.1: both halves are form-encoded before Basic encoding.
		id, err1 := url.QueryUnescape(basicID)
		s, err2 := url.QueryUnescape(basicSecret)
		if err1 != nil || err2 != nil || (clientID != "" && clientID != id) {
			badClient()
			return
		}
		clientID, secret = id, s
	}
	if clientID == "" || secret == "" || !b.oidc.clientKeys.verifyClientSecret(clientID, secret) {
		badClient()
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	client, ok, err := b.store.ssoClient(ctx, clientID)
	if err != nil {
		b.log.Error("looking up OIDC client", "err", err)
		tokenError(w, http.StatusServiceUnavailable, "temporarily_unavailable", "")
		return
	}
	if !ok {
		badClient()
		return
	}

	if form.Get("grant_type") != "authorization_code" {
		tokenError(w, http.StatusBadRequest, "unsupported_grant_type", "")
		return
	}
	code := form.Get("code")
	if code == "" {
		tokenError(w, http.StatusBadRequest, "invalid_request", "code is required")
		return
	}
	rec, fresh, found, err := b.store.redeemOIDCCode(ctx, sha256Bytes(code))
	if err != nil {
		b.log.Error("redeeming OIDC code", "err", err)
		tokenError(w, http.StatusServiceUnavailable, "temporarily_unavailable", "")
		return
	}
	if !found || !fresh || rec.DeploymentID != client.ID || form.Get("redirect_uri") != rec.RedirectURI {
		tokenError(w, http.StatusBadRequest, "invalid_grant", "")
		return
	}
	verifier := form.Get("code_verifier")
	if rec.CodeChallenge == "" {
		// RFC 9700 §2.1.1: a verifier for a code issued without a challenge
		// is a downgrade attempt.
		if verifier != "" {
			tokenError(w, http.StatusBadRequest, "invalid_grant", "")
			return
		}
	} else {
		sum := sha256.Sum256([]byte(verifier))
		if !verifierPattern.MatchString(verifier) ||
			subtle.ConstantTimeCompare([]byte(base64.RawURLEncoding.EncodeToString(sum[:])), []byte(rec.CodeChallenge)) != 1 {
			tokenError(w, http.StatusBadRequest, "invalid_grant", "")
			return
		}
	}

	now := b.now()
	idToken, err := b.oidc.signer.idToken(b.loginURL, rec, now)
	if err != nil {
		b.log.Error("signing ID token", "err", err)
		tokenError(w, http.StatusInternalServerError, "server_error", "")
		return
	}
	access, err := b.keys.seal(accessPurpose, accessGrant{ClientID: client.ID, Sub: rec.Subject, Email: rec.Email, Name: rec.Name}, accessTokenTTL, now)
	if err != nil {
		b.log.Error("sealing access token", "err", err)
		tokenError(w, http.StatusInternalServerError, "server_error", "")
		return
	}
	tokenResponse(w, http.StatusOK, map[string]any{
		"access_token": access,
		"token_type":   "Bearer",
		"expires_in":   int(accessTokenTTL.Seconds()),
		"id_token":     idToken,
		"scope":        "openid email profile",
	})
}

func (b *broker) userinfo(w http.ResponseWriter, r *http.Request) {
	invalid := func() {
		w.Header().Set("WWW-Authenticate", `Bearer error="invalid_token"`)
		tokenError(w, http.StatusUnauthorized, "invalid_token", "")
	}
	var tok string
	if scheme, value, ok := strings.Cut(r.Header.Get("Authorization"), " "); ok && strings.EqualFold(scheme, "Bearer") {
		tok = strings.TrimSpace(value)
	} else if r.Method == http.MethodPost {
		r.Body = http.MaxBytesReader(w, r.Body, 4096)
		if r.ParseForm() == nil {
			tok = r.PostForm.Get("access_token")
		}
	}
	if tok == "" {
		w.Header().Set("WWW-Authenticate", "Bearer")
		tokenError(w, http.StatusUnauthorized, "invalid_request", "")
		return
	}
	var g accessGrant
	if b.keys.open(accessPurpose, tok, &g, b.now()) != nil {
		invalid()
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	_, ok, err := b.store.ssoClient(ctx, g.ClientID)
	if err != nil {
		b.log.Error("looking up OIDC client", "err", err)
		tokenError(w, http.StatusServiceUnavailable, "temporarily_unavailable", "")
		return
	}
	if !ok {
		invalid()
		return
	}
	tokenResponse(w, http.StatusOK, map[string]any{"sub": g.Sub, "email": g.Email, "email_verified": true, "name": g.Name})
}

// oidcLogout is RP-initiated logout: it always ends the Keycloak session, and
// returns to the app only on the evidence of an ID token this provider issued
// to it (D9).
func (b *broker) oidcLogout(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 8192)
	if err := r.ParseForm(); err != nil {
		b.errorPage(w, http.StatusBadRequest, "This sign-out link isn't valid", "Go back to the app and sign out again.")
		return
	}
	p := r.Form
	var s logoutState
	if uri, state := p.Get("post_logout_redirect_uri"), p.Get("state"); uri != "" && len(state) <= maxStateLen {
		if aud, ok := b.oidc.signer.verifyHint(b.loginURL, p.Get("id_token_hint")); ok && aud == p.Get("client_id") {
			ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
			defer cancel()
			client, ok, err := b.store.ssoClient(ctx, aud)
			if err != nil {
				b.internal(w, "looking up OIDC client", err)
				return
			}
			if ok && client.allowsPostLogout(uri) {
				s = logoutState{URI: uri, State: state}
			}
		}
	}
	sealed, err := b.keys.seal("logout", s, logoutTTL, b.now())
	if err != nil {
		b.internal(w, "sealing logout state", err)
		return
	}
	target, err := b.auth.endSessionURL(sealed, b.loginURL+"/signed-out")
	if err != nil {
		b.log.Error("identity provider unavailable", "err", err)
		b.errorPage(w, http.StatusServiceUnavailable, "Sign-out is temporarily unavailable", "Something on our side isn't answering. Please try again in a moment.")
		return
	}
	redirect(w, target)
}
