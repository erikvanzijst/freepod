package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
)

// brandParam carries the app a sign-in is for to Keycloak, whose Freepod
// provider shows it on the sign-in pages and in the emails of that flow
// (tf/deps/keycloak/provider). Keycloak shows nothing it cannot verify, so the
// value is signed with a key derived from this broker's client secret, which
// Keycloak holds too.
const (
	brandParam    = "freepod_app"
	brandKeyLabel = "freepod-app-context:v1"
)

// appIdentity is how a deployment presents itself: its own name, and its own
// icon or else its product's (deployment-identity).
type appIdentity struct {
	Name     string
	IconPath string // under the platform's /api/static/
}

// appBrand is what Keycloak may say about the app: its name and icon, or its
// hostname alone when the deployment's identity could not be read.
type appBrand struct {
	Name string `json:"name,omitempty"`
	Host string `json:"host,omitempty"`
	Icon string `json:"icon,omitempty"`
}

// brand looks up the deployment's identity for Keycloak. Branding is never
// worth a failed sign-in: without it, the app is shown by hostname.
func (b *broker) brand(ctx context.Context, deploymentID, host string) appBrand {
	id, err := b.store.identity(ctx, deploymentID)
	if err != nil {
		b.log.Warn("signing in without the app's name", "deployment", deploymentID, "err", err)
	}
	return newAppBrand(host, id, b.platformURL)
}

func newAppBrand(host string, id appIdentity, platformURL string) appBrand {
	if id.Name == "" {
		return appBrand{Host: host}
	}
	b := appBrand{Name: id.Name, Host: host}
	if id.IconPath != "" && platformURL != "" {
		b.Icon = platformURL + "/api/static/" + id.IconPath
	}
	return b
}

// sign returns `<b64url(json)>.<b64url(hmac)>`, keyed by
// HMAC-SHA256(clientSecret, brandKeyLabel), or "" for an empty brand.
func (b appBrand) sign(clientSecret string) string {
	if b == (appBrand{}) || clientSecret == "" {
		return ""
	}
	raw, err := json.Marshal(b)
	if err != nil {
		return ""
	}
	payload := base64.RawURLEncoding.EncodeToString(raw)
	return payload + "." + base64.RawURLEncoding.EncodeToString(hmacSHA256(hmacSHA256([]byte(clientSecret), []byte(brandKeyLabel)), []byte(payload)))
}

func hmacSHA256(key, data []byte) []byte {
	h := hmac.New(sha256.New, key)
	h.Write(data)
	return h.Sum(nil)
}
