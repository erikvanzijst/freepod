package main

import (
	"context"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	sessionTTL     = 7 * 24 * time.Hour
	loginNonceTTL  = 10 * time.Minute
	reservedPrefix = "/.freepod/auth/"
)

// session is what the session cookie seals. Host is the audience: a session is
// valid only on the host it was issued for.
type session struct {
	Sub   string `json:"sub"`
	Email string `json:"email"`
	Name  string `json:"name"`
	Host  string `json:"host"`
}

type verifier struct {
	keys     *keyring
	store    store
	loginURL string // https://login.<domain>, no trailing slash
	now      func() time.Time
	log      *slog.Logger
	patterns *patternCache
}

// ServeHTTP answers Traefik's forward-auth request. Traefik describes the
// original request in X-Forwarded-*; with trustForwardHeader unset it always
// sets those from the real request, never from the client (design D4).
//
// A 2xx lets the request through with whichever of identityHeaders and Cookie
// this response carries; Traefik deletes those it was told about first, so
// absent here means absent upstream. Anything else goes back to the browser
// as-is, Set-Cookie and Location included.
func (v *verifier) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	host := normalizeHost(r.Header.Get("X-Forwarded-Host"))
	uri := r.Header.Get("X-Forwarded-Uri")
	method := r.Header.Get("X-Forwarded-Method")
	if host == "" || uri == "" || method == "" {
		http.Error(w, "not a forward-auth request", http.StatusBadRequest)
		return
	}
	target, err := url.ParseRequestURI(uri)
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}

	if strings.HasPrefix(target.Path, reservedPrefix) {
		v.reserved(w, r, host, target)
		return
	}

	sess, ok := v.session(r.Header, host)
	if ok || v.patterns.match(r.URL.Query().Get("p"), target.Path) {
		if cookies := filterCookies(r.Header); cookies != "" {
			w.Header().Set("Cookie", cookies)
		}
		if ok {
			setIdentity(w.Header(), sess)
		}
		w.WriteHeader(http.StatusOK)
		return
	}

	if isNavigation(method, r.Header) {
		v.startLogin(w, host, safeReturnPath(target.RequestURI()))
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusUnauthorized)
	w.Write([]byte("Sign-in required. Navigate to /.freepod/auth/login to sign in.\n"))
}

func setIdentity(h http.Header, s session) {
	h.Set("X-Freepod-User", s.Sub)
	h.Set("Remote-User", s.Sub)
	h.Set("X-Forwarded-User", s.Sub)
	h.Set("X-Freepod-Email", s.Email)
	h.Set("X-Forwarded-Email", s.Email)
	h.Set("X-Freepod-Name", url.PathEscape(s.Name))
}

func (v *verifier) session(h http.Header, host string) (session, bool) {
	for _, raw := range cookieValues(h, sessionCookie) {
		var s session
		if v.keys.open("session", raw, &s, v.now()) == nil && s.Host == host && s.Sub != "" {
			return s, true
		}
	}
	return session{}, false
}

// startLogin marks this browser as the one starting sign-in and sends it to the
// broker. Only the nonce's digest leaves in the URL; the nonce stays in a
// host-only cookie, and redemption requires both (design D7).
func (v *verifier) startLogin(w http.ResponseWriter, host, rd string) {
	nonce := randomToken()
	setCookie(w, loginCookie, nonce, int(loginNonceTTL.Seconds()))
	q := url.Values{"host": {host}, "rd": {rd}, "n": {hashToken(nonce)}}
	redirect(w, v.loginURL+"/start?"+q.Encode())
}

func (v *verifier) reserved(w http.ResponseWriter, r *http.Request, host string, target *url.URL) {
	q := target.Query()
	switch target.Path {
	case reservedPrefix + "login":
		v.startLogin(w, host, safeReturnPath(q.Get("rd")))
	case reservedPrefix + "logout":
		clearCookie(w, sessionCookie)
		redirect(w, "https://"+host+safeReturnPath(q.Get("rd")))
	case reservedPrefix + "callback":
		v.callback(w, r, host, q.Get("code"))
	default:
		http.NotFound(w, r)
	}
}

