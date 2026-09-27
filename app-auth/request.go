package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"net"
	"net/http"
	"net/url"
	"strings"
)

// Cookie names. The __Host- prefix makes the browser refuse any of them that
// is not Secure, has a Domain, or has a Path other than "/", so none can be
// planted from a sibling subdomain.
const (
	cookiePrefix  = "__Host-freepod_"
	sessionCookie = cookiePrefix + "session"
	loginCookie   = cookiePrefix + "login"
	flowCookie    = cookiePrefix + "flow_" // + a prefix of the OIDC state
	consentCookie = cookiePrefix + "consent"
)

// identityHeaders are every header the verifier owns on the way to the app.
// The chart lists the same set in authResponseHeaders (plus Cookie), which is
// what makes Traefik delete client-supplied copies; keep the two in step.
var identityHeaders = []string{
	"X-Freepod-User",
	"X-Freepod-Email",
	"X-Freepod-Name",
	"X-Freepod-Jwt",
	"Remote-User",
	"X-Forwarded-User",
	"X-Forwarded-Email",
}

// normalizeHost lowercases a Host header value and drops any port.
func normalizeHost(h string) string {
	h = strings.ToLower(strings.TrimSpace(h))
	if host, _, err := net.SplitHostPort(h); err == nil {
		return host
	}
	return h
}

// safeReturnPath accepts only a path on the same host. Anything that a browser
// could read as another origin -- `//evil`, `/\evil`, a scheme, control
// characters -- becomes "/".
func safeReturnPath(rd string) string {
	if rd == "" || len(rd) > 2048 || rd[0] != '/' {
		return "/"
	}
	if len(rd) > 1 && (rd[1] == '/' || rd[1] == '\\') {
		return "/"
	}
	for _, c := range rd {
		if c < 0x20 || c == 0x7f || c == '\\' {
			return "/"
		}
	}
	u, err := url.Parse(rd)
	if err != nil || u.Scheme != "" || u.Host != "" || u.User != nil {
		return "/"
	}
	return rd
}

// isNavigation reports whether a request is a top-level browser navigation,
// the only kind a redirect to a login page can help.
func isNavigation(method string, h http.Header) bool {
	if method != http.MethodGet && method != http.MethodHead {
		return false
	}
	if mode := h.Get("Sec-Fetch-Mode"); mode != "" {
		return mode == "navigate"
	}
	return strings.Contains(h.Get("Accept"), "text/html")
}

// filterCookies returns the request's cookies minus every platform cookie, as
// one Cookie header value, across however many Cookie lines the request had.
// The raw pairs are passed through untouched rather than re-serialized, so an
// app sees its own cookies exactly as the browser sent them.
func filterCookies(h http.Header) string {
	var kept []string
	for _, line := range h.Values("Cookie") {
		for _, pair := range strings.Split(line, ";") {
			pair = strings.TrimSpace(pair)
			if pair == "" {
				continue
			}
			name, _, _ := strings.Cut(pair, "=")
			if strings.HasPrefix(strings.TrimSpace(name), cookiePrefix) {
				continue
			}
			kept = append(kept, pair)
		}
	}
	return strings.Join(kept, "; ")
}

// cookieValues returns every value sent for a cookie name, in order. A browser
// can send the same name more than once; each is tried rather than trusting
// whichever came first.
func cookieValues(h http.Header, name string) []string {
	var out []string
	for _, line := range h.Values("Cookie") {
		for _, pair := range strings.Split(line, ";") {
			k, v, ok := strings.Cut(strings.TrimSpace(pair), "=")
			if ok && k == name {
				out = append(out, v)
			}
		}
	}
	return out
}

func randomToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func sha256Bytes(s string) []byte {
	sum := sha256.Sum256([]byte(s))
	return sum[:]
}

// hashToken is how a nonce travels to the broker: the app host keeps the
// nonce in a cookie, and only its digest ever leaves in a URL.
func hashToken(s string) string {
	return base64.RawURLEncoding.EncodeToString(sha256Bytes(s))
}

func setCookie(w http.ResponseWriter, name, value string, maxAge int) {
	http.SetCookie(w, &http.Cookie{
		Name:     name,
		Value:    value,
		Path:     "/",
		MaxAge:   maxAge,
		Secure:   true,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
	})
}

func clearCookie(w http.ResponseWriter, name string) {
	setCookie(w, name, "", -1)
}
