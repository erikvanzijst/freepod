package main

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

const wiki = "wiki-alice.freepod.app"

func clientFor(t *testing.T, host, paths, natives string) (ssoClient, bool) {
	t.Helper()
	return newSSOClient("d0c5a1e2-0000-4000-8000-000000000001", host, json.RawMessage(paths), json.RawMessage(natives), true)
}

func TestRedirectURIsMatchExactly(t *testing.T) {
	c, ok := clientFor(t, wiki, `["/oidc/callback"]`, `["app.immich:///oauth-callback"]`)
	if !ok {
		t.Fatal("not a client")
	}
	custom, _ := clientFor(t, "Wiki.Example.com", `["/oidc/callback"]`, "")
	for uri, want := range map[string]bool{
		"https://" + wiki + "/oidc/callback":                  true,
		"app.immich:///oauth-callback":                        true,
		"https://" + wiki + "/shared/page":                    false,
		"https://" + wiki + "/oidc/callback?code=ATTACKER":    false,
		"https://" + wiki + "/oidc/callback#x":                false,
		"https://" + wiki + "/oidc/callback/":                 false,
		"https://" + wiki + "/OIDC/callback":                  false,
		"https://evil.example/oidc/callback":                  false,
		"http://" + wiki + "/oidc/callback":                   false,
		"https://" + wiki + ":443/oidc/callback":              false,
		"https://" + strings.ToUpper(wiki) + "/oidc/callback": false,
		"app.immich:///oauth-callback?x=1":                    false,
		"app.evil:///steal":                                   false,
		"":                                                    false,
	} {
		if got := c.allowsRedirect(uri); got != want {
			t.Errorf("allowsRedirect(%q) = %v", uri, got)
		}
	}
	if !custom.allowsRedirect("https://wiki.example.com/oidc/callback") {
		t.Error("custom domain's callback refused")
	}
}

func TestRedirectPathsCannotLeaveTheHost(t *testing.T) {
	for path, want := range map[string]bool{
		"/oidc/callback":             true,
		"/api/oauth/mobile-redirect": true,
		"/":                          true,
		"@evil.example/cb":           false,
		".evil.example/cb":           false,
		":443@evil.example/cb":       false,
		":8443/cb":                   false,
		"/oidc/callback?next=/":      false,
		"/cb#frag":                   false,
		"//evil.example/cb":          false,
		"/\\evil.example/cb":         false,
		"/cb\\x":                     false,
		"/cb\x00":                    false,
		"/cb\n":                      false,
		"/cb\x7f":                    false,
		"cb":                         false,
		"":                           false,
		"https://evil.example/cb":    false,
	} {
		_, ok := redirectURIFor(wiki, path)
		if ok != want {
			t.Errorf("redirectURIFor(%q) ok=%v, want %v", path, ok, want)
		}
	}

	t.Run("userinfo trick", func(t *testing.T) {
		c, ok := clientFor(t, wiki, `["@evil.example/cb", "/cb"]`, "")
		if !ok || c.allowsRedirect("https://"+wiki+"@evil.example/cb") || len(c.Ignored) != 1 {
			t.Fatalf("%+v", c)
		}
	})
	t.Run("host suffix trick", func(t *testing.T) {
		c, _ := clientFor(t, wiki, `[".evil.example/cb", "/cb"]`, "")
		if c.allowsRedirect("https://" + wiki + ".evil.example/cb") {
			t.Fatal("redirect to another host accepted")
		}
	})
	t.Run("no valid path makes no client", func(t *testing.T) {
		if _, ok := clientFor(t, wiki, `["@evil.example/cb", "/cb?next=/"]`, `["app.immich:///cb"]`); ok {
			t.Fatal("a template whose paths are all ignored made a client")
		}
	})
	t.Run("no declared paths makes no client", func(t *testing.T) {
		for _, raw := range []string{"", "null", "[]", `"/cb"`, `[1, true]`, `{"a":"/cb"}`} {
			if _, ok := clientFor(t, wiki, raw, ""); ok {
				t.Errorf("redirectPaths %s made a client", raw)
			}
		}
	})
}

