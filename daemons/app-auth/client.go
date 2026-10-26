package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"net/url"
	"regexp"
	"strings"
)

// An SSO-enabled deployment is an OIDC client with no client record: its ID is
// the deployment's, its secret is derived (D3), and its redirect URIs are the
// template's declared paths on the deployment's own hostname (D4).
type ssoClient struct {
	ID           string
	Hostname     string
	RedirectURIs []string // https://<hostname><path>, one per valid declared path
	NativeURIs   []string
	PKCE         bool
	Ignored      []string // declared entries that broke the rules, for the log
}

// clientIDPattern is a deployment ID as Postgres prints it. Anything else is no
// client, and is never sent to the database as a uuid it would fail to cast.
var clientIDPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// newSSOClient applies D4 to a template's raw `sso` system values. ok is false
// when no declared path survives, which makes the deployment no client at all.
func newSSOClient(id, hostname string, redirectPaths, nativeURIs json.RawMessage, pkce bool) (ssoClient, bool) {
	c := ssoClient{ID: id, Hostname: strings.ToLower(hostname), PKCE: pkce}
	for _, p := range jsonStrings(redirectPaths, &c.Ignored) {
		if uri, ok := redirectURIFor(c.Hostname, p); ok {
			c.RedirectURIs = append(c.RedirectURIs, uri)
		} else {
			c.Ignored = append(c.Ignored, "sso.redirectPaths: "+p)
		}
	}
	for _, u := range jsonStrings(nativeURIs, &c.Ignored) {
		if validNativeURI(u) {
			c.NativeURIs = append(c.NativeURIs, u)
		} else {
			c.Ignored = append(c.Ignored, "sso.nativeRedirectUris: "+u)
		}
	}
	return c, len(c.RedirectURIs) > 0
}

// jsonStrings reads a JSON array of strings, noting anything else as ignored.
func jsonStrings(raw json.RawMessage, ignored *[]string) []string {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var items []json.RawMessage
	if err := json.Unmarshal(raw, &items); err != nil {
		*ignored = append(*ignored, "not a list: "+string(raw))
		return nil
	}
	var out []string
	for _, it := range items {
		var s string
		if err := json.Unmarshal(it, &s); err != nil {
			*ignored = append(*ignored, "not a string: "+string(it))
			continue
		}
		out = append(out, s)
	}
	return out
}

// redirectURIFor joins a declared path onto the hostname, and refuses any path
// whose join would move the URI off that host: `@evil.example/cb` makes
// evil.example the host, `.evil.example/cb` a subdomain of it (D4).
func redirectURIFor(hostname, path string) (string, bool) {
	if hostname == "" || !strings.HasPrefix(path, "/") || strings.HasPrefix(path, "//") || strings.ContainsAny(path, "?#\\") {
		return "", false
	}
	for _, r := range path {
		if r < 0x20 || r == 0x7f {
			return "", false
		}
	}
	uri := "https://" + hostname + path
	u, err := url.Parse(uri)
	if err != nil || u.User != nil || u.Port() != "" || u.Host != hostname || u.Hostname() != hostname {
		return "", false
	}
	return uri, true
}

// nativeSchemePattern is a private-use scheme in reverse-domain form (RFC 8252
// §7.1): RFC 3986 scheme characters with at least one dot.
var nativeSchemePattern = regexp.MustCompile(`^[a-z][a-z0-9+\-]*(\.[a-z0-9+\-]+)+$`)

func validNativeURI(uri string) bool {
	scheme, _, ok := strings.Cut(uri, ":")
	if !ok || !nativeSchemePattern.MatchString(scheme) || strings.ContainsAny(uri, "#\\") {
		return false
	}
	for _, r := range uri {
		if r <= 0x20 || r == 0x7f {
			return false
		}
	}
	_, err := url.Parse(uri)
	return err == nil
}

func (c ssoClient) allowsRedirect(uri string) bool {
	return c.isWebRedirect(uri) || c.isNativeRedirect(uri)
}

func (c ssoClient) isWebRedirect(uri string) bool {
	for _, u := range c.RedirectURIs {
		if u == uri {
			return true
		}
	}
	return false
}

func (c ssoClient) isNativeRedirect(uri string) bool {
	for _, u := range c.NativeURIs {
		if u == uri {
			return true
		}
	}
	return false
}

// allowsPostLogout is D9: the deployment's root, or any redirect URI.
func (c ssoClient) allowsPostLogout(uri string) bool {
	return uri == "https://"+c.Hostname+"/" || c.allowsRedirect(uri)
}

// clientSecretPrefix versions the derivation; the API derives the same value
// (app/services/app_auth_oidc.py) and a test in each pins one shared vector.
const clientSecretPrefix = "app-oidc-client:v1:"

func deriveClientSecret(key []byte, clientID string) string {
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(clientSecretPrefix + clientID))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// clientSecret is what the platform hands a deployment: derived with the
// first key of the ring.
func (kr *keyring) clientSecret(clientID string) string {
	return deriveClientSecret(kr.keys[0].secret, clientID)
}

// verifyClientSecret accepts a secret derived with any key in the ring, so a
// new key can go in front before every deployment's Secret is republished. It
// tries every key whatever matches, so timing reveals nothing about which.
func (kr *keyring) verifyClientSecret(clientID, secret string) bool {
	ok := 0
	for _, k := range kr.keys {
		ok |= subtle.ConstantTimeCompare([]byte(deriveClientSecret(k.secret, clientID)), []byte(secret))
	}
	return ok == 1
}

// withQuery appends parameters to a redirect URI that may already carry a
// query of its own (a native URI may).
func withQuery(uri string, v url.Values) string {
	sep := "?"
	if strings.Contains(uri, "?") {
		sep = "&"
	}
	return uri + sep + v.Encode()
}