// callback redeems a broker-issued code into a session on this host. The code
// is consumed by the lookup itself, so every presentation burns it, including
// the ones rejected below -- a login-CSRF attempt destroys the attacker's code.
func (v *verifier) callback(w http.ResponseWriter, r *http.Request, host, code string) {
	clearCookie(w, loginCookie)
	fail := func(reason string) {
		v.log.Info("callback rejected", "host", host, "reason", reason)
		v.failurePage(w, host)
	}
	if code == "" {
		fail("no code")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	rec, fresh, found, err := v.store.redeemCode(ctx, sha256Bytes(code))
	if err != nil {
		v.log.Error("redeeming code", "err", err)
		http.Error(w, "sign-in is temporarily unavailable", http.StatusServiceUnavailable)
		return
	}
	switch {
	case !found:
		fail("unknown or used code")
		return
	case !fresh:
		fail("expired code")
		return
	case rec.Host != host:
		fail("code issued for another host")
		return
	case !v.nonceMatches(r.Header, rec.NonceHash):
		fail("no matching login cookie")
		return
	}
	value, err := v.keys.seal("session", session{
		Sub: rec.Subject, Email: rec.Email, Name: rec.Name, Host: host,
	}, sessionTTL, v.now())
	if err != nil {
		v.log.Error("sealing session", "err", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	setCookie(w, sessionCookie, value, int(sessionTTL.Seconds()))
	redirect(w, "https://"+host+safeReturnPath(rec.ReturnPath))
}

func (v *verifier) nonceMatches(h http.Header, want []byte) bool {
	for _, nonce := range cookieValues(h, loginCookie) {
		if subtle.ConstantTimeCompare(sha256Bytes(nonce), want) == 1 {
			return true
		}
	}
	return false
}

func (v *verifier) failurePage(w http.ResponseWriter, host string) {
	renderPage(w, http.StatusBadRequest, page{
		chrome:   newChrome(v.loginURL),
		Title:    "Sign-in didn't complete",
		Message:  "This sign-in link expired or was already used, or it was opened in a different browser from the one that started signing in.",
		Link:     "https://" + host + reservedPrefix + "login",
		LinkText: "Try again",
	})
}

// redirect always writes an absolute URL. Traefik resolves a relative Location
// from a forward-auth response against the verifier's own address, not the
// app's (design context, fact 3).
func redirect(w http.ResponseWriter, location string) {
	w.Header().Set("Location", location)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusFound)
}

// patternCache compiles each deployment's public patterns once. The key is the
// middleware's `p` parameter verbatim, so it changes exactly when the chart
// renders different patterns. Patterns are RE2, so matching is linear in the
// path whatever a tenant wrote; one that does not compile is dropped, which
// makes no path public by it (fail closed).
type patternCache struct {
	mu    sync.Mutex
	byKey map[string][]*regexp.Regexp
	log   *slog.Logger
}

const patternCacheLimit = 10000

func newPatternCache(log *slog.Logger) *patternCache {
	return &patternCache{byKey: map[string][]*regexp.Regexp{}, log: log}
}

func (c *patternCache) match(key, path string) bool {
	if key == "" {
		return false
	}
	for _, re := range c.compiled(key) {
		if re.MatchString(path) {
			return true
		}
	}
	return false
}

func (c *patternCache) compiled(key string) []*regexp.Regexp {
	c.mu.Lock()
	defer c.mu.Unlock()
	if res, ok := c.byKey[key]; ok {
		return res
	}
	var res []*regexp.Regexp
	var patterns []string
	raw, err := base64.RawURLEncoding.DecodeString(key)
	if err == nil {
		err = json.Unmarshal(raw, &patterns)
	}
	if err != nil {
		c.log.Warn("undecodable public patterns; none apply", "err", err)
	}
	for _, p := range patterns {
		re, err := regexp.Compile(p)
		if err != nil {
			c.log.Warn("public pattern does not compile; ignored", "pattern", p, "err", err)
			continue
		}
		res = append(res, re)
	}
	if len(c.byKey) >= patternCacheLimit {
		c.byKey = map[string][]*regexp.Regexp{}
	}
	c.byKey[key] = res
	return res
}