func TestNativeRedirectURIs(t *testing.T) {
	for uri, want := range map[string]bool{
		"app.immich:///oauth-callback": true,
		"com.example.app:/cb":          true,
		"org.nextcloud:callback":       true,
		"https://collector.example/cb": false,
		"http://collector.example/cb":  false,
		"HTTPS://collector.example/cb": false,
		"immich:///cb":                 false, // not reverse-domain
		"app.immich:///cb#frag":        false,
		"app.immich:///c b":            false,
		".immich:///cb":                false,
		"app..immich:///cb":            false,
		"javascript.x:alert(1)":        true, // a private-use scheme like any other; browsers do not run it
		"":                             false,
	} {
		if got := validNativeURI(uri); got != want {
			t.Errorf("validNativeURI(%q) = %v", uri, got)
		}
	}
	c, ok := clientFor(t, wiki, `["/cb"]`, `["https://collector.example/cb", "app.immich:///oauth-callback"]`)
	if !ok || c.allowsRedirect("https://collector.example/cb") || !c.allowsRedirect("app.immich:///oauth-callback") || len(c.Ignored) != 1 {
		t.Fatalf("%+v", c)
	}
}

func TestPostLogoutRedirects(t *testing.T) {
	c, _ := clientFor(t, wiki, `["/oidc/callback"]`, `["app.immich:///oauth-callback"]`)
	for uri, want := range map[string]bool{
		"https://" + wiki + "/":              true,
		"https://" + wiki + "/oidc/callback": true,
		"app.immich:///oauth-callback":       true,
		"https://" + wiki:                    false,
		"https://" + wiki + "/shared/page":   false,
		"https://evil.example/":              false,
	} {
		if got := c.allowsPostLogout(uri); got != want {
			t.Errorf("allowsPostLogout(%q) = %v", uri, got)
		}
	}
}

// clientSecretVector is shared with api/tests/test_app_auth_oidc.py, so the
// platform and the broker cannot drift apart on the derivation.
const (
	clientSecretVectorKey    = "v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
	clientSecretVectorID     = "3d6f0a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6"
	clientSecretVectorSecret = "nBv_vmyY6kRCnevk9TnrVr_5g2I008el3tTzhNkDr38"
)

func TestClientSecrets(t *testing.T) {
	kr := mustKeyring(t, clientSecretVectorKey)
	if got := kr.clientSecret(clientSecretVectorID); got != clientSecretVectorSecret {
		t.Fatalf("derived %q, want the shared vector", got)
	}
	if !kr.verifyClientSecret(clientSecretVectorID, clientSecretVectorSecret) {
		t.Fatal("correct secret refused")
	}
	other := "3d6f0a8e-1b2c-4d5e-8f90-a1b2c3d4e5f7"
	for name, secret := range map[string]string{
		"another deployment's": kr.clientSecret(other),
		"empty":                "",
		"truncated":            clientSecretVectorSecret[:20],
		"padded":               clientSecretVectorSecret + "=",
	} {
		if kr.verifyClientSecret(clientSecretVectorID, secret) {
			t.Errorf("%s secret accepted", name)
		}
	}

	t.Run("rotation", func(t *testing.T) {
		rotated := mustKeyring(t, "v2:"+testKey('z')+","+clientSecretVectorKey)
		if !rotated.verifyClientSecret(clientSecretVectorID, clientSecretVectorSecret) {
			t.Fatal("secret derived with the previous key refused")
		}
		if rotated.clientSecret(clientSecretVectorID) == clientSecretVectorSecret {
			t.Fatal("the new first key does not derive")
		}
		retired := mustKeyring(t, "v2:"+testKey('z'))
		if retired.verifyClientSecret(clientSecretVectorID, clientSecretVectorSecret) {
			t.Fatal("secret accepted after its key was dropped")
		}
	})

	if raw, _ := base64.RawURLEncoding.DecodeString(clientSecretVectorSecret); len(raw) != 32 {
		t.Fatal("vector is not an HMAC-SHA256")
	}
}
